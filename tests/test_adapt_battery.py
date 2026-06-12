"""Tests for adapt_battery.py — old-loop vs new-planner scorecard."""

from __future__ import annotations

from adapt_battery import AdaptBatteryRow, build_scorecard


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
