"""Budget and deadline failures must stop requests, including parallel admission."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

from ai import openrouter
from ai.run_limits import RunLimitExceededError, RunLimits, run_limits
from ai.telemetry import traced_pipeline
from tests.test_openrouter import _responses, _text


def test_parallel_admission_reserves_inflight_cost_atomically() -> None:
    limits = RunLimits(max_usd=1, call_ceilings={"model": 0.4})
    barrier = threading.Barrier(4)

    def admit(_: int) -> bool:
        barrier.wait(timeout=3)
        try:
            limits.reserve("model")
            return True
        except RunLimitExceededError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(admit, range(4))) == 2
    assert limits.snapshot()["in_flight"] == 2
    assert limits.snapshot()["charged_or_reserved_usd"] == pytest.approx(0.8)


def test_unknown_charges_keep_reservation_and_reported_charges_reconcile() -> None:
    limits = RunLimits(max_usd=1, call_ceilings={"model": 0.5})
    first = limits.reserve("model")
    second = limits.reserve("model")
    limits.settle(first, None)
    limits.settle(second, 0.2)
    assert limits.snapshot()["charged_or_reserved_usd"] == pytest.approx(0.7)
    with pytest.raises(RunLimitExceededError, match="reservation exhausted"):
        limits.reserve("model")


@pytest.mark.parametrize("fault", ["unpriced", "too_cheap", "attempt_limit"])
def test_invalid_spending_assumptions_stop_before_more_http(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    calls = _responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"cost": 0.2},
                },
            )
        ],
    )
    model = openrouter.models("text")[0]
    limits = RunLimits(
        max_usd=1,
        max_calls=1,
        call_ceilings={} if fault == "unpriced" else {model: 0.1 if fault == "too_cheap" else 0.3},
    )
    with run_limits(limits), pytest.raises(RunLimitExceededError):
        openrouter.complete("private")
        openrouter.complete("private")
    assert len(calls) == (0 if fault == "unpriced" else 1)
    assert limits.snapshot()["in_flight"] == 0


def test_retry_has_its_own_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setattr("ai.openrouter.time.sleep", lambda _: None)
    calls = _responses(monkeypatch, [httpx.Response(503), _text("ok")])
    limits = RunLimits(max_usd=0.5, call_ceilings={openrouter.models("text")[0]: 0.4})
    with run_limits(limits), pytest.raises(RunLimitExceededError, match="reservation exhausted"):
        openrouter.complete("retry")
    assert len(calls) == 1 and limits.snapshot()["unknown_cost_calls"] == 1


def test_deadline_clamps_http_timeout_and_blocks_late_result_and_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    now = [0.0]
    limits = RunLimits(deadline_s=2, clock=lambda: now[0])
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    seen: list[float] = []

    def slow_response(url: str, **kwargs: Any) -> httpx.Response:
        seen.append(kwargs["timeout"])
        now[0] = 3
        return _text("late")

    monkeypatch.setattr(client, "post", slow_response)
    monkeypatch.setattr(openrouter, "_client", client)
    with run_limits(limits), pytest.raises(RunLimitExceededError, match="deadline"):
        openrouter.complete("late")
    assert seen == [2] and limits.snapshot()["in_flight"] == 0
    client.close()


def test_failed_run_saves_sanitized_budget_and_timing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-secret")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.1")
    monkeypatch.setenv("WORKSHEET_CALL_CEILINGS_JSON", "{}")
    calls = _responses(monkeypatch, [])

    @traced_pipeline
    def run(artifacts_dir: str) -> None:
        openrouter.complete("private-name")

    with pytest.raises(RunLimitExceededError):
        run(str(tmp_path))
    assert not calls
    limits = json.loads((tmp_path / "run_limits.json").read_text())
    timing = json.loads((tmp_path / "timing_summary.json").read_text())
    assert limits["blocked"] and not timing["completed"]
    assert "private" not in (tmp_path / "run_limits.json").read_text()


@pytest.mark.parametrize(
    "name,value",
    [
        ("WORKSHEET_RUN_MAX_USD", "nan"),
        ("WORKSHEET_RUN_DEADLINE_S", "0"),
        ("WORKSHEET_RUN_MAX_CALLS", "1.5"),
        ("WORKSHEET_CALL_CEILINGS_JSON", '{"model": true}'),
    ],
)
def test_invalid_limit_configuration_never_silently_disables_caps(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        RunLimits.from_env()
