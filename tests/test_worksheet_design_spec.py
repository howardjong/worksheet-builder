"""Tests for renderer-neutral worksheet design specs."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from companion.schema import LearnerProfile, Preferences
from theme.schema import ThemeConfig


def _adapted() -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source_hash",
        skill_model_hash="skill_hash",
        learner_profile_hash="profile_hash",
        grade_level="1",
        domain="phonics",
        specific_skill="vowel teams ai ay",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Read vowel team words",
                instructions=[
                    Step(number=1, text="Read each word."),
                    Step(number=2, text="Circle the vowel team."),
                ],
                worked_example=Example(
                    instruction="Try this first:",
                    content="rain has ai",
                ),
                items=[
                    ActivityItem(
                        item_id=1,
                        content="rain",
                        response_format="write",
                        answer="rain",
                    ),
                    ActivityItem(
                        item_id=2,
                        content="play",
                        response_format="fill_blank",
                        answer="ay",
                    ),
                    ActivityItem(
                        item_id=3,
                        content="tree",
                        response_format="read_aloud",
                    ),
                ],
                response_format="write",
                time_estimate="About 3 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="geometry_dash",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_title="Vowel Team Adventure",
        worksheet_number=1,
        worksheet_count=2,
    )


def test_design_spec_round_trips_and_preserves_required_text() -> None:
    from render.design_spec import compile_worksheet_design_spec

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(
        name="Ian",
        grade_level="1",
        preferences=Preferences(
            favorite_themes=["roblox_obby", "geometry_dash"],
            visual_style="pixel_art",
        ),
    )

    spec = compile_worksheet_design_spec(_adapted(), theme, profile, render_mode="image_prompt")
    roundtrip = spec.__class__.model_validate_json(spec.model_dump_json())

    assert roundtrip.page.width_pt == 612
    assert roundtrip.page.height_pt == 792
    assert roundtrip.render_mode == "image_prompt"
    assert roundtrip.theme_id == "geometry_dash"
    assert roundtrip.theme_name == "Geometry Dash Calm"
    assert roundtrip.visual_budget.style == "calm"
    assert roundtrip.visual_budget.max_decorative_elements == 2
    assert "geometry_dash" in roundtrip.learner_theme_preferences
    assert "Vowel Team Adventure" in roundtrip.required_text
    assert "Read each word." in roundtrip.required_text
    assert "Circle the vowel team." in roundtrip.required_text
    assert "rain has ai" in roundtrip.required_text
    assert "rain" in roundtrip.required_text
    assert "play" in roundtrip.required_text
    assert "tree" in roundtrip.required_text
    assert {zone.item_id for zone in roundtrip.answer_zones} == {1, 2}


def test_design_spec_rejects_invalid_visual_intensity() -> None:
    from render.design_spec import VisualBudget, VisualIntensity

    with pytest.raises(ValidationError):
        VisualBudget(
            style="calm",
            intensity=cast(VisualIntensity, "chaotic"),
            max_decorative_elements=2,
            max_colors=4,
        )


def test_design_spec_high_intensity_profile() -> None:
    from render.design_spec import compile_worksheet_design_spec

    theme = ThemeConfig(name="Roblox Obby")
    profile = LearnerProfile(
        name="Ian",
        grade_level="1",
        preferences=Preferences(
            favorite_themes=["roblox_obby"],
            visual_style="pixel_art",
            visual_intensity="high",
        ),
    )

    spec = compile_worksheet_design_spec(_adapted(), theme, profile, render_mode="hybrid_shell")

    assert spec.visual_budget.intensity == "high"
    assert spec.visual_budget.max_decorative_elements == 6
    assert spec.visual_budget.max_colors == 6


def test_design_spec_low_intensity_profile() -> None:
    from render.design_spec import compile_worksheet_design_spec

    theme = ThemeConfig(name="Roblox Obby")
    profile = LearnerProfile(
        name="Ian",
        grade_level="1",
        preferences=Preferences(
            favorite_themes=["roblox_obby"],
            visual_intensity="low",
        ),
    )

    spec = compile_worksheet_design_spec(_adapted(), theme, profile, render_mode="hybrid_shell")

    assert spec.visual_budget.intensity == "low"
    assert spec.visual_budget.max_decorative_elements == 1
    assert spec.visual_budget.max_colors == 3


def test_design_spec_dial_unset_matches_legacy() -> None:
    # Dial off (no visual_intensity) → exact legacy theme-derived budget.
    from render.design_spec import compile_worksheet_design_spec

    theme = ThemeConfig(name="Geometry Dash Calm")  # calm, max_per_page=2
    profile = LearnerProfile(
        name="Ian",
        grade_level="1",
        preferences=Preferences(favorite_themes=["roblox_obby"], visual_style="pixel_art"),
    )

    spec = compile_worksheet_design_spec(_adapted(), theme, profile, render_mode="image_prompt")

    assert spec.visual_budget.style == "calm"
    assert spec.visual_budget.intensity == "low"
    assert spec.visual_budget.max_decorative_elements == 2
    assert spec.visual_budget.max_colors == 4


def test_visual_budget_rejects_over_intensity_budget() -> None:
    from render.design_spec import VisualBudget

    # A calm-tier (medium) budget may not pack a high-tier decoration count.
    with pytest.raises(ValidationError):
        VisualBudget(
            style="calm",
            intensity="medium",
            max_decorative_elements=6,
            max_colors=4,
        )
    with pytest.raises(ValidationError):
        VisualBudget(
            style="calm",
            intensity="low",
            max_decorative_elements=2,
            max_colors=6,
        )


def test_visual_budget_high_allows_full_budget() -> None:
    from render.design_spec import VisualBudget

    budget = VisualBudget(
        style="energetic",
        intensity="high",
        max_decorative_elements=6,
        max_colors=6,
    )
    assert budget.max_decorative_elements == 6
    assert budget.max_colors == 6


def test_design_spec_rejects_non_print_page_size() -> None:
    from render.design_spec import PageSpec

    with pytest.raises(ValidationError):
        PageSpec(width_pt=500, height_pt=500, margin_pt=54)


def test_design_spec_preserves_section_grouping() -> None:
    from render.design_spec import compile_worksheet_design_spec

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(name="Ian", grade_level="1")

    spec = compile_worksheet_design_spec(_adapted(), theme, profile, render_mode="image_gen")

    assert spec.render_mode == "image_gen"
    assert len(spec.sections) == 1
    section = spec.sections[0]
    assert section.chunk_id == 1
    assert section.micro_goal == "Read vowel team words"
    assert section.instructions == ["Read each word.", "Circle the vowel team."]
    assert section.worked_example_instruction == "Try this first:"
    assert section.worked_example_content == "rain has ai"
    assert section.time_estimate == "About 3 minutes"
    assert [item.content for item in section.items] == ["rain", "play", "tree"]
    assert section.items[1].response_format == "fill_blank"
    assert section.items[1].answer == "ay"
    assert spec.self_assessment == []
    assert spec.break_prompt is None


def test_required_text_excludes_raw_skill_slug() -> None:
    from render.design_spec import compile_worksheet_design_spec

    adapted = _adapted()
    adapted.specific_skill = "decodable_text_cvce"

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(name="Ian", grade_level="1")

    spec = compile_worksheet_design_spec(adapted, theme, profile, render_mode="image_gen")

    assert "decodable_text_cvce" not in spec.required_text
    assert spec.worksheet_title == "Vowel Team Adventure"
    assert "Vowel Team Adventure" in spec.required_text


def test_required_text_excludes_answer_keys() -> None:
    from render.design_spec import compile_worksheet_design_spec

    adapted = _adapted()
    adapted.chunks[0].items[1].answer = "zzz_marker"

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(name="Ian", grade_level="1")

    spec = compile_worksheet_design_spec(adapted, theme, profile, render_mode="image_gen")

    # The child writes answers; they are never rendered, so the text gate must
    # not demand them.
    assert "zzz_marker" not in spec.required_text
    # Item content and options ARE rendered, so they remain required.
    assert "play" in spec.required_text


def test_worksheet_title_fallback_is_humanized() -> None:
    from render.design_spec import compile_worksheet_design_spec

    adapted = _adapted()
    adapted.worksheet_title = None
    adapted.specific_skill = "decodable_text_cvce"

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(name="Ian", grade_level="1")

    spec = compile_worksheet_design_spec(adapted, theme, profile, render_mode="image_gen")

    assert spec.worksheet_title == "Decodable Text Cvce"
    assert "Decodable Text Cvce" in spec.required_text
    assert "decodable_text_cvce" not in spec.required_text


def test_design_spec_sections_normalize_missing_example_and_options() -> None:
    from render.design_spec import compile_worksheet_design_spec

    adapted = _adapted()
    adapted.chunks[0].worked_example = None
    adapted.chunks[0].items[0].options = None

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(name="Ian", grade_level="1")

    spec = compile_worksheet_design_spec(adapted, theme, profile, render_mode="image_gen")

    section = spec.sections[0]
    assert section.worked_example_instruction is None
    assert section.worked_example_content is None
    assert section.items[0].options == []
