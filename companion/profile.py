"""Learner profile CRUD operations."""

from __future__ import annotations

from pathlib import Path

from companion.schema import (
    Accommodations,
    AvatarConfig,
    LearnerProfile,
    Preferences,
    Progress,
    load_profile,
    save_profile,
)


def create_profile(
    name: str,
    grade_level: str,
    base_character: str = "robot",
    profile_dir: str = "profiles",
) -> LearnerProfile:
    """Create a new learner profile with defaults."""
    profile = LearnerProfile(
        name=name,
        grade_level=grade_level,
        avatar=AvatarConfig(base_character=base_character),
        preferences=Preferences(),
        progress=Progress(),
    )

    # Save to disk
    path = Path(profile_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = name.lower().replace(" ", "_") + ".yaml"
    save_profile(profile, path / filename)

    return profile


def update_accommodations(
    profile: LearnerProfile,
    **kwargs: str | int | bool | list[str] | None,
) -> LearnerProfile:
    """Update accommodation settings on a profile."""
    accom_data = profile.accommodations.model_dump()
    for key, value in kwargs.items():
        if hasattr(profile.accommodations, key):
            accom_data[key] = value
    profile.accommodations = Accommodations.model_validate(accom_data)
    return profile


def ensure_companion_fields(profile: LearnerProfile) -> LearnerProfile:
    """Ensure all companion layer fields are initialized."""
    if profile.avatar is None:
        profile.avatar = AvatarConfig()
    if profile.preferences is None:
        profile.preferences = Preferences()
    if profile.progress is None:
        profile.progress = Progress()
    return profile


__all__ = [
    "create_profile",
    "ensure_companion_fields",
    "load_profile",
    "save_profile",
    "update_accommodations",
]
