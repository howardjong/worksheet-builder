"""Tests for companion/ — profile, catalog, rewards, and caregiver."""

from __future__ import annotations

import tempfile
from pathlib import Path

from companion.caregiver import adjust_accommodations, view_progress
from companion.catalog import (
    get_affordable_items,
    get_item,
    get_milestone_items,
)
from companion.profile import (
    create_profile,
    ensure_companion_fields,
    update_accommodations,
)
from companion.rewards import (
    MILESTONE_INTERVAL,
    TOKENS_PER_WORKSHEET,
    award_completion,
    equip_item,
    purchase_item,
    unequip_item,
)
from companion.schema import (
    AvatarConfig,
    LearnerProfile,
    Preferences,
    Progress,
    load_profile,
    save_profile,
)

# --- Profile Tests ---


class TestProfile:
    def test_create_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = create_profile("Ian", "1", "robot", profile_dir=tmpdir)
            assert profile.name == "Ian"
            assert profile.grade_level == "1"
            assert profile.avatar is not None
            assert profile.avatar.base_character == "robot"
            assert profile.progress is not None
            # Check file was created
            assert (Path(tmpdir) / "ian.yaml").exists()

    def test_load_save_round_trip(self) -> None:
        profile = LearnerProfile(
            name="Test",
            grade_level="K",
            avatar=AvatarConfig(base_character="unicorn"),
            progress=Progress(worksheets_completed=3, tokens_available=30),
        )
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        save_profile(profile, path)
        loaded = load_profile(path)
        assert loaded.name == "Test"
        assert loaded.avatar is not None
        assert loaded.avatar.base_character == "unicorn"
        assert loaded.progress is not None
        assert loaded.progress.worksheets_completed == 3
        path.unlink()

    def test_update_accommodations(self) -> None:
        profile = LearnerProfile(name="Test", grade_level="1")
        updated = update_accommodations(profile, chunking_level="small", font_size_override=18)
        assert updated.accommodations.chunking_level == "small"
        assert updated.accommodations.font_size_override == 18

    def test_ensure_companion_fields(self) -> None:
        profile = LearnerProfile(name="Test", grade_level="1")
        assert profile.avatar is None
        assert profile.progress is None

        profile = ensure_companion_fields(profile)
        assert profile.avatar is not None
        assert profile.preferences is not None
        assert profile.progress is not None

    def test_pydantic_round_trip(self) -> None:
        profile = LearnerProfile(
            name="Ian",
            grade_level="1",
            avatar=AvatarConfig(
                base_character="astronaut",
                equipped_items=["space_helmet"],
                unlocked_items=["space_helmet", "star_badge"],
            ),
            preferences=Preferences(favorite_themes=["space", "dinosaur"]),
            progress=Progress(worksheets_completed=7, tokens_available=45),
        )
        json_str = profile.model_dump_json()
        restored = LearnerProfile.model_validate_json(json_str)
        assert restored.name == profile.name
        assert restored.avatar is not None
        assert restored.avatar.equipped_items == ["space_helmet"]
        assert restored.progress is not None
        assert restored.progress.worksheets_completed == 7


# --- Catalog Tests ---


class TestCatalog:
    def test_get_item_exists(self) -> None:
        item = get_item("star_badge")
        assert item is not None
        assert item.name == "Star Badge"
        assert item.cost == 5

    def test_get_item_not_found(self) -> None:
        assert get_item("nonexistent_item") is None

    def test_affordable_items(self) -> None:
        items = get_affordable_items(10)
        assert len(items) >= 1
        for item in items:
            assert item.cost <= 10
            assert not item.milestone_only

    def test_affordable_items_with_theme(self) -> None:
        items = get_affordable_items(100, theme="space")
        for item in items:
            assert item.theme in ("space", "any")

    def test_affordable_with_zero_tokens(self) -> None:
        items = get_affordable_items(0)
        for item in items:
            assert item.cost == 0

    def test_milestone_items(self) -> None:
        items = get_milestone_items()
        assert len(items) >= 1
        for item in items:
            assert item.milestone_only


# --- Rewards Tests ---


