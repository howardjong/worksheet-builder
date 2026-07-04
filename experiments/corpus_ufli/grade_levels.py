"""Shared grade-level derivation for UFLI lesson identifiers."""

from __future__ import annotations

_GRADE_RANGES: list[tuple[int, int, str]] = [
    (1, 34, "K"),
    (35, 64, "1"),
    (65, 94, "1"),
    (95, 128, "2"),
]

_ALPHA_LESSONS = set("ABCDEFGHIJ")


def derive_grade(lesson_id: str) -> str:
    """Derive grade level from a UFLI lesson identifier."""
    if lesson_id.upper() in _ALPHA_LESSONS:
        return "K"
    try:
        num = int(lesson_id)
    except ValueError:
        return "K"
    for start, end, grade in _GRADE_RANGES:
        if start <= num <= end:
            return grade
    return "2"
