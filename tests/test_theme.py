"""Tests for theme/engine.py and theme/schema.py."""

from __future__ import annotations

from adapt.engine import adapt_activity
from adapt.schema import AdaptedActivityModel
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from theme.engine import apply_theme, load_theme
from theme.schema import ThemedModel


def _phonics_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc_blending",
        learning_objectives=["Blend CVC words"],
        target_words=["tall", "call", "wall"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="tall, call, wall", source_region_index=0),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Test", grade_level="1")


def _adapted() -> AdaptedActivityModel:
    return adapt_activity(_phonics_skill(), _profile())


class TestLoadTheme:
    def test_load_space_theme(self) -> None:
        theme = load_theme("space")
        assert theme.name == "Space Adventure"
        assert theme.style == "calm"

    def test_load_underwater_theme(self) -> None:
        theme = load_theme("underwater")
        assert theme.name == "Ocean Explorer"

    def test_load_dinosaur_theme(self) -> None:
        theme = load_theme("dinosaur")
        assert theme.name == "Dino Discovery"

    def test_load_unknown_returns_default(self) -> None:
        theme = load_theme("nonexistent")
        assert theme.name == "Default"
        assert theme.style == "calm"

    def test_theme_has_colors(self) -> None:
        theme = load_theme("space")
        assert theme.colors.directions.startswith("#")
        assert theme.colors.examples.startswith("#")
        assert theme.colors.text.startswith("#")

    def test_theme_has_decorative_config(self) -> None:
        theme = load_theme("space")
        assert theme.decorative_elements.max_per_page == 2
        assert len(theme.decorative_elements.assets) >= 1


class TestApplyTheme:
    def test_apply_produces_themed_model(self) -> None:
        adapted = _adapted()
        theme = load_theme("space")
        themed = apply_theme(adapted, theme)
        assert themed.theme.name == "Space Adventure"
        assert len(themed.adapted_json) > 0

    def test_theme_swap_changes_visuals(self) -> None:
        adapted = _adapted()
        space = apply_theme(adapted, load_theme("space"))
        dino = apply_theme(adapted, load_theme("dinosaur"))
        assert space.adapted_json == dino.adapted_json
        assert space.theme.name != dino.theme.name

    def test_decoration_placements_respect_zones(self) -> None:
        adapted = _adapted()
        theme = load_theme("space")
        themed = apply_theme(adapted, theme)
        for placement in themed.decoration_placements:
            assert "asset" in placement
            assert "x0" in placement
            assert "y0" in placement

    def test_decoration_count_within_budget(self) -> None:
        adapted = _adapted()
        theme = load_theme("space")
        themed = apply_theme(adapted, theme)
        assert len(themed.decoration_placements) <= theme.decorative_elements.max_per_page

    def test_pydantic_round_trip(self) -> None:
        adapted = _adapted()
        theme = load_theme("space")
        themed = apply_theme(adapted, theme)
        json_str = themed.model_dump_json()
        restored = ThemedModel.model_validate_json(json_str)
        assert restored.theme.name == themed.theme.name
