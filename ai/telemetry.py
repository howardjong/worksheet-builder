"""Per-run inference measurements without prompts, images or credentials."""

from __future__ import annotations

import inspect
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from ai.run_limits import RunLimits, check_run_limits, run_limits

_P = ParamSpec("_P")
_T = TypeVar("_T")
_recorder: ContextVar[Recorder | None] = ContextVar("worksheet_recorder", default=None)
_stage: ContextVar[str] = ContextVar("worksheet_stage", default="pipeline")
_candidate: ContextVar[str | None] = ContextVar("worksheet_candidate", default=None)


class Recorder:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.started = time.perf_counter()
        self.events: list[dict[str, Any]] = []
        self.spans: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(
                {
                    "stage": _stage.get(),
                    "candidate_id": _candidate.get(),
                    "finished_s": time.perf_counter() - self.started,
                    **event,
                }
            )

    def record_span(self, name: str, started: float) -> None:
        with self.lock:
            self.spans.append(
                {
                    "stage": name,
                    "started_s": started - self.started,
                    "elapsed_s": time.perf_counter() - started,
                }
            )

    def save(self, succeeded: bool) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        events = list(self.events)
        (self.directory / "inference_calls.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events)
        )
        (self.directory / "timing_summary.json").write_text(
            json.dumps(
                {
                    "pipeline_s": time.perf_counter() - self.started,
                    "completed": succeeded,
                    "stage_spans": self.spans,
                    "inference_http_attempts": len(events),
                    "reported_cost_usd": sum(event.get("cost_usd", 0) for event in events),
                    "cost_is_complete": bool(events)
                    and all("cost_usd" in event for event in events),
                },
                indent=2,
            )
        )


def record_call(event: dict[str, Any]) -> None:
    recorder = _recorder.get()
    if recorder is not None:
        recorder.record(event)


def current_stage() -> str:
    return _stage.get()


@contextmanager
def candidate(identifier: str) -> Iterator[None]:
    token = _candidate.set(identifier)
    try:
        yield
    finally:
        _candidate.reset(token)


def in_stage(name: str) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def decorate(function: Callable[_P, _T]) -> Callable[_P, _T]:
        @wraps(function)
        def measured(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with stage(name):
                return function(*args, **kwargs)

        return measured

    return decorate


@contextmanager
def stage(name: str) -> Iterator[None]:
    check_run_limits()
    started = time.perf_counter()
    token = _stage.set(name)
    try:
        yield
    finally:
        recorder = _recorder.get()
        if recorder is not None:
            recorder.record_span(name, started)
        _stage.reset(token)


def traced_pipeline(function: Callable[_P, _T]) -> Callable[_P, _T]:
    signature = inspect.signature(function)

    @wraps(function)
    def traced(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        bound = signature.bind(*args, **kwargs)
        recorder = Recorder(Path(str(bound.arguments["artifacts_dir"])))
        limits = RunLimits.from_env()
        token = _recorder.set(recorder)
        succeeded = False
        try:
            with run_limits(limits):
                result = function(*args, **kwargs)
                limits.check()
                succeeded = True
                return result
        finally:
            try:
                recorder.save(succeeded)
                (recorder.directory / "run_limits.json").write_text(
                    json.dumps(limits.snapshot(), indent=2)
                )
            finally:
                _recorder.reset(token)

    return traced
