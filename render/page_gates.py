"""Full-page worksheet gates: exact-text readback + character consistency.

Policy: fail closed. A generated page ships only when the text gate ran and
passed, and — when a character reference exists — the character judge ran
and approved. When no reference image is provided the character gate is
vacuously satisfied (there is no buddy identity to verify).
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


class PageGateReport(BaseModel):
    """Combined verdict for one generated page attempt."""

    passed: bool
    text: TextGateReport
    character: CharacterJudgeResult
    provider_id: str = ""
    attempt: int = 0


def evaluate_page(
    page_png: bytes,
    required_text: list[str],
    reference_png: bytes | None,
    character_criteria: list[str],
) -> PageGateReport:
    """Run both gates against a generated page image."""
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

    passed = text_report.available and text_report.passed and character_ok
    return PageGateReport(passed=passed, text=text_report, character=character_report)


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
