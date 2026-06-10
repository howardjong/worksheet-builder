"""Shared Learning Buddy image consistency judging."""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_JUDGE_MODEL_GEMINI = "gemini-3-flash-preview"
_JUDGE_MODEL_OPENAI = "gpt-5.4"


class CharacterJudgeResult(BaseModel):
    """Result from an optional character consistency judge."""

    available: bool = False
    approved: bool = False
    score: int = 0
    issues: list[str] = Field(default_factory=list)
    judge: str | None = None


def judge_character_consistency(
    reference_bytes: bytes,
    generated_bytes: bytes,
    criteria: list[str],
) -> CharacterJudgeResult:
    """Judge whether generated art preserves the Learning Buddy identity.

    Returns ``available=False`` when no judge can run. Callers choose whether
    that is acceptable for their surface.
    """
    if not reference_bytes or not generated_bytes:
        return CharacterJudgeResult(
            available=False,
            approved=False,
            issues=["missing reference or generated image bytes"],
        )

    result = _judge_with_gemini(reference_bytes, generated_bytes, criteria)
    if result is not None:
        return result

    result = _judge_with_openai(reference_bytes, generated_bytes, criteria)
    if result is not None:
        return result

    return CharacterJudgeResult(
        available=False,
        approved=False,
        score=0,
        issues=["no judge available"],
    )


def _build_judge_prompt(criteria: list[str]) -> str:
    checks = "\n".join(f"- {criterion}" for criterion in criteria)
    return (
        "You are a quality judge for character-consistent image generation. "
        "You are given two images:\n"
        "1. The REFERENCE image of the original Learning Buddy.\n"
        "2. The GENERATED image to evaluate.\n\n"
        "Judge the generated image on these criteria:\n"
        f"{checks}\n\n"
        "Respond with ONLY JSON (no markdown fences):\n"
        '{"approved": true/false, "score": 1-10, "issues": ["issue1"]}\n'
        "Score 7+ means acceptable. Be strict about character identity, "
        "requested items, style fidelity, and clean printable output."
    )


def _judge_with_gemini(
    reference_bytes: bytes,
    generated_bytes: bytes,
    criteria: list[str],
) -> CharacterJudgeResult | None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_JUDGE_MODEL_GEMINI,
            contents=[
                types.Part(text=_build_judge_prompt(criteria)),
                types.Part(
                    inline_data=types.Blob(mime_type="image/png", data=reference_bytes),
                ),
                types.Part(
                    inline_data=types.Blob(mime_type="image/png", data=generated_bytes),
                ),
            ],  # type: ignore[arg-type]
        )
        raw = _parse_json_response(response.text or "")
        return _coerce_result(raw, "gemini")
    except Exception as exc:
        logger.warning("Gemini character judge failed: %s", exc)
        return None


def _judge_with_openai(
    reference_bytes: bytes,
    generated_bytes: bytes,
    criteria: list[str],
) -> CharacterJudgeResult | None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        ref_b64 = base64.b64encode(reference_bytes).decode("utf-8")
        gen_b64 = base64.b64encode(generated_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model=_JUDGE_MODEL_OPENAI,
            max_completion_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_judge_prompt(criteria)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{ref_b64}"},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{gen_b64}"},
                        },
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        raw = _parse_json_response(text)
        return _coerce_result(raw, "openai")
    except Exception as exc:
        logger.warning("OpenAI character judge failed: %s", exc)
        return None


def _parse_json_response(text: str) -> Mapping[str, Any]:
    extracted = _extract_json(text)
    loaded = json.loads(extracted)
    if not isinstance(loaded, dict):
        raise ValueError("judge response must be a JSON object")
    return loaded


def _coerce_result(raw: Mapping[str, Any], judge: str) -> CharacterJudgeResult:
    approved = _strict_approval(raw)
    raw_score = raw.get("score", 0)
    score = int(raw_score) if isinstance(raw_score, int | float | str) else 0
    raw_issues = raw.get("issues", [])
    if isinstance(raw_issues, list):
        issues = [str(issue) for issue in raw_issues]
    elif raw_issues:
        issues = [str(raw_issues)]
    else:
        issues = []
    return CharacterJudgeResult(
        available=True,
        approved=approved,
        score=score,
        issues=issues,
        judge=judge,
    )


def _strict_approval(raw: Mapping[str, Any]) -> bool:
    value = raw.get("approved", raw.get("passed", False))
    return value is True


def _extract_json(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.split("\n")
    json_lines: list[str] = []
    in_block = False
    for line in lines:
        if line.strip().startswith("```") and not in_block:
            in_block = True
            continue
        if line.strip() == "```" and in_block:
            break
        if in_block:
            json_lines.append(line)
    return "\n".join(json_lines)
