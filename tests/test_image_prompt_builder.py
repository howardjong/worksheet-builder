"""Tests for full-page image prompt assembly."""

from __future__ import annotations

from typing import Any

from adapt.schema import FeedbackPanel
from render.design_spec import (
    PageSpec,
    SectionItemSpec,
    SectionSpec,
    VisualBudget,
    WorksheetDesignSpec,
)


def _spec(**overrides: object) -> WorksheetDesignSpec:
    base: dict[str, Any] = {  # Any required: **-unpacking into typed Pydantic constructor
        "render_mode": "image_gen",
        "source_hash": "src",
        "skill_model_hash": "skill",
        "learner_profile_hash": "prof",
        "theme_id": "roblox_obby",
        "theme_name": "Roblox Obby Quest",
        "learner_name": "Ian",
        "learner_grade_level": "1",
        "worksheet_title": "Word Work",
        "worksheet_number": 1,
        "worksheet_count": 2,
        "domain": "phonics",
        "specific_skill": "vowel teams ai ay",
        "page": PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        "visual_budget": VisualBudget(
            style="calm", intensity="low", max_decorative_elements=2, max_colors=4
        ),
        "required_text": ["Word Work", "rain", "play"],
        "sections": [
            SectionSpec(
                chunk_id=1,
                micro_goal="Build 3 new words",
                instructions=["Read the starting word.", "Write the new word."],
                worked_example_instruction="Watch how the letters change:",
                worked_example_content="rain -> main",
                time_estimate="About 2 minutes",
                response_format="write",
                items=[
                    SectionItemSpec(
                        item_id=1, content="rain", response_format="write", answer="main"
                    ),
                    SectionItemSpec(
                        item_id=2,
                        content="play",
                        response_format="circle",
                        options=["play", "tray", "plop"],
                    ),
                ],
            )
        ],
        "learning_goal": "I can read words with the y pattern",
        "feedback": FeedbackPanel(
            goal_statement="I can read words with the y pattern", show_decision_hint=True
        ),
        "break_prompt": "Stand up and stretch!",
    }
    base.update(overrides)
    return WorksheetDesignSpec(**base)


def test_prompt_includes_sections_items_and_exact_text_rules() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())

    assert "Word Work" in prompt
    assert 'Section 1 banner text: "Build 3 new words"' in prompt
    assert 'Numbered instruction 1: "Read the starting word."' in prompt
    assert '"rain -> main"' in prompt
    assert 'Item 1: "rain"' in prompt
    assert "play, tray, plop" in prompt
    assert "EXACTLY as written" in prompt
    assert "I can read words with the y pattern" in prompt
    assert "Stand up and stretch!" in prompt


def test_prompt_damping_block_uses_visual_budget_numbers() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())

    assert "at most 4 accent colors" in prompt
    assert "Exactly 2 small purely decorative accents" in prompt
    assert "calm and tidy" in prompt
    assert "never put patterns, gradients, or scene art behind text" in prompt


def test_prompt_zero_decorations_branch() -> None:
    from render.image_prompt_builder import build_page_prompt

    spec = _spec(
        visual_budget=VisualBudget(
            style="calm", intensity="medium", max_decorative_elements=0, max_colors=3
        )
    )
    prompt = build_page_prompt(spec)

    assert "No purely decorative elements" in prompt
    assert "at most 3 accent colors" in prompt


def test_prompt_includes_character_and_theme_blocks_when_provided() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(
        _spec(),
        character_block="a blocky boy avatar with rainbow spiky hair",
        scene_guidelines="Compose scenes like calm printable learning panels.",
        theme_environment="light blue walls and simple geometric platforms",
        theme_palette="bright avatar colors, pale backgrounds",
        art_style="roblox_2d_comic_avatar",
    )

    assert "rainbow spiky hair" in prompt
    assert "matching the attached reference image" in prompt
    assert "light blue walls" in prompt
    assert "roblox_2d_comic_avatar" in prompt


def test_prompt_omits_character_section_without_character_block() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())

    assert "Learning Buddy" not in prompt


def test_prompt_high_intensity_branch() -> None:
    from render.image_prompt_builder import build_page_prompt

    spec = _spec(
        visual_budget=VisualBudget(
            style="energetic", intensity="high", max_decorative_elements=2, max_colors=4
        )
    )
    prompt = build_page_prompt(spec)

    assert "bold and energetic chrome" in prompt


def test_goal_ribbon_on_sheet_one_running_line_after() -> None:
    from render.image_prompt_builder import build_page_prompt

    p1 = build_page_prompt(_spec(worksheet_number=1))
    p2 = build_page_prompt(_spec(worksheet_number=2))
    assert 'goal ribbon with exact text: "I can read words with the y pattern"' in p1
    assert "running goal line" in p2
    assert "Skill focus" not in p1  # replaced by the goal ribbon


def test_typography_rules_present() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())
    assert "## Typography rules (required)" in prompt
    assert "exactly THREE text sizes" in prompt
    assert "60%" in prompt


def test_buddy_action_threaded_and_rotation_distinct() -> None:
    from render.image_prompt_builder import build_page_prompt
    from render.pose_planner import PAGE_POSE_ROTATION, page_pose

    prompt = build_page_prompt(_spec(), character_block="blocky boy", buddy_action=page_pose(2))
    assert page_pose(2) in prompt
    assert page_pose(1) != page_pose(2) != page_pose(3)
    assert page_pose(1 + len(PAGE_POSE_ROTATION)) == page_pose(1)


def test_feedback_strip_and_parent_log() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())
    assert 'exact text: "How did it go? Circle one for each part."' in prompt
    assert 'titled with exact text: "Grown-up quick log"' in prompt
    assert "smooth / choppy" in prompt
    assert "step back one lesson" in prompt  # hint present when show_decision_hint=True


def test_prompt_version_bumped() -> None:
    from render.image_prompt_builder import PROMPT_VERSION

    assert PROMPT_VERSION == "page_prompt_v4"


def _spec_with_fill_blank_options() -> WorksheetDesignSpec:
    return _spec(
        sections=[
            SectionSpec(
                chunk_id=1,
                micro_goal="Fill in 1 missing letter",
                instructions=[
                    "Look at the word with a missing letter.",
                    "Circle the missing letter.",
                ],
                worked_example_instruction=None,
                worked_example_content=None,
                time_estimate="About 2 minutes",
                response_format="fill_blank",
                items=[
                    SectionItemSpec(
                        item_id=1,
                        content="c_t",
                        response_format="fill_blank",
                        answer="a",
                        options=["a", "e", "i", "o", "u"],
                    ),
                ],
            )
        ],
    )


def test_fill_blank_with_options_renders_circle_affordance() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec_with_fill_blank_options())
    assert "circle" in prompt.lower()
    assert "handwriting line below" not in prompt


def test_prompt_version_bumped_for_uat_fixes() -> None:
    from render.image_prompt_builder import PROMPT_VERSION

    assert PROMPT_VERSION == "page_prompt_v4"
