"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapt.engine import adapt_activity
from companion.schema import LearnerProfile
from render.design_spec import PageSpec, VisualBudget, WorksheetDesignSpec
from render.strategies import RenderContext
from skill.schema import LiteracySkillModel, SourceItem
from theme.engine import load_theme


def _phonics_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc_blending",
        learning_objectives=["Blend CVC words"],
        target_words=["tall", "call", "wall", "fall", "mall", "doll"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="tall, call, wall", source_region_index=0),
            SourceItem(item_type="word_list", content="fall, mall, doll", source_region_index=1),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Test", grade_level="1")


def _design_spec() -> WorksheetDesignSpec:
    return WorksheetDesignSpec(
        render_mode="hybrid_shell",
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        theme_id="roblox_obby",
        theme_name="Roblox Obby Quest",
        learner_name="Test",
        learner_grade_level="1",
        learner_theme_preferences=["roblox_obby"],
        worksheet_title="Word Work",
        worksheet_number=1,
        worksheet_count=1,
        domain="phonics",
        specific_skill="cvc_blending",
        page=PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        visual_budget=VisualBudget(
            style="calm",
            intensity="low",
            max_decorative_elements=2,
            max_colors=4,
        ),
        required_text=[
            "Word Work",
            "Read each word.",
            "tall",
            "call",
        ],
        learning_goal="I can blend CVC words",
    )


@pytest.fixture()
def render_context(tmp_path: Path) -> RenderContext:
    """Minimal RenderContext for hybrid_shell composed-render tests."""
    adapted = adapt_activity(_phonics_skill(), _profile())
    theme = load_theme("roblox_obby")
    return RenderContext(
        design_spec=_design_spec(),
        adapted=adapted,
        theme=theme,
        output_path=tmp_path / "worksheet.pdf",
        artifacts_dir=tmp_path / "artifacts",
    )