class TestRewards:
    def test_award_completion_basic(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(),
        )
        result = award_completion(profile, lesson=5)
        assert result.tokens_earned == TOKENS_PER_WORKSHEET
        assert result.tokens_total == TOKENS_PER_WORKSHEET
        assert not result.is_milestone
        assert profile.progress is not None
        assert profile.progress.worksheets_completed == 1

    def test_milestone_at_interval(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(worksheets_completed=MILESTONE_INTERVAL - 1),
        )
        result = award_completion(profile, lesson=10)
        assert result.is_milestone
        assert result.milestone_bonus > 0
        assert result.tokens_earned > TOKENS_PER_WORKSHEET

    def test_milestone_unlocks_item(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(worksheets_completed=MILESTONE_INTERVAL - 1),
        )
        result = award_completion(profile, lesson=10)
        assert len(result.items_unlocked) >= 1
        assert profile.avatar is not None
        assert result.items_unlocked[0] in profile.avatar.unlocked_items

    def test_tokens_accumulate(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(),
        )
        award_completion(profile, lesson=1)
        award_completion(profile, lesson=2)
        award_completion(profile, lesson=3)
        assert profile.progress is not None
        assert profile.progress.tokens_available == TOKENS_PER_WORKSHEET * 3
        assert profile.progress.worksheets_completed == 3

    def test_completion_history_recorded(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(),
        )
        award_completion(profile, lesson=5, skill_domain="phonics")
        assert profile.progress is not None
        assert len(profile.progress.completion_history) == 1
        assert profile.progress.completion_history[0].lesson == 5
        assert profile.progress.completion_history[0].skill_domain == "phonics"

    def test_purchase_item_success(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(tokens_available=20),
        )
        result = purchase_item(profile, "star_badge")  # costs 5
        assert result.success
        assert result.tokens_remaining == 15
        assert "star_badge" in profile.avatar.unlocked_items  # type: ignore[union-attr]

    def test_purchase_insufficient_tokens(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(tokens_available=2),
        )
        result = purchase_item(profile, "star_badge")  # costs 5
        assert not result.success

    def test_purchase_already_owned(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(unlocked_items=["star_badge"]),
            progress=Progress(tokens_available=20),
        )
        result = purchase_item(profile, "star_badge")
        assert not result.success

    def test_purchase_milestone_item_blocked(self) -> None:
        milestone_items = get_milestone_items()
        if milestone_items:
            profile = LearnerProfile(
                name="Test", grade_level="1",
                avatar=AvatarConfig(),
                progress=Progress(tokens_available=100),
            )
            result = purchase_item(profile, milestone_items[0].item_id)
            assert not result.success

    def test_equip_item(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(unlocked_items=["star_badge"]),
        )
        assert equip_item(profile, "star_badge")
        assert "star_badge" in profile.avatar.equipped_items  # type: ignore[union-attr]

    def test_equip_item_not_unlocked(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
        )
        assert not equip_item(profile, "star_badge")

    def test_unequip_item(self) -> None:
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(
                unlocked_items=["star_badge"],
                equipped_items=["star_badge"],
            ),
        )
        assert unequip_item(profile, "star_badge")
        assert "star_badge" not in profile.avatar.equipped_items  # type: ignore[union-attr]

    def test_effort_based_not_accuracy(self) -> None:
        """Tokens are always the same regardless of 'performance'."""
        profile = LearnerProfile(
            name="Test", grade_level="1",
            avatar=AvatarConfig(),
            progress=Progress(),
        )
        r1 = award_completion(profile, lesson=1)
        r2 = award_completion(profile, lesson=2)
        # Both non-milestone completions earn the same tokens
        assert r1.tokens_earned == r2.tokens_earned == TOKENS_PER_WORKSHEET


# --- Caregiver Tests ---


class TestCaregiver:
    def test_view_progress(self) -> None:
        profile = LearnerProfile(
            name="Ian", grade_level="1",
            progress=Progress(
                worksheets_completed=7,
                tokens_available=45,
                milestones_reached=[1],
            ),
        )
        report = view_progress(profile)
        assert report.name == "Ian"
        assert report.worksheets_completed == 7
        assert report.tokens_available == 45
        assert 1 in report.milestones_reached

    def test_view_progress_empty(self) -> None:
        profile = LearnerProfile(name="New", grade_level="K")
        report = view_progress(profile)
        assert report.worksheets_completed == 0
        assert report.tokens_available == 0

    def test_adjust_accommodations(self) -> None:
        profile = LearnerProfile(name="Test", grade_level="1")
        updated = adjust_accommodations(profile, chunking_level="small")
        assert updated.accommodations.chunking_level == "small"

    def test_accommodation_summary_in_report(self) -> None:
        profile = LearnerProfile(name="Test", grade_level="1")
        report = view_progress(profile)
        assert "chunking_level" in report.accommodation_summary
        assert report.accommodation_summary["chunking_level"] == "medium"
