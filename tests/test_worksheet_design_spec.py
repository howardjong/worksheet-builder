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


def test_design_spec_rejects_non_print_page_size() -> None:
    from render.design_spec import PageSpec

    with pytest.raises(ValidationError):
        PageSpec(width_pt=500, height_pt=500, margin_pt=54)
