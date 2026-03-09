"""Learner profile schema with companion layer models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


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

    base_character: str = "rainbow_roblox"
    base_colors: dict[str, str] = Field(
        default_factory=lambda: {"primary": "#4A90D9", "secondary": "#F5A623", "accent": "#7ED321"}
    )
    equipped_items: dict[str, str] = Field(default_factory=dict)  # slot -> item_id
    unlocked_items: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_equipped_list(cls, values: Any) -> Any:
        """Migrate old list format to dict format on load."""
        if isinstance(values, dict):
            equipped = values.get("equipped_items")
            if isinstance(equipped, list):
                # Convert list of item_ids to slot -> item_id dict
                new_equipped: dict[str, str] = {}
                for item_id in equipped:
                    from companion.catalog import get_item
                    cat_item = get_item(item_id)
                    if cat_item:
                        new_equipped[cat_item.slot] = item_id
                values["equipped_items"] = new_equipped
        return values


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
