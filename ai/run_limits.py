"""Run-scoped admission limits shared by parallel calls, retries and fallbacks.

Reservations are caller-verified conservative call ceilings, not provider billing
guarantees. Keep an external account/key cap. Unknown charges retain their full
reservation. Deadlines stop new work; running HTTP calls cannot be unbilled.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_limits: ContextVar[RunLimits | None] = ContextVar("worksheet_run_limits", default=None)


class RunLimitExceededError(RuntimeError):
    """A run must fail rather than silently bypass its spending/time limits."""


def _number(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


class RunLimits:
    def __init__(
        self,
        *,
        max_usd: float | None = None,
        deadline_s: float | None = None,
        max_calls: int | None = None,
        call_ceilings: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for value in (max_usd, deadline_s, max_calls):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError("Run limits must be finite and positive")
        self.clock = clock
        self.started = clock()
        self.max_usd, self.deadline_s, self.max_calls = max_usd, deadline_s, max_calls
        self.call_ceilings = call_ceilings or {}
        if any(not math.isfinite(v) or v <= 0 for v in self.call_ceilings.values()):
            raise ValueError("Call reservations must be finite and positive")
        self.charged_or_reserved = 0.0
        self.reported_cost = 0.0
        self.calls = 0
        self.in_flight = 0
        self.unknown_cost_calls = 0
        self.blocked: str | None = None
        self.lock = threading.Lock()

    @classmethod
    def from_env(cls) -> RunLimits:
        raw = json.loads(os.environ.get("WORKSHEET_CALL_CEILINGS_JSON", "{}"))
        if not isinstance(raw, dict) or any(
            not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int | float)
            for k, v in raw.items()
        ):
            raise ValueError("WORKSHEET_CALL_CEILINGS_JSON must map model IDs to USD ceilings")
        max_calls = _number("WORKSHEET_RUN_MAX_CALLS")
        if max_calls is not None and not max_calls.is_integer():
            raise ValueError("WORKSHEET_RUN_MAX_CALLS must be an integer")
        return cls(
            max_usd=_number("WORKSHEET_RUN_MAX_USD"),
            deadline_s=_number("WORKSHEET_RUN_DEADLINE_S"),
            max_calls=int(max_calls) if max_calls is not None else None,
            call_ceilings={k: float(v) for k, v in raw.items()},
        )

    def _check(self) -> None:
        if self.deadline_s is not None and self.clock() - self.started >= self.deadline_s:
            self.blocked = "run deadline exhausted"
        if self.blocked:
            raise RunLimitExceededError(self.blocked)

    def check(self) -> None:
        with self.lock:
            self._check()

    def remaining_s(self) -> float | None:
        with self.lock:
            self._check()
            return (
                max(0, self.deadline_s - (self.clock() - self.started))
                if self.deadline_s is not None
                else None
            )

    def reserve(self, model: str) -> float:
        with self.lock:
            self._check()
            ceiling = self.call_ceilings.get(model, 0.0)
            if self.max_usd is not None:
                if not ceiling:
                    self.blocked = "missing verified call ceiling for model"
                elif self.charged_or_reserved + ceiling > self.max_usd + 1e-9:
                    self.blocked = "run spending reservation exhausted"
            if self.max_calls is not None and self.calls >= self.max_calls:
                self.blocked = "run HTTP attempt limit exhausted"
            self._check()
            self.charged_or_reserved += ceiling
            self.calls += 1
            self.in_flight += 1
            return ceiling

    def settle(self, reservation: float, cost: object) -> None:
        with self.lock:
            self.in_flight -= 1
            if (
                isinstance(cost, int | float)
                and not isinstance(cost, bool)
                and math.isfinite(cost)
                and cost >= 0
            ):
                self.charged_or_reserved += float(cost) - reservation
                self.reported_cost += float(cost)
                if self.max_usd is not None and cost > reservation + 1e-9:
                    self.blocked = "reported cost exceeded declared call ceiling"
            else:
                self.unknown_cost_calls += 1
            if self.max_usd is not None and self.charged_or_reserved > self.max_usd + 1e-9:
                self.blocked = "run spending limit exceeded"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "max_usd": self.max_usd,
                "deadline_s": self.deadline_s,
                "max_calls": self.max_calls,
                "http_attempts": self.calls,
                "in_flight": self.in_flight,
                "reported_cost_usd": self.reported_cost,
                "charged_or_reserved_usd": self.charged_or_reserved,
                "unknown_cost_calls": self.unknown_cost_calls,
                "blocked": self.blocked,
                "deadline_kind": "cooperative; cannot cancel or unbill running requests",
                "budget_kind": "declared call reservations; external billing cap required",
            }


def current_limits() -> RunLimits | None:
    return _limits.get()


def check_run_limits() -> None:
    if limits := current_limits():
        limits.check()


@contextmanager
def run_limits(limits: RunLimits) -> Iterator[None]:
    token = _limits.set(limits)
    try:
        yield
    finally:
        _limits.reset(token)
