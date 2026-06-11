"""Tests for full-page gates (offline; judges stubbed)."""

from __future__ import annotations

import pytest

from companion.character_judge import CharacterJudgeResult


def _text_report(**overrides: object):
    from render.page_gates import TextGateReport

    base: dict = {
        "available": True,
        "passed": True,
        "missing_text": [],
        "misspelled_text": [],
        "judge": "gemini",
    }
    base.update(overrides)
    return TextGateReport(**base)


def test_coerce_text_report_passes_when_nothing_missing() -> None:
    from render.page_gates import _coerce_text_report

    report = _coerce_text_report({"missing": [], "misspelled": []}, judge="gemini")

    assert report.available is True
    assert report.passed is True
    assert report.judge == "gemini"


def test_coerce_text_report_fails_on_missing_or_misspelled() -> None:
    from render.page_gates import _coerce_text_report

    missing = _coerce_text_report({"missing": ["rain"], "misspelled": []}, judge="gemini")
    garbled = _coerce_text_report({"missing": [], "misspelled": ["pluy"]}, judge="gemini")

    assert missing.passed is False
    assert missing.missing_text == ["rain"]
    assert garbled.passed is False
    assert garbled.misspelled_text == ["pluy"]


def test_evaluate_page_passes_with_both_gates_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", ["criteria"])

    assert report.passed is True


def test_evaluate_page_fails_when_text_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(
        page_gates,
        "evaluate_page_text",
        lambda png, req: _text_report(passed=False, missing_text=["rain"]),
    )
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [])

    assert report.passed is False


def test_evaluate_page_fails_closed_when_text_gate_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(
        page_gates,
        "evaluate_page_text",
        lambda png, req: _text_report(available=False, passed=False),
    )
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [])

    assert report.passed is False


def test_evaluate_page_character_gate_vacuous_without_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())

    report = page_gates.evaluate_page(b"png", ["rain"], None, [])

    assert report.passed is True
    assert report.character.available is False


def test_evaluate_page_fails_when_character_judge_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(
            available=True, approved=False, score=3, issues=["wrong hair"]
        ),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [])

    assert report.passed is False
    assert report.character.issues == ["wrong hair"]
