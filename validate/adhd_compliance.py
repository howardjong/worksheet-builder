"""ADHD compliance validation — checks all ADHD design rules and anti-patterns."""

from __future__ import annotations

from adapt.rules import (
    CHUNKING_RULES,
    INSTRUCTION_LIMITS,
    MAX_SECTIONS_PER_WORKSHEET,
    AccommodationRules,
)
from adapt.schema import AdaptedActivityModel
from validate.schema import ValidationResult


def validate_adhd_compliance(
    adapted: AdaptedActivityModel,
    rules: AccommodationRules | None = None,
) -> ValidationResult:
    """Check adapted activity against every ADHD design rule.

    Checks:
    1. Chunk size within grade limits
    2. Instructions use numbered steps
    3. Instruction word count within limits
    4. Decorative elements <= 2 per page
    5. No dense text blocks (items too long)
    6. Worked example present in first chunk
    7. Self-assessment checklist present
    8. No accuracy-based scoring (anti-pattern)
    9. Decoration zones don't overlap (normalized coords valid)
    10. Time estimates reasonable
    11. Response format variety
    12. Worksheet time limit
    13. Sections per worksheet within grade cap
    """
    result = ValidationResult(validator="adhd_compliance", passed=True, checks_run=0)

    grade = adapted.grade_level

    # Check 1: Chunk size within grade limits
    result.checks_run += 1
    if rules is not None:
        max_allowed = rules.max_items_per_chunk
    else:
        grade_chunks = CHUNKING_RULES.get(grade, CHUNKING_RULES["1"])
        max_allowed = grade_chunks.get("large", 8)
    for chunk in adapted.chunks:
        if len(chunk.items) > max_allowed:
            result.add_violation(
                check="chunk_size_limit",
                message=(
                    f"Chunk {chunk.chunk_id} has {len(chunk.items)} items, "
                    f"max for grade {grade} is {max_allowed}"
                ),
                details={
                    "chunk_id": chunk.chunk_id,
                    "items": len(chunk.items),
                    "max": max_allowed,
                },
            )

    # Check 2: Instructions use numbered steps
    result.checks_run += 1
    for chunk in adapted.chunks:
        for i, step in enumerate(chunk.instructions):
            if step.number != i + 1:
                result.add_violation(
                    check="numbered_instructions",
                    message=(
                        f"Chunk {chunk.chunk_id}: step number {step.number} " f"should be {i + 1}"
                    ),
                )

    # Check 3: Instruction word count within limits
    result.checks_run += 1
    grade_limits = INSTRUCTION_LIMITS.get(grade, INSTRUCTION_LIMITS["1"])
    max_words = grade_limits["max_words"]
    max_steps = grade_limits["max_steps"]
    for chunk in adapted.chunks:
        if len(chunk.instructions) > max_steps:
            result.add_violation(
                check="instruction_step_limit",
                message=(
                    f"Chunk {chunk.chunk_id} has {len(chunk.instructions)} steps, "
                    f"max for grade {grade} is {max_steps}"
                ),
                severity="warning",
            )
        for step in chunk.instructions:
            word_count = len(step.text.split())
            if word_count > max_words:
                result.add_violation(
                    check="instruction_word_limit",
                    message=(
                        f"Chunk {chunk.chunk_id}, step {step.number}: "
                        f"{word_count} words exceeds max {max_words} for grade {grade}"
                    ),
                    severity="warning",
                )

    # Check 4: Decorative elements <= 2
    result.checks_run += 1
    if len(adapted.decoration_zones) > 2:
        result.add_violation(
            check="decoration_budget",
            message=(
                f"{len(adapted.decoration_zones)} decoration zones defined, " f"max is 2 per page"
            ),
        )

    # Check 5: No dense text blocks (items with > 100 words)
    result.checks_run += 1
    for chunk in adapted.chunks:
        for item in chunk.items:
            word_count = len(item.content.split())
            if word_count > 100:
                result.add_violation(
                    check="no_dense_text",
                    message=(
                        f"Item {item.item_id} in chunk {chunk.chunk_id} has "
                        f"{word_count} words — may be too dense"
                    ),
                    severity="warning",
                )

    # Check 6: Worked example in first chunk
    result.checks_run += 1
    if adapted.chunks and adapted.chunks[0].worked_example is None:
        result.add_violation(
            check="worked_example_present",
            message="First chunk should have a worked example",
            severity="warning",
        )

    # Check 7: Self-assessment checklist
    result.checks_run += 1
    if not adapted.self_assessment:
        result.add_violation(
            check="self_assessment_present",
            message="Self-assessment checklist is missing",
            severity="warning",
        )

    # Check 8: No accuracy-based scoring (anti-pattern)
    result.checks_run += 1
    for chunk in adapted.chunks:
        if chunk.reward_event:
            trigger = chunk.reward_event.get("trigger", "")
            if isinstance(trigger, str) and "accuracy" in trigger.lower():
                result.add_violation(
                    check="no_accuracy_scoring",
                    message=(
                        f"Chunk {chunk.chunk_id} has accuracy-based reward — "
                        f"rewards must be effort-based"
                    ),
                )

    # Check 9: Decoration zones valid (normalized 0-1 coords)
    result.checks_run += 1
    for i, zone in enumerate(adapted.decoration_zones):
        if len(zone) != 4:
            result.add_violation(
                check="decoration_zone_valid",
                message=f"Decoration zone {i} has {len(zone)} coords, expected 4",
            )
        elif not all(0.0 <= v <= 1.0 for v in zone):
            result.add_violation(
                check="decoration_zone_valid",
                message=f"Decoration zone {i} has out-of-range coordinates",
            )

    # Check 10: Time estimates reasonable (not > 15 min per chunk)
    result.checks_run += 1
    for chunk in adapted.chunks:
        if chunk.time_estimate:
            # Extract number from "About X minutes"
            minutes = _parse_minutes(chunk.time_estimate)
            if minutes is not None and minutes > 15:
                result.add_violation(
                    check="time_estimate_reasonable",
                    message=(
                        f"Chunk {chunk.chunk_id} time estimate of {minutes} minutes "
                        f"exceeds 15 minute maximum"
                    ),
                    severity="warning",
                )

    # Check 11: Response format variety (multi-worksheet awareness)
    result.checks_run += 1
    formats_used = {chunk.response_format for chunk in adapted.chunks}
    if len(adapted.chunks) >= 3 and len(formats_used) < 2:
        result.add_violation(
            check="format_variety",
            message=(
                f"Only {len(formats_used)} response format(s) used across "
                f"{len(adapted.chunks)} chunks. Varied formats improve engagement."
            ),
            severity="warning",
        )

    # Check 12: Worksheet time limit (max 8 min per mini-worksheet)
    result.checks_run += 1
    if adapted.worksheet_count > 1:
        total_minutes = 0
        for chunk in adapted.chunks:
            if chunk.time_estimate:
                m = _parse_minutes(chunk.time_estimate)
                if m is not None:
                    total_minutes += m
        if total_minutes > 8:
            result.add_violation(
                check="worksheet_time_limit",
                message=(
                    f"Mini-worksheet {adapted.worksheet_number} estimated at "
                    f"{total_minutes} minutes, max is 8 minutes"
                ),
                severity="warning",
            )

    # Check 13: Sections per worksheet (grade-scaled hard cap)
    result.checks_run += 1
    if rules is not None:
        max_sections = rules.max_sections_per_worksheet
    else:
        max_sections = MAX_SECTIONS_PER_WORKSHEET.get(grade, 4)
    if len(adapted.chunks) > max_sections:
        result.add_violation(
            check="sections_per_worksheet",
            message=(
                f"Worksheet has {len(adapted.chunks)} sections, "
                f"max for grade {grade} is {max_sections}"
            ),
            details={"sections": len(adapted.chunks), "max": max_sections},
        )

    return result


