"""Learner profile schema — MVP fields only.

Companion layer fields (avatar, preferences, progress, operational_signals)
are Optional and added post-core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class Accommodations(BaseModel):
    """ADHD accommodation settings for a learner."""

    chunking_level: str = "medium"  # "small" | "medium" | "large"
    response_format_prefs: list[str] = Field(
        default_factory=lambda: ["write", "circle"]
    )
    font_size_override: int | None = None
    show_time_estimates: bool = True
    show_self_check_boxes: bool = True


class LearnerProfile(BaseModel):
    """Core learner profile — MVP fields required, companion fields optional."""

    name: str
    grade_level: str  # "K" | "1" | "2" | "3"
    accommodations: Accommodations = Field(default_factory=Accommodations)

    # --- Companion layer fields (post-core, all Optional) ---
    avatar: dict[str, Any] | None = None
    preferences: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    operational_signals: dict[str, Any] | None = None


def load_profile(path: str | Path) -> LearnerProfile:
    """Load a LearnerProfile from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return LearnerProfile.model_validate(data)


def save_profile(profile: LearnerProfile, path: str | Path) -> None:
    """Save a LearnerProfile to a YAML file."""
    with open(path, "w") as f:
        yaml.dump(profile.model_dump(exclude_none=True), f, default_flow_style=False)
