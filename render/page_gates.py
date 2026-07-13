"""Full-page worksheet gates: exact-text readback + character consistency
+ match-row picture alignment.

Policy: fail closed. A generated page ships only when the text gate ran and
passed, and — when a character reference exists — the character judge ran
and approved, and — when match rows exist — the match-alignment gate ran
and found no row whose picture depicts its own word. When no reference
image is provided the character gate is vacuously satisfied (there is no
buddy identity to verify); when there are no match rows the alignment gate
is vacuously satisfied (there is nothing to check).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from companion.character_judge import (
    CharacterJudgeResult,
    _parse_json_response,  # noqa: PLC2701  # accepted repo idiom: mirrors character_judge structure
    judge_character_consistency,
)
from render.design_spec import WorksheetDesignSpec

logger = logging.getLogger(__name__)

_TEXT_GATE_MODEL_GEMINI = "gemini-3-flash-preview"
_TEXT_GATE_MODEL_OPENAI = "gpt-5.4"


class TextGateReport(BaseModel):
    """Result of the exact-text readback gate."""

    available: bool = False
    passed: bool = False
    missing_text: list[str] = Field(default_factory=list)
    misspelled_text: list[str] = Field(default_factory=list)
    judge: str | None = None


class MatchAlignmentReport(BaseModel):
    """Result of the match-row picture/word alignment gate (D9).

    A match-format worksheet row is only useful if its picture depicts a
    *different* word than the one printed on that row (the derangement is
    the whole point — see adapt/engine.py:_shuffled_mismatch). This gate
    flags rows where the generated picture drew the row's own word instead.
    """

    available: bool = False
    aligned_rows: list[str] = Field(default_factory=list)
    judge: str | None = None

    @property
    def passed(self) -> bool:
        # Fail closed (module policy): this report exists because match rows
        # were requested, so an unavailable judge means unverified, not
        # approved. The no-match-rows vacuous pass lives in evaluate_page,
        # which skips this gate entirely when there is nothing to check.
        return self.available and not self.aligned_rows


class PageGateReport(BaseModel):
    """Combined verdict for one generated page attempt."""

    passed: bool
    text: TextGateReport
    character: CharacterJudgeResult
    match_alignment: MatchAlignmentReport = Field(default_factory=MatchAlignmentReport)
    provider_id: str = ""
    attempt: int = 0


def evaluate_page(
    page_png: bytes,
    required_text: list[str],
    reference_png: bytes | None,
    character_criteria: list[str],
    match_rows: list[str] | None = None,
) -> PageGateReport:
    """Run all gates against a generated page image."""
    text_report = evaluate_page_text(page_png, required_text)

    if reference_png:
        character_report = judge_character_consistency(reference_png, page_png, character_criteria)
        character_ok = character_report.available and character_report.approved
    else:
        character_report = CharacterJudgeResult(
            available=False,
            approved=False,
            issues=["no reference image; character gate skipped"],
        )
        # Vacuously satisfied: no reference image means no buddy identity to
        # verify. Do NOT change this to track character_report.approved — that
        # would block every reference-less page (see vacuous-pass test).
        character_ok = True

    if match_rows:
        match_alignment = _evaluate_match_alignment(page_png, match_rows)
        # Fail closed: rows exist, so an unavailable judge blocks the page.
        match_ok = match_alignment.passed
    else:
        match_alignment = MatchAlignmentReport(available=False)
        # Vacuously satisfied: no match rows on the page means nothing to
        # verify (same shape as the reference-less character gate above).
        match_ok = True

    passed = text_report.available and text_report.passed and character_ok and match_ok
    return PageGateReport(
        passed=passed,
        text=text_report,
        character=character_report,
        match_alignment=match_alignment,
    )


def match_rows_from_spec(spec: WorksheetDesignSpec) -> list[str]:
    """Collect match-row words (one per row, in row order) from a design spec."""
    return [
        item.content
        for section in spec.sections
        if section.response_format == "match"
        for item in section.items
        if item.response_format == "match"
    ]


def evaluate_page_text(page_png: bytes, required_text: list[str]) -> TextGateReport:
    """Vision readback: verify every required string appears, spelled exactly."""
    report = _text_gate_with_gemini(page_png, required_text)
    if report is not None:
        return report
    report = _text_gate_with_openai(page_png, required_text)
    if report is not None:
        return report
    return TextGateReport(available=False, passed=False)


def _build_text_gate_prompt(required_text: list[str]) -> str:
    checklist = "\n".join(f"- {text}" for text in required_text)
    return (
        "You are checking a generated children's worksheet image for text "
        "fidelity.\n"
        "For each required string below, verify it appears in the image, spelled "
        "EXACTLY as written (case-insensitive; ignore minor punctuation spacing).\n\n"
        f"Required strings:\n{checklist}\n\n"
        "Also flag any visible word on the page that is misspelled or garbled, "
        "even if it is not in the list.\n\n"
        "Respond with ONLY JSON (no markdown fences):\n"
        '{"missing": ["required strings not found"], '
        '"misspelled": ["garbled or misspelled visible words"]}'
    )


def _coerce_text_report(raw: Mapping[str, Any], judge: str) -> TextGateReport:
    raw_missing = raw.get("missing", [])
    raw_misspelled = raw.get("misspelled", [])
    missing = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
    misspelled = [str(item) for item in raw_misspelled] if isinstance(raw_misspelled, list) else []
    return TextGateReport(
        available=True,
        passed=not missing and not misspelled,
        missing_text=missing,
        misspelled_text=misspelled,
        judge=judge,
    )


def _text_gate_with_gemini(page_png: bytes, required_text: list[str]) -> TextGateReport | None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_TEXT_GATE_MODEL_GEMINI,
            contents=[
                types.Part(text=_build_text_gate_prompt(required_text)),
                types.Part(
                    inline_data=types.Blob(mime_type="image/png", data=page_png),
                ),
            ],  # type: ignore[arg-type]
        )
        return _coerce_text_report(_parse_json_response(response.text or ""), judge="gemini")
    except Exception as exc:
        logger.warning("Gemini text gate failed: %s", exc)
        return None


def _text_gate_with_openai(page_png: bytes, required_text: list[str]) -> TextGateReport | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import base64

        import openai

        client = openai.OpenAI(api_key=api_key)
        page_b64 = base64.b64encode(page_png).decode("utf-8")
        response = client.chat.completions.create(
            model=_TEXT_GATE_MODEL_OPENAI,
            max_completion_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_text_gate_prompt(required_text)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{page_b64}"},
                        },
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        return _coerce_text_report(_parse_json_response(text), judge="openai")
    except Exception as exc:
        logger.warning("OpenAI text gate failed: %s", exc)
        return None


def _evaluate_match_alignment(page_png: bytes, match_rows: list[str]) -> MatchAlignmentReport:
    """Vision check: does any match-row picture depict its own row's word?"""
    report = _match_alignment_with_gemini(page_png, match_rows)
    if report is not None:
        return report
    report = _match_alignment_with_openai(page_png, match_rows)
    if report is not None:
        return report
    return MatchAlignmentReport(available=False)


