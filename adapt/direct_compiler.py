"""Direct-context worksheet compiler for full-source lesson planning.

The provider boundary is intentionally inert by default. Tests and future
provider implementations can replace `_call_direct_compiler()` without changing
the parser, validation, or deterministic fallback behavior.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from adapt.schema import AdaptedActivityModel
from companion.character_identity import CharacterIdentity
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel
from validate.content_coverage import validate_content_coverage_for_package

logger = logging.getLogger(__name__)


def build_direct_context_prompt(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    character_identity: CharacterIdentity | None,
    theme_id: str,
) -> str:
    """Build a strict prompt with full source context and output expectations."""

    source_items = "\n".join(
        (
            f"{index}. type={source_item.item_type}; "
            f"region={source_item.source_region_index}; "
            f"content={source_item.content}; "
            f"metadata={source_item.metadata}"
        )
        for index, source_item in enumerate(skill.source_items, start=1)
    )
    if not source_items:
        source_items = "(no source items)"

    accommodations = profile.accommodations.model_dump()
    preferences = profile.preferences.model_dump() if profile.preferences else {}
    buddy_summary = _character_identity_summary(character_identity)

    return f"""You are compiling print-first literacy worksheets for a child ages 5-8.

Use the complete source worksheet context below. Do not summarize it down to
target words only.

## Skill
Template: {skill.template_type}
Domain: {skill.domain}
Specific skill: {skill.specific_skill}
Grade level: {skill.grade_level}
Learning objectives: {skill.learning_objectives}
Target words: {skill.target_words}
Response types: {skill.response_types}
Theme: {theme_id}

## Full Source Items
{source_items}

## Learner Profile
Name: {profile.name}
Grade: {profile.grade_level}
Accommodations: {accommodations}
Preferences: {preferences}

## Learning Buddy Identity
{buddy_summary}

## Strict Output Expectations
- Return only JSON. No markdown fences, prose, or comments.
- Return a JSON array of AdaptedActivityModel objects.
- Every object must validate against the existing AdaptedActivityModel schema.
- Preserve the domain, specific skill, grade level, source content, and response
  expectations from the source worksheet.
- Include all target words and all student-facing source_items across the
  worksheet package.
- Include word-chain words, student-facing sentences, and decodable passages
  when they are present in the source.
- The package must pass deterministic content coverage validation before it is
  accepted.
"""


def compile_lesson_direct(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str,
    character_identity: CharacterIdentity | None = None,
) -> list[AdaptedActivityModel] | None:
    """Compile worksheets from direct context, or return None for fallback."""

    prompt = build_direct_context_prompt(skill, profile, character_identity, theme_id)
    try:
        response_text = _call_direct_compiler(prompt)
    except Exception as exc:
        logger.warning("Direct compiler call failed: %s", exc)
        return None

    if not response_text:
        return None

    worksheets = _parse_direct_compiler_response(response_text)
    if not worksheets:
        return None

    coverage = validate_content_coverage_for_package(skill, worksheets)
    if not coverage.passed:
        logger.warning(
            "Direct compiler output failed content coverage: %s",
            "; ".join(violation.message for violation in coverage.violations),
        )
        return None

    return worksheets


def _call_direct_compiler(prompt: str) -> str | None:
    """Provider call boundary.

    Future provider wiring can live here or replace this function in tests. The
    default returns None so enabling WORKSHEET_DIRECT_COMPILER without provider
    configuration still falls back to the stable deterministic path.
    """

    return None


def _parse_direct_compiler_response(response_text: str) -> list[AdaptedActivityModel] | None:
    try:
        data = json.loads(_extract_json(response_text))
        worksheet_payloads = _worksheet_payloads(data)
        if worksheet_payloads is None:
            return None
        return [AdaptedActivityModel.model_validate(worksheet) for worksheet in worksheet_payloads]
    except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
        logger.warning("Failed to parse direct compiler output: %s", exc)
        return None


def _worksheet_payloads(data: Any) -> list[Any] | None:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        worksheets = data.get("worksheets")
        if isinstance(worksheets, list):
            return worksheets
    return None


def _extract_json(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    json_lines: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") and not in_block:
            in_block = True
            continue
        if stripped == "```" and in_block:
            break
        if in_block:
            json_lines.append(line)
    return "\n".join(json_lines).strip()


def _character_identity_summary(character_identity: CharacterIdentity | None) -> str:
    if character_identity is None:
        return "No Learning Buddy identity was provided."

    equipped_items = (
        character_identity.equipped_items if character_identity.equipped_items else "(none)"
    )
    return "\n".join(
        [
            f"Base character: {character_identity.base_character}",
            f"Identity version: {character_identity.identity_version}",
            f"Character description: {character_identity.character_block}",
            f"Scene guidelines: {character_identity.scene_guidelines}",
            f"Item style notes: {character_identity.item_style_notes}",
            f"Equipped items: {equipped_items}",
            f"Canonical reference: {character_identity.canonical_reference_path}",
            f"Pose reference: {character_identity.pose_reference_path}",
        ]
    )
