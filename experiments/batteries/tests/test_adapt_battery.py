"""Tests for adapt_battery.py — old-loop vs new-planner scorecard."""

from __future__ import annotations

from experiments.batteries.adapt_battery import (
    AdaptBatteryRow,
    GateResult,
    build_scorecard,
    evaluate_gate,
    gate_over_runs,
)


def _row(
    input_name: str,
    variant: str,
    *,
    approved: bool | None = None,
    outcome: str = "planned_approved",
    coverage: bool | None = True,
    adhd: bool | None = True,
    error: str | None = None,
) -> AdaptBatteryRow:
    return AdaptBatteryRow(
        input_name=input_name,
        variant=variant,
        outcome=outcome,
        judge_approved=approved,
        judge_score=0.86 if approved else None,
        sections_per_worksheet=[3, 3, 2],
        content_coverage_passed=coverage,
        adhd_compliance_passed=adhd,
        error=error,
    )


def _approved_3input_rows() -> list[AdaptBatteryRow]:
    """3 inputs: planner approves 2/3, coverage >= loop, adhd all pass."""
    rows: list[AdaptBatteryRow] = []
    for name, planner_ok in (("A", True), ("B", True), ("C", False)):
        rows.append(_row(name, "loop", approved=False, outcome="gpt_takeover", coverage=False))
        rows.append(
            _row(
                name,
                "planner",
                approved=planner_ok,
                outcome="planned_approved" if planner_ok else "planned_rejected_fallback",
                coverage=planner_ok,
            )
        )
    return rows


def test_scorecard_lists_both_variants() -> None:
    rows = [
        AdaptBatteryRow(
            input_name="IMG_0004",
            variant="loop",
            outcome="gpt_takeover_unjudged",
            judge_approved=None,
            judge_score=None,
            sections_per_worksheet=[9],
            content_coverage_passed=False,
            adhd_compliance_passed=False,
        ),
        AdaptBatteryRow(
            input_name="IMG_0004",
            variant="planner",
            outcome="planned_approved",
            judge_approved=True,
            judge_score=0.86,
            sections_per_worksheet=[3, 3, 2],
            content_coverage_passed=True,
            adhd_compliance_passed=True,
        ),
    ]
    card = build_scorecard(rows)

    assert "IMG_0004" in card
    assert "loop" in card and "planner" in card
    assert "gpt_takeover_unjudged" in card
    assert "planned_approved" in card
    assert "0.86" in card
    assert "3/3/2" in card


def test_scorecard_shows_errors() -> None:
    rows = [
        AdaptBatteryRow(
            input_name="IMG_0003",
            variant="planner",
            outcome="error",
            judge_approved=None,
            judge_score=None,
            sections_per_worksheet=[],
            content_coverage_passed=None,
            adhd_compliance_passed=None,
            error="boom",
        )
    ]
    card = build_scorecard(rows)

    assert "error" in card
    assert "boom" in card


def test_evaluate_gate_passes_with_majority_approved() -> None:
    result = evaluate_gate(_approved_3input_rows())

    assert isinstance(result, GateResult)
    assert result.passed is True


def test_evaluate_gate_fails_with_too_few_approved() -> None:
    rows = _approved_3input_rows()
    # flip B's planner cell to rejected → only 1/3 approved
    for i, r in enumerate(rows):
        if r.input_name == "B" and r.variant == "planner":
            rows[i] = _row(
                "B", "planner", approved=False, outcome="planned_rejected_fallback", coverage=False
            )
    result = evaluate_gate(rows)

    assert result.passed is False
    assert any("approv" in reason.lower() for reason in result.reasons)


def test_evaluate_gate_fails_on_planner_error_cell() -> None:
    rows = _approved_3input_rows()
    rows.append(
        _row("D", "planner", approved=None, outcome="error", coverage=None, adhd=None, error="boom")
    )
    result = evaluate_gate(rows)

    assert result.passed is False
    assert any("error" in reason.lower() for reason in result.reasons)


def test_evaluate_gate_fails_when_coverage_below_loop() -> None:
    rows = _approved_3input_rows()
    # make every loop cell pass coverage so planner (2) < loop (3)
    for i, r in enumerate(rows):
        if r.variant == "loop":
            rows[i] = _row(
                r.input_name, "loop", approved=False, outcome="gpt_takeover", coverage=True
            )
    result = evaluate_gate(rows)

    assert result.passed is False
    assert any("coverage" in reason.lower() for reason in result.reasons)


def test_gate_over_runs_requires_two_consecutive_passes() -> None:
    p = GateResult(passed=True, reasons=[])
    f = GateResult(passed=False, reasons=["x"])

    assert gate_over_runs([p, p]) is True
    assert gate_over_runs([p, f]) is False
    assert gate_over_runs([f, p, p]) is True
    assert gate_over_runs([p, f, p]) is False
    assert gate_over_runs([p]) is False  # one run cannot be "consecutive"