def _build_match_alignment_prompt(match_rows: list[str]) -> str:
    checklist = "\n".join(f'- Row with the word "{word}"' for word in match_rows)
    return (
        "You are checking a generated children's worksheet match activity "
        "(a left column of words and a right column of pictures, one per "
        "row, connected by drawn lines).\n"
        "For each row below, look ONLY at the picture printed on that row and "
        "decide: does the picture on the row of word X depict X?\n\n"
        f"Rows to check:\n{checklist}\n\n"
        "The picture on a row should NEVER depict that row's own word — it "
        "must depict a different word from the activity.\n\n"
        "Respond with ONLY JSON (no markdown fences):\n"
        '{"aligned": ["words whose row picture depicts that same word"]}'
    )


def _coerce_match_alignment_report(raw: Mapping[str, Any], judge: str) -> MatchAlignmentReport:
    raw_aligned = raw.get("aligned", [])
    aligned = [str(item) for item in raw_aligned] if isinstance(raw_aligned, list) else []
    return MatchAlignmentReport(available=True, aligned_rows=aligned, judge=judge)


def _match_alignment_with_gemini(
    page_png: bytes, match_rows: list[str]
) -> MatchAlignmentReport | None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_TEXT_GATE_MODEL_GEMINI,
            contents=[
                types.Part(text=_build_match_alignment_prompt(match_rows)),
                types.Part(
                    inline_data=types.Blob(mime_type="image/png", data=page_png),
                ),
            ],  # type: ignore[arg-type]
        )
        return _coerce_match_alignment_report(
            _parse_json_response(response.text or ""), judge="gemini"
        )
    except Exception as exc:
        logger.warning("Gemini match-alignment gate failed: %s", exc)
        return None


def _match_alignment_with_openai(
    page_png: bytes, match_rows: list[str]
) -> MatchAlignmentReport | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import base64

        import openai

        client = openai.OpenAI(api_key=api_key)
        page_b64 = base64.b64encode(page_png).decode("utf-8")
        response = client.chat.completions.create(
            model=_TEXT_GATE_MODEL_OPENAI,
            max_completion_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_match_alignment_prompt(match_rows)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{page_b64}"},
                        },
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        return _coerce_match_alignment_report(_parse_json_response(text), judge="openai")
    except Exception as exc:
        logger.warning("OpenAI match-alignment gate failed: %s", exc)
        return None
