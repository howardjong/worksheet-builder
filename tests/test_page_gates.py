"""Tests for full-page gates (offline; judges stubbed)."""

from __future__ import annotations

from typing import Any

import pytest

from companion.character_judge import CharacterJudgeResult
from render.page_gates import TextGateReport


def _text_report(**overrides: object) -> TextGateReport:
    base: dict[str, Any] = {  # Any required: **-unpacking into typed Pydantic constructor
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


def test_evaluate_page_rejects_when_match_row_picture_aligns_with_its_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9: a match-row picture that depicts its own row's word must reject the
    page attempt (the picture must depict the shuffled neighbor, never the
    row's own word)."""
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )
    monkeypatch.setattr(
        page_gates,
        "_evaluate_match_alignment",
        lambda png, match_rows: page_gates.MatchAlignmentReport(
            available=True, aligned_rows=["grade"]
        ),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [], match_rows=["grade", "chase"])

    assert report.passed is False
    assert report.match_alignment.aligned_rows == ["grade"]


def test_evaluate_page_passes_when_no_match_rows_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )
    monkeypatch.setattr(
        page_gates,
        "_evaluate_match_alignment",
        lambda png, match_rows: page_gates.MatchAlignmentReport(available=True, aligned_rows=[]),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [], match_rows=["grade", "chase"])

    assert report.passed is True
    assert report.match_alignment.aligned_rows == []


def test_evaluate_page_fails_closed_when_match_rows_exist_but_gate_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module policy is fail closed: match rows exist but both vision providers
    fail, so the page must NOT ship unverified (mirrors the text-gate
    fail-closed test)."""
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )
    # Both providers fail (no key / API error / unparseable response) → None.
    monkeypatch.setattr(page_gates, "_match_alignment_with_gemini", lambda png, rows: None)
    monkeypatch.setattr(page_gates, "_match_alignment_with_openai", lambda png, rows: None)

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [], match_rows=["grade", "chase"])

    assert report.passed is False
    assert report.match_alignment.available is False


def test_evaluate_page_vacuous_pass_without_match_rows_never_calls_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No match rows on the page → nothing to verify → vacuous pass, and the
    match-alignment judge must not be called at all."""
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(available=True, approved=True, score=9),
    )

    def _must_not_be_called(png: bytes, rows: list[str]) -> object:
        raise AssertionError("match-alignment gate must not run without match rows")

    monkeypatch.setattr(page_gates, "_evaluate_match_alignment", _must_not_be_called)

    empty_rows: list[str] | None
    for empty_rows in (None, []):
        report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [], match_rows=empty_rows)
        assert report.passed is True
