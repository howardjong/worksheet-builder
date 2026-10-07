"""Shared Learning Buddy image consistency judging."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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

    from ai import openrouter

    raw = openrouter.complete_json(
        _build_judge_prompt(criteria),
        images=[reference_bytes, generated_bytes],
        role="vision",
        validate=lambda value: (
            isinstance(value.get("approved"), bool) and isinstance(value.get("issues"), list)
        ),
    )
    return (
        _coerce_result(raw, "openrouter")
        if raw is not None
        else CharacterJudgeResult(
            available=False, approved=False, issues=["no OpenRouter judge available"]
        )
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
