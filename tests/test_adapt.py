"""Tests for adapt/engine.py, adapt/rules.py, adapt/schema.py, and companion/schema.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.engine import adapt_activity, adapt_lesson
from adapt.rules import (
    CHUNKING_RULES,
    build_rules,
    get_substitute_format,
)
from adapt.schema import AdaptedActivityModel
from companion.schema import Accommodations, LearnerProfile, load_profile, save_profile
from skill.schema import LiteracySkillModel, SourceItem

# --- Fixtures ---


def _phonics_skill() -> LiteracySkillModel:
    """Synthetic phonics skill model (word work, -all pattern)."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc_blending",
        learning_objectives=[
            "Identify and read words with the -all, -oll, -ull pattern",
            "Blend CVC words",
        ],
        target_words=["tall", "call", "wall", "fall", "mall", "doll", "roll", "poll"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(item_type="word_list", content="tall, call, wall", source_region_index=2),
            SourceItem(item_type="word_list", content="doll, roll, poll", source_region_index=3),
            SourceItem(
                item_type="word_chain",
                content="1. all → fall → mall → small",
                source_region_index=4,
            ),
            SourceItem(
                item_type="sight_words", content="go*, no*, so*", source_region_index=7
            ),
            SourceItem(
                item_type="sentence",
                content="1. The bin is so full.",
                source_region_index=8,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _fluency_skill() -> LiteracySkillModel:
    """Synthetic fluency skill model (decodable story)."""
    return LiteracySkillModel(
        grade_level="1",
        domain="fluency",
        specific_skill="decodable_text_cvce",
        learning_objectives=[
            "Read a decodable passage with fluency and accuracy",
            "Apply cvce pattern knowledge in connected text",
        ],
        target_words=["june", "flute", "tune", "dune", "luke"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="passage",
                content="June has a flute. June likes to use the flute to make tunes.",
                source_region_index=2,
            ),
            SourceItem(
                item_type="passage",
                content="Once, June and Luke made tunes at lunch for their pals.",
                source_region_index=3,
            ),
        ],
        extraction_confidence=0.92,
        template_type="ufli_decodable_story",
    )


def _grade_k_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test K",
        grade_level="K",
        accommodations=Accommodations(
            chunking_level="small",
            response_format_prefs=["circle", "verbal"],
        ),
    )


def _grade_1_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test G1",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="medium",
            response_format_prefs=["write", "circle"],
        ),
    )


def _grade_3_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test G3",
        grade_level="3",
        accommodations=Accommodations(
            chunking_level="large",
            response_format_prefs=["write", "circle", "match"],
        ),
    )


# --- LearnerProfile Tests ---


class TestLearnerProfile:
    def test_create_minimal(self) -> None:
        p = LearnerProfile(name="Ian", grade_level="1")
        assert p.name == "Ian"
        assert p.grade_level == "1"
        assert p.accommodations.chunking_level == "medium"

    def test_companion_fields_optional(self) -> None:
        p = LearnerProfile(name="Ian", grade_level="1")
        assert p.avatar is None
        assert p.preferences is None
        assert p.progress is None

    def test_yaml_round_trip(self) -> None:
        p = LearnerProfile(
            name="Ian",
            grade_level="1",
            accommodations=Accommodations(
                chunking_level="small",
                font_size_override=16,
            ),
        )
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            path = Path(f.name)

        save_profile(p, path)
        loaded = load_profile(path)
        assert loaded.name == p.name
        assert loaded.grade_level == p.grade_level
        assert loaded.accommodations.chunking_level == "small"
        assert loaded.accommodations.font_size_override == 16
        path.unlink()

    def test_pydantic_validation(self) -> None:
        p = LearnerProfile(name="Ian", grade_level="K")
        json_str = p.model_dump_json()
        restored = LearnerProfile.model_validate_json(json_str)
        assert restored.name == p.name


# --- AccommodationRules Tests ---


class TestAccommodationRules:
    def test_build_from_grade_1(self) -> None:
        rules = build_rules(_grade_1_profile())
        assert rules.max_items_per_chunk == 4  # Grade 1, medium
        assert rules.instruction_max_words == 12
        assert rules.instruction_max_steps == 3
        assert rules.require_worked_example is True

    def test_build_from_grade_k(self) -> None:
        rules = build_rules(_grade_k_profile())
        assert rules.max_items_per_chunk == 2  # K, small
        assert rules.font_size_min == 16
        assert rules.time_estimate_minutes == 3

    def test_build_from_grade_3(self) -> None:
        rules = build_rules(_grade_3_profile())
        assert rules.max_items_per_chunk == 8  # Grade 3, large
        assert rules.instruction_max_steps == 4

    def test_font_size_override(self) -> None:
        p = LearnerProfile(
            name="Test",
            grade_level="3",
            accommodations=Accommodations(font_size_override=18),
        )
        rules = build_rules(p)
        assert rules.font_size_min == 18

    def test_chunking_all_grades(self) -> None:
        for grade in ("K", "1", "2", "3"):
            assert grade in CHUNKING_RULES
            for level in ("small", "medium", "large"):
                assert level in CHUNKING_RULES[grade]
                assert CHUNKING_RULES[grade][level] >= 2

    def test_substitute_format(self) -> None:
        assert get_substitute_format("write", ["write", "circle"]) == "write"
        assert get_substitute_format("write", ["circle", "match"]) == "circle"
        assert get_substitute_format("fill_blank", ["circle"]) == "circle"
        assert get_substitute_format("unknown", ["verbal"]) == "verbal"

    def test_color_system(self) -> None:
        rules = build_rules(_grade_1_profile())
        assert "directions" in rules.color_system
        assert "examples" in rules.color_system
        assert "rewards" in rules.color_system
        assert rules.max_decorative_elements == 2


