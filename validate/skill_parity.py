"""Skill-parity validation — ensures adapted output preserves instructional intent."""

from __future__ import annotations

from adapt.schema import AdaptedActivityModel
from skill.schema import LiteracySkillModel
from skill.taxonomy import get_domain_grade_range
from validate.schema import ValidationResult

# Grade ordering for age-band checks
_GRADE_ORDER = {"K": 0, "1": 1, "2": 2, "3": 3}


def validate_skill_parity(
    source_skill: LiteracySkillModel,
    adapted: AdaptedActivityModel,
) -> ValidationResult:
    """Validate that the adapted activity preserves the instructional intent.

    Does NOT require the original word list to appear verbatim. Valid adaptations
    may use different words, orderings, or item counts as long as they exercise
    the same literacy skill.

    Checks:
    1. Domain preserved (same literacy domain)
    2. Specific skill preserved (same skill pattern)
    3. Grade level appropriate
    4. Response types compatible
    5. No empty adaptation (at least one chunk with items)
    """
    result = ValidationResult(validator="skill_parity", passed=True, checks_run=0)

    # Check 1: Domain preserved
    result.checks_run += 1
    if adapted.domain != source_skill.domain:
        result.add_violation(
            check="domain_preserved",
            message=(
                f"Domain drift: source is '{source_skill.domain}', "
                f"adapted is '{adapted.domain}'"
            ),
            details={"source": source_skill.domain, "adapted": adapted.domain},
        )

    # Check 2: Specific skill preserved
    result.checks_run += 1
    if adapted.specific_skill != source_skill.specific_skill:
        result.add_violation(
            check="skill_preserved",
            message=(
                f"Skill drift: source targets '{source_skill.specific_skill}', "
                f"adapted targets '{adapted.specific_skill}'"
            ),
            severity="warning",
            details={
                "source": source_skill.specific_skill,
                "adapted": adapted.specific_skill,
            },
        )

    # Check 3: Grade level appropriate
    result.checks_run += 1
    source_grade = _GRADE_ORDER.get(source_skill.grade_level, 1)
    adapted_grade = _GRADE_ORDER.get(adapted.grade_level, 1)
    if abs(source_grade - adapted_grade) > 1:
        result.add_violation(
            check="grade_appropriate",
            message=(
                f"Grade band violation: source is grade {source_skill.grade_level}, "
                f"adapted is grade {adapted.grade_level} (more than 1 level apart)"
            ),
            details={
                "source_grade": source_skill.grade_level,
                "adapted_grade": adapted.grade_level,
            },
        )

    # Check 4: Response types compatible
    result.checks_run += 1
    adapted_formats = set()
    for chunk in adapted.chunks:
        adapted_formats.add(chunk.response_format)
        for item in chunk.items:
            adapted_formats.add(item.response_format)

    # At least one response type should be compatible with skill domain
    domain_compatible = _compatible_formats_for_domain(source_skill.domain)
    if adapted_formats and not adapted_formats & domain_compatible:
        result.add_violation(
            check="response_types_compatible",
            message=(
                f"Response format mismatch: '{source_skill.domain}' domain expects "
                f"formats like {domain_compatible}, got {adapted_formats}"
            ),
            severity="warning",
        )

    # Check 5: Non-empty adaptation
    result.checks_run += 1
    total_items = sum(len(chunk.items) for chunk in adapted.chunks)
    if total_items == 0:
        result.add_violation(
            check="non_empty",
            message="Adapted activity has no practice items",
        )

    return result


def validate_age_band(
    adapted: AdaptedActivityModel,
    target_grade: str,
) -> ValidationResult:
    """Ensure adapted output is developmentally appropriate for target grade.

    Checks:
    1. Grade matches target
    2. Domain is valid for grade range
    3. Item count per chunk is grade-appropriate
    """
    result = ValidationResult(validator="age_band", passed=True, checks_run=0)

    # Check 1: Grade alignment
    result.checks_run += 1
    if adapted.grade_level != target_grade:
        result.add_violation(
            check="grade_match",
            message=(
                f"Adapted grade '{adapted.grade_level}' doesn't match "
                f"target grade '{target_grade}'"
            ),
            severity="warning",
        )

    # Check 2: Domain valid for grade
    result.checks_run += 1
    valid_grades = get_domain_grade_range(adapted.domain)
    if valid_grades and target_grade not in valid_grades:
        result.add_violation(
            check="domain_grade_range",
            message=(
                f"Domain '{adapted.domain}' is not typically taught in "
                f"grade {target_grade} (expected {valid_grades})"
            ),
            severity="warning",
        )

    # Check 3: Item count sanity (no chunk should have more than 10 items)
    result.checks_run += 1
    for chunk in adapted.chunks:
        if len(chunk.items) > 10:
            result.add_violation(
                check="item_count_sanity",
                message=(
                    f"Chunk {chunk.chunk_id} has {len(chunk.items)} items "
                    f"(max recommended: 10)"
                ),
            )

    return result


def _compatible_formats_for_domain(domain: str) -> set[str]:
    """Return response formats that are compatible with a literacy domain."""
    return {
        "phonemic_awareness": {"circle", "verbal", "match", "write"},
        "phonics": {"write", "circle", "match", "verbal", "trace", "read_aloud"},
        "fluency": {"read_aloud", "verbal"},
        "vocabulary": {"write", "circle", "match", "verbal"},
        "comprehension": {"write", "circle", "verbal", "match"},
        "writing": {"write", "trace"},
    }.get(domain, {"write", "circle", "verbal"})
