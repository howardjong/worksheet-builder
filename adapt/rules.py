"""ADHD accommodation rules — chunking tables, response format substitutions, constraints."""

from __future__ import annotations

from pydantic import BaseModel

from companion.schema import LearnerProfile

# Items per chunk by grade level and chunking preference
CHUNKING_RULES: dict[str, dict[str, int]] = {
    "K": {"small": 2, "medium": 2, "large": 3},
    "1": {"small": 3, "medium": 4, "large": 5},
    "2": {"small": 4, "medium": 5, "large": 6},
    "3": {"small": 5, "medium": 6, "large": 8},
}

# When a child's preferred format isn't available, substitute equivalent formats
RESPONSE_FORMAT_SUBSTITUTIONS: dict[str, list[str]] = {
    "write": ["circle", "match", "verbal"],
    "fill_blank": ["circle", "match"],
    "trace": ["write", "circle"],
}

# Instruction constraints by grade
INSTRUCTION_LIMITS: dict[str, dict[str, int]] = {
    "K": {"max_words": 8, "max_steps": 2},
    "1": {"max_words": 12, "max_steps": 3},
    "2": {"max_words": 15, "max_steps": 3},
    "3": {"max_words": 20, "max_steps": 4},
}

# Font size minimums by grade
FONT_SIZE_MIN: dict[str, int] = {
    "K": 16,
    "1": 14,
    "2": 12,
    "3": 12,
}

# Time estimate per chunk by grade (minutes)
TIME_ESTIMATE_MINUTES: dict[str, int] = {
    "K": 3,
    "1": 5,
    "2": 5,
    "3": 7,
}

# Color system — consistent across all worksheets
COLOR_SYSTEM: dict[str, str] = {
    "directions": "#2563EB",  # Blue
    "examples": "#16A34A",  # Green
    "rewards": "#D97706",  # Gold
    "content": "#000000",  # Black
    "background": "#FFFFFF",  # White
}


class AccommodationRules(BaseModel):
    """Derived accommodation rules for a specific learner + grade combination."""

    max_items_per_chunk: int
    instruction_max_words: int
    instruction_max_steps: int
    require_worked_example: bool = True
    require_time_estimate: bool = True
    require_self_check: bool = True
    allowed_response_formats: list[str]
    font_size_min: int
    max_decorative_elements: int = 2
    color_system: dict[str, str]
    time_estimate_minutes: int


def build_rules(profile: LearnerProfile) -> AccommodationRules:
    """Build accommodation rules from a learner profile.

    Derives constraints from grade level + profile accommodations.
    """
    grade = profile.grade_level
    accom = profile.accommodations

    # Chunking
    grade_chunks = CHUNKING_RULES.get(grade, CHUNKING_RULES["1"])
    max_items = grade_chunks.get(accom.chunking_level, grade_chunks["medium"])

    # Instruction limits
    grade_limits = INSTRUCTION_LIMITS.get(grade, INSTRUCTION_LIMITS["1"])

    # Font size: profile override wins
    font_min = accom.font_size_override or FONT_SIZE_MIN.get(grade, 12)

    # Response formats: use profile prefs, fallback to defaults
    allowed_formats = (
        list(accom.response_format_prefs) if accom.response_format_prefs else ["write", "circle"]
    )

    # Time estimates
    time_est = TIME_ESTIMATE_MINUTES.get(grade, 5)

    return AccommodationRules(
        max_items_per_chunk=max_items,
        instruction_max_words=grade_limits["max_words"],
        instruction_max_steps=grade_limits["max_steps"],
        require_worked_example=True,
        require_time_estimate=accom.show_time_estimates,
        require_self_check=accom.show_self_check_boxes,
        allowed_response_formats=allowed_formats,
        font_size_min=font_min,
        max_decorative_elements=2,
        color_system=dict(COLOR_SYSTEM),
        time_estimate_minutes=time_est,
    )


def get_substitute_format(preferred: str, available: list[str]) -> str:
    """Find a substitute response format when preferred isn't available."""
    if preferred in available:
        return preferred

    substitutes = RESPONSE_FORMAT_SUBSTITUTIONS.get(preferred, [])
    for sub in substitutes:
        if sub in available:
            return sub

    # Last resort: return first available
    return available[0] if available else preferred
