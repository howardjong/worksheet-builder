"""Tests for the opt-in direct-context worksheet compiler."""

from __future__ import annotations

import json

import pytest

from adapt.engine import adapt_lesson
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
from companion.character_identity import CharacterIdentity
from companion.schema import (
    Accommodations,
    AvatarConfig,
    CharacterStyleSheet,
    LearnerProfile,
    Preferences,
)
from skill.schema import LiteracySkillModel, SourceItem


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read and spell CVCe words"],
        target_words=["grade", "slide", "quite"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, slide, quite",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="tune -> tone -> cone -> cane",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sentence",
                content="The slide is quite tall.",
                source_region_index=2,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Ian",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="small",
            response_format_prefs=["write", "circle"],
            font_size_override=18,
            show_time_estimates=True,
        ),
        preferences=Preferences(
            favorite_themes=["roblox_obby"],
            color_preferences=["blue"],
            visual_style="pixel_art",
        ),
        avatar=AvatarConfig(
            base_character="ian_learning_buddy",
            equipped_items={"hat": "blue_cap"},
            style_sheet=CharacterStyleSheet(
                character_block="A consistent blue robot learning buddy.",
                scene_guidelines="Keep the buddy calm and recognizable.",
                item_style_notes="Use blocky accessories.",
                identity_version="identity_test",
            ),
        ),
    )


def _identity() -> CharacterIdentity:
    return CharacterIdentity(
        base_character="ian_learning_buddy",
        base_image_path="assets/characters/ian_learning_buddy.png",
        reference_image_dir="assets/characters/ian_learning_buddy",
        canonical_reference_path="assets/characters/ian_learning_buddy/ref_front.png",
        pose_reference_path=None,
        character_block="A consistent blue robot learning buddy.",
        scene_guidelines="Keep the buddy calm and recognizable.",
        item_style_notes="Use blocky accessories.",
        equipped_items={"hat": "blue_cap"},
        identity_version="identity_test",
    )


def _worksheet(contents: list[str], title: str = "Direct Word Work") -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Practice all source words",
                instructions=[Step(number=1, text="Read and write each word.")],
                items=[
                    ActivityItem(item_id=i + 1, content=text, response_format="write")
                    for i, text in enumerate(contents)
                ],
                response_format="write",
                time_estimate="About 2 minutes",
            ),
        ],
        scaffolding=ScaffoldConfig(
            show_worked_example=True,
            fade_after_chunk=1,
            hint_level="full",
        ),
        theme_id="roblox_obby",
        decoration_zones=[],
        worksheet_title=title,
        worksheet_number=1,
        worksheet_count=1,
    )


def test_prompt_includes_full_source_profile_and_buddy_identity() -> None:
    from adapt.direct_compiler import build_direct_context_prompt

    prompt = build_direct_context_prompt(
        _skill(),
        _profile(),
        _identity(),
        "roblox_obby",
    )

    assert "grade, slide, quite" in prompt
    assert "tune -> tone -> cone -> cane" in prompt
    assert "The slide is quite tall." in prompt
    assert "Name: Ian" in prompt
    assert "Grade: 1" in prompt
    assert "chunking_level" in prompt
    assert "response_format_prefs" in prompt
    assert "favorite_themes" in prompt
    assert "roblox_obby" in prompt
    assert "A consistent blue robot learning buddy." in prompt
    assert "identity_test" in prompt
    assert "AdaptedActivityModel" in prompt
    assert "content coverage" in prompt.lower()


def test_compile_lesson_direct_rejects_missing_target_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt import direct_compiler

    dropped = _worksheet(["slide", "quite", "tune tone cone cane", "The slide is quite tall."])
    monkeypatch.setattr(
        direct_compiler,
        "_call_direct_compiler",
        lambda prompt: json.dumps({"worksheets": [dropped.model_dump(mode="json")]}),
    )

    assert direct_compiler.compile_lesson_direct(_skill(), _profile(), "roblox_obby") is None


def test_feature_flag_disabled_leaves_deterministic_path_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt import direct_compiler

    monkeypatch.delenv("WORKSHEET_DIRECT_COMPILER", raising=False)
    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
    expected = [ws.model_dump() for ws in adapt_lesson(_skill(), _profile(), "roblox_obby")]

    def fail_if_called(prompt: str) -> str | None:
        raise AssertionError("direct compiler should not be called")

    monkeypatch.setattr(direct_compiler, "_call_direct_compiler", fail_if_called)

    actual = [ws.model_dump() for ws in adapt_lesson(_skill(), _profile(), "roblox_obby")]
    assert actual == expected


def test_feature_flag_enabled_uses_valid_direct_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt import direct_compiler

    direct = _worksheet(
        [
            "grade",
            "slide",
            "quite",
            "tune tone cone cane",
            "The slide is quite tall.",
        ],
        title="Direct Compiler Result",
    )
    monkeypatch.setenv("WORKSHEET_DIRECT_COMPILER", "1")
    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
    monkeypatch.setattr(
        direct_compiler,
        "_call_direct_compiler",
        lambda prompt: json.dumps([direct.model_dump(mode="json")]),
    )

    worksheets = adapt_lesson(_skill(), _profile(), "roblox_obby")

    assert [ws.worksheet_title for ws in worksheets] == ["Direct Compiler Result"]


def test_direct_compiler_failure_falls_back_to_deterministic_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt import direct_compiler

    monkeypatch.delenv("WORKSHEET_DIRECT_COMPILER", raising=False)
    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
    expected = [ws.model_dump() for ws in adapt_lesson(_skill(), _profile(), "roblox_obby")]

    monkeypatch.setenv("WORKSHEET_DIRECT_COMPILER", "1")
    monkeypatch.setattr(direct_compiler, "_call_direct_compiler", lambda prompt: None)

    actual = [ws.model_dump() for ws in adapt_lesson(_skill(), _profile(), "roblox_obby")]
    assert actual == expected
