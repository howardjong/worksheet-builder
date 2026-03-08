"""Learner profile schema with companion layer models."""

from __future__ import annotations

from pathlib import Path

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


class AvatarConfig(BaseModel):
    """Avatar customization state."""

    base_character: str = "robot"  # "robot" | "unicorn" | "astronaut"
    base_colors: dict[str, str] = Field(
        default_factory=lambda: {"primary": "#4A90D9", "secondary": "#F5A623", "accent": "#7ED321"}
    )
    equipped_items: list[str] = Field(default_factory=list)
    unlocked_items: list[str] = Field(default_factory=list)


class Preferences(BaseModel):
    """Child preferences for themes and visual style."""

    favorite_themes: list[str] = Field(default_factory=lambda: ["space"])
    color_preferences: list[str] = Field(default_factory=list)
    visual_style: str = "cute_cartoon"  # "cute_cartoon" | "comic_book" | "pixel_art"


class CompletionRecord(BaseModel):
    """Record of a single worksheet completion."""

    lesson: int
    timestamp: str  # ISO format
    tokens_earned: int = 0
    skill_domain: str = ""


class Progress(BaseModel):
    """Learner progress tracking."""

    worksheets_completed: int = 0
    current_lesson: int = 0
    tokens_available: int = 0
    tokens_lifetime: int = 0
    milestones_reached: list[int] = Field(default_factory=list)
    completion_history: list[CompletionRecord] = Field(default_factory=list)


class OperationalSignals(BaseModel):
    """Operational tracking signals (inform accommodations, not scores)."""

    avg_session_duration: float = 0.0
    avg_chunks_per_session: float = 0.0
    hint_usage_rate: float = 0.0
    skip_rate: float = 0.0


class LearnerProfile(BaseModel):
    """Complete learner profile — MVP fields required, companion fields optional."""

    name: str
    grade_level: str  # "K" | "1" | "2" | "3"
    accommodations: Accommodations = Field(default_factory=Accommodations)

    # --- Companion layer fields (all Optional with defaults) ---
    avatar: AvatarConfig | None = None
    preferences: Preferences | None = None
    progress: Progress | None = None
    operational_signals: OperationalSignals | None = None


def load_profile(path: str | Path) -> LearnerProfile:
    """Load a LearnerProfile from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return LearnerProfile.model_validate(data)


def save_profile(profile: LearnerProfile, path: str | Path) -> None:
    """Save a LearnerProfile to a YAML file."""
    with open(path, "w") as f:
        yaml.dump(profile.model_dump(exclude_none=True), f, default_flow_style=False)
