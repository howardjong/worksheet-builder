"""Caregiver/teacher controls — progress visibility and accommodation adjustments."""

from __future__ import annotations

from pydantic import BaseModel, Field

from companion.profile import update_accommodations
from companion.schema import LearnerProfile, Progress


class ProgressReport(BaseModel):
    """Summary of learner progress for caregiver review."""

    name: str
    grade_level: str
    worksheets_completed: int = 0
    current_lesson: int = 0
    tokens_available: int = 0
    tokens_lifetime: int = 0
    milestones_reached: list[int] = Field(default_factory=list)
    skills_practiced: list[str] = Field(default_factory=list)
    accommodation_summary: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)


def view_progress(profile: LearnerProfile) -> ProgressReport:
    """Generate a progress report for caregiver review."""
    progress = profile.progress or Progress()

    # Extract unique skill domains from completion history
    skills = list({
        r.skill_domain for r in progress.completion_history if r.skill_domain
    })

    # Summarize accommodations
    accom = profile.accommodations
    accom_summary: dict[str, str | int | bool | list[str]] = {
        "chunking_level": accom.chunking_level,
        "response_formats": accom.response_format_prefs,
        "show_time_estimates": accom.show_time_estimates,
        "show_self_check_boxes": accom.show_self_check_boxes,
    }
    if accom.font_size_override:
        accom_summary["font_size_override"] = accom.font_size_override

    return ProgressReport(
        name=profile.name,
        grade_level=profile.grade_level,
        worksheets_completed=progress.worksheets_completed,
        current_lesson=progress.current_lesson,
        tokens_available=progress.tokens_available,
        tokens_lifetime=progress.tokens_lifetime,
        milestones_reached=list(progress.milestones_reached),
        skills_practiced=skills,
        accommodation_summary=accom_summary,
    )


def adjust_accommodations(
    profile: LearnerProfile,
    **kwargs: str | int | bool | list[str] | None,
) -> LearnerProfile:
    """Update accommodation settings (delegates to profile module)."""
    return update_accommodations(profile, **kwargs)
