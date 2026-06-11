"""Tests for full-page image prompt assembly."""

from __future__ import annotations

from typing import Any

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
        "self_assessment": ["I can read ai words"],
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
    assert "I can read ai words" in prompt
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