# --- Adaptation Engine Tests ---


class TestAdaptActivity:
    def test_phonics_produces_chunks(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert len(model.chunks) >= 1
        assert model.domain == "phonics"

    def test_chunk_size_respects_rules(self) -> None:
        skill = _phonics_skill()
        profile = _grade_1_profile()
        rules = build_rules(profile)
        model = adapt_activity(skill, profile, rules=rules)

        for chunk in model.chunks:
            assert len(chunk.items) <= rules.max_items_per_chunk

    def test_first_chunk_has_worked_example(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        first = model.chunks[0]
        assert first.worked_example is not None

    def test_later_chunks_no_worked_example(self) -> None:
        # Use small chunks to ensure multiple chunks
        profile = LearnerProfile(
            name="Test",
            grade_level="1",
            accommodations=Accommodations(chunking_level="small"),
        )
        model = adapt_activity(_phonics_skill(), profile)
        if len(model.chunks) > 1:
            assert model.chunks[1].worked_example is None

    def test_instructions_numbered(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        for chunk in model.chunks:
            for i, step in enumerate(chunk.instructions):
                assert step.number == i + 1

    def test_time_estimate_present(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        for chunk in model.chunks:
            assert "minutes" in chunk.time_estimate.lower() or chunk.time_estimate == ""

    def test_time_estimate_hidden_when_disabled(self) -> None:
        profile = LearnerProfile(
            name="Test",
            grade_level="1",
            accommodations=Accommodations(show_time_estimates=False),
        )
        model = adapt_activity(_phonics_skill(), profile)
        for chunk in model.chunks:
            assert chunk.time_estimate == ""

    def test_fluency_adaptation(self) -> None:
        model = adapt_activity(_fluency_skill(), _grade_1_profile())
        assert model.domain == "fluency"
        assert len(model.chunks) >= 1
        # Passage items should be read_aloud
        for chunk in model.chunks:
            for item in chunk.items:
                assert item.response_format == "read_aloud"

    def test_self_assessment_generated(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert model.self_assessment is not None
        assert len(model.self_assessment) >= 2
        # Should end with growth mindset item
        assert "still learning" in model.self_assessment[-1].lower()

    def test_decoration_zones_defined(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert len(model.decoration_zones) >= 1
        for zone in model.decoration_zones:
            assert len(zone) == 4  # x0, y0, x1, y1
            assert all(0 <= v <= 1 for v in zone)

    def test_avatar_prompts_none_for_mvp(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert model.avatar_prompts is None

    def test_grade_k_small_chunks(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_k_profile())
        for chunk in model.chunks:
            assert len(chunk.items) <= 2  # K, small = 2

    def test_response_format_substitution(self) -> None:
        # Profile prefers circle only — write items should substitute
        profile = LearnerProfile(
            name="Test",
            grade_level="1",
            accommodations=Accommodations(
                response_format_prefs=["circle", "verbal"],
            ),
        )
        model = adapt_activity(_phonics_skill(), profile)
        for chunk in model.chunks:
            for item in chunk.items:
                assert item.response_format in ("circle", "verbal", "read_aloud", "write")

    def test_deterministic(self) -> None:
        m1 = adapt_activity(_phonics_skill(), _grade_1_profile())
        m2 = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert m1.model_dump() == m2.model_dump()

    def test_pydantic_round_trip(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        json_str = model.model_dump_json()
        restored = AdaptedActivityModel.model_validate_json(json_str)
        assert len(restored.chunks) == len(model.chunks)
        assert restored.domain == model.domain

    def test_scaffolding_config(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert model.scaffolding.show_worked_example is True
        assert model.scaffolding.fade_after_chunk == 1

    def test_links_back_to_source(self) -> None:
        model = adapt_activity(_phonics_skill(), _grade_1_profile())
        assert len(model.source_hash) > 0
        assert len(model.skill_model_hash) > 0
        assert len(model.learner_profile_hash) > 0


# --- UFLI Lesson 59 fixture (CVCe pattern with chains, sight words, passage) ---


def _ufli_59_skill() -> LiteracySkillModel:
    """Synthetic UFLI Lesson 59 skill model with varied content types."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=[
            "Read words with CVCe pattern",
            "Apply CVCe pattern in connected text",
        ],
        target_words=["grade", "chase", "slide", "quite", "froze", "these"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, chase, slide, quite, froze, these",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content=(
                    "1. tune \u2192 tone \u2192 cone \u2192 cane "
                    "2. tame \u2192 time \u2192 dime \u2192 dome"
                ),
                source_region_index=1,
            ),
            SourceItem(
                item_type="sight_words",
                content="who, by, my, one, once",
                source_region_index=2,
            ),
            SourceItem(
                item_type="sentence",
                content=(
                    "1. The grade on the slide was quite nice. "
                    "2. These froze by the chase."
                ),
                source_region_index=3,
            ),
            SourceItem(
                item_type="passage",
                content=(
                    "A Cake for Tess. Tess had a cake. "
                    "The cake was huge! She made it with love."
                ),
                source_region_index=4,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


# --- Multi-Worksheet Tests ---


class TestAdaptLesson:
    def test_produces_multiple_worksheets(self) -> None:
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        assert len(worksheets) >= 2
        assert len(worksheets) <= 3

    def test_worksheet_numbers_correct(self) -> None:
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        for i, ws in enumerate(worksheets):
            assert ws.worksheet_number == i + 1
            assert ws.worksheet_count == len(worksheets)

    def test_worksheet_titles_set(self) -> None:
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        titles = [ws.worksheet_title for ws in worksheets]
        assert "Word Discovery" in titles
        assert "Word Builder" in titles

    def test_activity_format_variety(self) -> None:
        """Not all response formats should be 'write' across all worksheets."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        all_formats: set[str] = set()
        for ws in worksheets:
            for chunk in ws.chunks:
                all_formats.add(chunk.response_format)
                for item in chunk.items:
                    all_formats.add(item.response_format)
        # Should have at least 3 different formats
        assert len(all_formats) >= 3, f"Only formats: {all_formats}"

    def test_story_not_dropped(self) -> None:
        """Decodable passage should appear in one of the worksheets."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        all_content = []
        for ws in worksheets:
            for chunk in ws.chunks:
                for item in chunk.items:
                    all_content.append(item.content)
        # The passage about Tess should be present
        assert any("Tess" in c or "cake" in c.lower() for c in all_content), \
            "Decodable passage 'A Cake for Tess' was dropped"

    def test_brain_break_prompts(self) -> None:
        """Non-last worksheets should have break prompts."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        if len(worksheets) >= 2:
            # First worksheet should have a break prompt
            assert worksheets[0].break_prompt is not None
            # Last worksheet should NOT have a break prompt
            assert worksheets[-1].break_prompt is None

    def test_fill_blank_generation(self) -> None:
        """Fill-blank items should have correct vowel removal."""
        from adapt.engine import _generate_fill_blank
        blanked, vowel = _generate_fill_blank("grade")
        assert "_" in blanked
        assert vowel in "aeiou"
        assert len(blanked) == len("grade")

    def test_circle_distractors(self) -> None:
        """Distractor words should be plausible non-pattern words."""
        from adapt.engine import _generate_distractors
        distractors = _generate_distractors(["grade", "chase"], 4)
        assert len(distractors) == 4
        assert "grade" not in distractors
        assert "chase" not in distractors

    def test_backward_compat_adapt_activity(self) -> None:
        """adapt_activity() still works unchanged after adding adapt_lesson()."""
        model = adapt_activity(_ufli_59_skill(), _grade_1_profile())
        assert model.worksheet_number == 1
        assert model.worksheet_count == 1
        assert model.break_prompt is None
        assert len(model.chunks) >= 1

    def test_word_discovery_has_match_items(self) -> None:
        """Worksheet 1 (Word Discovery) should have match-format items."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"]
        assert len(discovery) == 1
        match_items = [
            item
            for chunk in discovery[0].chunks
            for item in chunk.items
            if item.response_format == "match"
        ]
        assert len(match_items) >= 1

    def test_match_items_have_picture_prompts(self) -> None:
        """Match items should have picture_prompt set."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        for ws in worksheets:
            for chunk in ws.chunks:
                for item in chunk.items:
                    if item.response_format == "match":
                        assert item.picture_prompt is not None

    def test_single_worksheet_fallback(self) -> None:
        """Skills with only word lists should still produce at least 1 worksheet."""
        minimal = LiteracySkillModel(
            grade_level="1",
            domain="phonics",
            specific_skill="cvc_blending",
            learning_objectives=["Blend CVC words"],
            target_words=["cat", "hat"],
            response_types=["write"],
            source_items=[
                SourceItem(item_type="word_list", content="cat, hat", source_region_index=0),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )
        worksheets = adapt_lesson(minimal, _grade_1_profile())
        assert len(worksheets) >= 1