def validate_lesson_time_budget(
    worksheets: list[AdaptedActivityModel],
) -> ValidationResult:
    """Validate total time budget across all worksheets in a lesson.

    Cross-worksheet time budget checks:
    - Total time across all worksheets should not exceed 20 minutes (WARNING)
    - Each individual worksheet should stay under 8 minutes (WARNING)

    Args:
        worksheets: List of adapted worksheets for the lesson

    Returns:
        ValidationResult with passed=True (violations are warnings only)
    """
    result = ValidationResult(validator="lesson_time_budget", passed=True, checks_run=0)

    # Check 1: Total time budget across all worksheets
    result.checks_run += 1
    total_minutes = 0
    for worksheet in worksheets:
        for chunk in worksheet.chunks:
            if chunk.time_estimate:
                m = _parse_minutes(chunk.time_estimate)
                if m is not None:
                    total_minutes += m

    if total_minutes > 20:
        result.add_violation(
            check="total_time_budget",
            message=(
                f"Total lesson time estimated at {total_minutes} minutes, "
                f"exceeds recommended 20 minute maximum"
            ),
            severity="warning",
            details={
                "total_minutes": total_minutes,
                "worksheet_count": len(worksheets),
                "max_minutes": 20,
            },
        )

    # Check 2: Individual worksheet time limits
    result.checks_run += 1
    for worksheet in worksheets:
        worksheet_minutes = 0
        for chunk in worksheet.chunks:
            if chunk.time_estimate:
                m = _parse_minutes(chunk.time_estimate)
                if m is not None:
                    worksheet_minutes += m

        if worksheet_minutes > 8:
            worksheet_id = (
                f"{worksheet.worksheet_number}/{worksheet.worksheet_count}"
                if worksheet.worksheet_count > 1
                else "1/1"
            )
            result.add_violation(
                check="worksheet_time_limit",
                message=(
                    f"Worksheet {worksheet_id} estimated at {worksheet_minutes} minutes, "
                    f"exceeds recommended 8 minute maximum per worksheet"
                ),
                severity="warning",
                details={
                    "worksheet_id": worksheet_id,
                    "minutes": worksheet_minutes,
                    "max_minutes": 8,
                },
            )

    return result


def _parse_minutes(text: str) -> int | None:
    """Extract minutes from a time estimate string like 'About 5 minutes'."""
    import re

    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None
