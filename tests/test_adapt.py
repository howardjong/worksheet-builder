"""Tests for adapt/engine.py, adapt/rules.py, adapt/schema.py, and companion/schema.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from adapt.engine import adapt_activity, adapt_lesson
from adapt.rules import (
    CHUNKING_RULES,
    INTENSITY_VISUALS,
    build_rules,
    get_substitute_format,
    llm_adapt_enabled,
)
from adapt.schema import AdaptedActivityModel
from companion.schema import (
    Accommodations,
    LearnerProfile,
    Preferences,
    load_profile,
    save_profile,
)
from skill.schema import LiteracySkillModel, SourceItem
from validate.content_coverage import validate_content_coverage_for_package

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
            SourceItem(item_type="sight_words", content="go*, no*, so*", source_region_index=7),
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


def _grade_1_small_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test G1 Small",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="small",
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

    def test_intensity_visuals_table_medium_matches_legacy_hardcodes(self) -> None:
        # medium must be bit-identical to the pre-dial hardcodes.
        medium = INTENSITY_VISUALS["medium"]
        assert medium.max_decorative_elements == 2
        assert medium.max_colors == 4
        assert medium.art_scale == 1.0
        assert medium.game_chrome == "basic"
        low = INTENSITY_VISUALS["low"]
        assert (low.max_decorative_elements, low.max_colors) == (1, 3)
        assert low.art_scale == 0.75
        assert low.game_chrome == "none"
        high = INTENSITY_VISUALS["high"]
        assert (high.max_decorative_elements, high.max_colors) == (6, 6)
        assert high.art_scale == 1.3
        assert high.game_chrome == "full"

    def test_visual_intensity_dial_unset_is_medium(self) -> None:
        # No preferences → medium == exact legacy behavior.
        rules = build_rules(_grade_1_profile())
        assert rules.visual_intensity == "medium"
        assert rules.max_decorative_elements == 2

    def test_visual_intensity_high_dial(self) -> None:
        profile = LearnerProfile(
            name="High dial",
            grade_level="1",
            preferences=Preferences(visual_intensity="high"),
        )
        rules = build_rules(profile)
        assert rules.visual_intensity == "high"
        assert rules.max_decorative_elements == 6

    def test_visual_intensity_low_dial(self) -> None:
        profile = LearnerProfile(
            name="Low dial",
            grade_level="1",
            preferences=Preferences(visual_intensity="low"),
        )
        rules = build_rules(profile)
        assert rules.visual_intensity == "low"
        assert rules.max_decorative_elements == 1


class TestLlmAdaptEnabled:
    """WORKSHEET_LLM_ADAPT gate: '0' is a real opt-out (documented D31 semantics)."""

    def test_unset_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
        assert llm_adapt_enabled() is False

    def test_empty_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "")
        assert llm_adapt_enabled() is False

    def test_zero_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Before the shared helper, "0" was truthy and silently ENABLED the LLM
        # paths — the opposite of the documented opt-out.
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
        assert llm_adapt_enabled() is False

    def test_one_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        assert llm_adapt_enabled() is True


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
                content=("1. The grade on the slide was quite nice. 2. These froze by the chase."),
                source_region_index=3,
            ),
            SourceItem(
                item_type="passage",
                content=(
                    "A Cake for Tess. Tess had a cake. The cake was huge! She made it with love."
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
        # Section cap enforcement may split worksheets beyond the base 3
        assert len(worksheets) <= 6

    def test_worksheet_numbers_correct(self) -> None:
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        for i, ws in enumerate(worksheets):
            assert ws.worksheet_number == i + 1
            assert ws.worksheet_count == len(worksheets)

    def test_worksheet_titles_set(self) -> None:
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        titles = [ws.worksheet_title for ws in worksheets]
        # UFLI word work with chains: reordered to Word Work / Word Practice
        # Section cap enforcement may append "(Part N)" to split worksheets
        assert any(t and t.startswith("Word Work") for t in titles)
        assert any(t and t.startswith("Word Practice") for t in titles)

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
        assert any("Tess" in c or "cake" in c.lower() for c in all_content), (
            "Decodable passage 'A Cake for Tess' was dropped"
        )

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
        """Word practice worksheet should have match-format items."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        # UFLI word work with chains: Discovery is renamed to Word Practice
        # Section cap enforcement may split into multiple parts
        discovery = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert len(discovery) >= 1
        match_items = [
            item
            for ws in discovery
            for chunk in ws.chunks
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

    def test_warmup_chunk_present_grade_1(self) -> None:
        """Grade 1 profiles should have sound_box warmup chunk in Word Practice."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        # UFLI word work with chains: Discovery is renamed to Word Practice
        # Section cap enforcement may split into multiple parts
        discovery = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert len(discovery) >= 1
        # Find chunk with sound_box format (may be in any of the parts)
        sound_box_chunks = [
            chunk for ws in discovery for chunk in ws.chunks if chunk.response_format == "sound_box"
        ]
        assert len(sound_box_chunks) >= 1

    def test_warmup_chunk_absent_grade_3(self) -> None:
        """Grade 3 skills should NOT have sound_box warmup chunk."""
        # Create a grade 3 skill (grade level determines warmup presence)
        grade_3_skill = LiteracySkillModel(
            grade_level="3",
            domain="phonics",
            specific_skill="cvce_pattern",
            learning_objectives=["Read words with CVCe pattern"],
            target_words=["grade", "chase", "slide"],
            response_types=["write", "read_aloud"],
            source_items=[
                SourceItem(
                    item_type="word_list",
                    content="grade, chase, slide",
                    source_region_index=0,
                ),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )
        worksheets = adapt_lesson(grade_3_skill, _grade_1_profile())
        discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"]
        assert len(discovery) == 1
        # Should have NO sound_box chunks
        sound_box_chunks = [
            chunk for chunk in discovery[0].chunks if chunk.response_format == "sound_box"
        ]
        assert len(sound_box_chunks) == 0

    def test_roll_and_read_chunk_present(self) -> None:
        """Skills with roll_and_read source items should produce appropriate chunks."""
        skill = LiteracySkillModel(
            grade_level="1",
            domain="phonics",
            specific_skill="cvc_blending",
            learning_objectives=["Read CVC words with fluency"],
            target_words=["cat", "hat", "mat"],
            response_types=["write", "read_aloud"],
            source_items=[
                SourceItem(item_type="word_list", content="cat, hat, mat", source_region_index=0),
                SourceItem(
                    item_type="roll_and_read",
                    content="sunny\nfunny\nbunny\nbuddy\nhappy",
                    source_region_index=5,
                ),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )
        worksheets = adapt_lesson(skill, _grade_1_profile())
        builder = [ws for ws in worksheets if ws.worksheet_title == "Word Builder"]
        assert len(builder) == 1
        # Find chunks with roll_and_read metadata or read_aloud micro_goal
        roll_chunks = [
            chunk
            for chunk in builder[0].chunks
            if any(item.metadata.get("display") == "roll_and_read" for item in chunk.items)
            or "Read" in chunk.micro_goal
        ]
        assert len(roll_chunks) >= 1

    def test_lesson_total_time_under_20_minutes(self) -> None:
        """Total time across all worksheets should not exceed 20 minutes."""
        import re

        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        total_minutes = 0
        for ws in worksheets:
            for chunk in ws.chunks:
                if chunk.time_estimate:
                    m = re.search(r"(\d+)", chunk.time_estimate)
                    if m:
                        total_minutes += int(m.group(1))
        assert total_minutes <= 20

    def test_respects_small_chunk_cap_for_grade_1_lesson(self) -> None:
        """All generated practice chunks should fit the learner's small chunk cap."""
        profile = _grade_1_small_profile()
        rules = build_rules(profile)
        worksheets = adapt_lesson(_ufli_59_skill(), profile, rules=rules)

        oversized = [
            (ws.worksheet_title, chunk.micro_goal, len(chunk.items))
            for ws in worksheets
            for chunk in ws.chunks
            if len(chunk.items) > rules.max_items_per_chunk
        ]

        assert oversized == []

        oversized_options = [
            (ws.worksheet_title, chunk.micro_goal, item.content, len(item.options))
            for ws in worksheets
            for chunk in ws.chunks
            for item in chunk.items
            if item.response_format in {"match", "fill_blank", "circle"}
            and item.options
            and len(item.options) > rules.max_items_per_chunk
        ]

        assert oversized_options == []

    def test_k_small_sound_box_warmup_respects_chunk_cap(self) -> None:
        """K small profiles should not get a 3-item sound-box warmup."""
        profile = _grade_k_profile()
        rules = build_rules(profile)
        skill = LiteracySkillModel(
            grade_level="K",
            domain="phonics",
            specific_skill="cvc_blending",
            learning_objectives=["Blend CVC words"],
            target_words=["cat", "hat", "mat", "sat"],
            response_types=["write"],
            source_items=[
                SourceItem(
                    item_type="word_list",
                    content="cat, hat, mat, sat",
                    source_region_index=0,
                ),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )

        worksheets = adapt_lesson(skill, profile, rules=rules)
        sound_box_chunks = [
            chunk
            for ws in worksheets
            for chunk in ws.chunks
            if chunk.response_format == "sound_box"
        ]

        assert sound_box_chunks
        assert all(len(chunk.items) <= rules.max_items_per_chunk for chunk in sound_box_chunks)

    def test_word_list_only_small_chunks_preserve_package_coverage(self) -> None:
        """Splitting by cap should not drop later target words from the package."""
        profile = _grade_1_small_profile()
        rules = build_rules(profile)
        target_words = ["grade", "chase", "slide", "quite", "froze", "these"]
        skill = LiteracySkillModel(
            grade_level="1",
            domain="phonics",
            specific_skill="cvce_pattern",
            learning_objectives=["Read CVCe words"],
            target_words=target_words,
            response_types=["write", "circle", "match"],
            source_items=[
                SourceItem(
                    item_type="word_list",
                    content=", ".join(target_words),
                    source_region_index=0,
                ),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )

        worksheets = adapt_lesson(skill, profile, rules=rules)

        oversized_chunks = [
            (ws.worksheet_title, chunk.micro_goal, len(chunk.items))
            for ws in worksheets
            for chunk in ws.chunks
            if len(chunk.items) > rules.max_items_per_chunk
        ]
        assert oversized_chunks == []

        oversized_options = [
            (ws.worksheet_title, chunk.micro_goal, item.content, len(item.options))
            for ws in worksheets
            for chunk in ws.chunks
            for item in chunk.items
            if item.response_format in {"match", "fill_blank", "circle"}
            and item.options
            and len(item.options) > rules.max_items_per_chunk
        ]
        assert oversized_options == []

        coverage = validate_content_coverage_for_package(skill, worksheets)
        assert coverage.passed

    def test_word_list_with_chain_small_chunks_preserve_package_coverage(self) -> None:
        """Word chains should not prevent later word-list targets from being visible."""
        profile = _grade_1_small_profile()
        rules = build_rules(profile)
        target_words = ["grade", "chase", "slide", "quite", "froze", "these"]
        skill = LiteracySkillModel(
            grade_level="1",
            domain="phonics",
            specific_skill="cvce_pattern",
            learning_objectives=["Read CVCe words", "Build words by changing letters"],
            target_words=target_words,
            response_types=["write", "circle", "match"],
            source_items=[
                SourceItem(
                    item_type="word_list",
                    content=", ".join(target_words),
                    source_region_index=0,
                ),
                SourceItem(
                    item_type="word_chain",
                    content="1. tune → tone → cone → cane",
                    source_region_index=1,
                ),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )

        worksheets = adapt_lesson(skill, profile, rules=rules)

        oversized_chunks = [
            (ws.worksheet_title, chunk.micro_goal, len(chunk.items))
            for ws in worksheets
            for chunk in ws.chunks
            if len(chunk.items) > rules.max_items_per_chunk
        ]
        assert oversized_chunks == []

        oversized_options = [
            (ws.worksheet_title, chunk.micro_goal, item.content, len(item.options))
            for ws in worksheets
            for chunk in ws.chunks
            for item in chunk.items
            if item.response_format in {"match", "fill_blank", "circle"}
            and item.options
            and len(item.options) > rules.max_items_per_chunk
        ]
        assert oversized_options == []

        coverage = validate_content_coverage_for_package(skill, worksheets)
        assert coverage.passed

    def test_roll_and_read_instructions_do_not_use_speed_pressure(self) -> None:
        """Roll and Read should cue smooth repeated reading, not faster reading."""
        skill = LiteracySkillModel(
            grade_level="1",
            domain="phonics",
            specific_skill="cvc_blending",
            learning_objectives=["Read CVC words with fluency"],
            target_words=["cat", "hat", "mat"],
            response_types=["write", "read_aloud"],
            source_items=[
                SourceItem(item_type="word_list", content="cat, hat, mat", source_region_index=0),
                SourceItem(
                    item_type="roll_and_read",
                    content="sunny\nfunny\nbunny\nbuddy\nhappy",
                    source_region_index=5,
                ),
            ],
            extraction_confidence=0.95,
            template_type="ufli_word_work",
        )
        worksheets = adapt_lesson(skill, _grade_1_profile())
        roll_steps = [
            step.text
            for ws in worksheets
            for chunk in ws.chunks
            if any(item.metadata.get("display") == "roll_and_read" for item in chunk.items)
            for step in chunk.instructions
        ]

        assert roll_steps
        assert all("faster" not in step.lower() for step in roll_steps)


def test_rules_include_grade_scaled_section_cap() -> None:
    from adapt.rules import MAX_SECTIONS_PER_WORKSHEET, build_rules
    from companion.schema import Accommodations, LearnerProfile

    assert MAX_SECTIONS_PER_WORKSHEET == {"K": 2, "1": 3, "2": 4, "3": 4}
    for grade, cap in MAX_SECTIONS_PER_WORKSHEET.items():
        profile = LearnerProfile(name="t", grade_level=grade, accommodations=Accommodations())
        assert build_rules(profile).max_sections_per_worksheet == cap


class TestLessonPackageCapWiring:
    """adapt_lesson resolves WORKSHEET_MAX_WORKSHEETS once, up front."""

    def test_auto_mode_caps_dense_lesson_and_writes_budget_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORKSHEET_MAX_WORKSHEETS", "auto")
        monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)  # deterministic path
        monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)

        alpha_words = [f"{c1}{c2}ay" for c1 in "bcdfghjk" for c2 in "bcdfg"]
        many_words = ", ".join(alpha_words)
        skill = LiteracySkillModel(
            grade_level="2",
            domain="phonics",
            specific_skill="vowel_teams",
            learning_objectives=["Read ay words"],
            target_words=alpha_words,
            response_types=["write"],
            source_items=[
                SourceItem(item_type="word_list", content=many_words, source_region_index=0),
                SourceItem(
                    item_type="sentence",
                    content="We play all day. May will stay in the hay. Ray has gray clay.",
                    source_region_index=1,
                ),
            ],
            extraction_confidence=1.0,
            template_type="ufli_word_work",
        )
        profile = LearnerProfile(name="Test", grade_level="2")

        worksheets = adapt_lesson(skill, profile, artifacts_dir=str(tmp_path))

        assert 1 <= len(worksheets) <= 3  # grade-2 attention ceiling
        assert worksheets[-1].worksheet_count == len(worksheets)
        assert (tmp_path / "workload_budget.json").exists()

    def test_unset_env_means_no_package_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WORKSHEET_MAX_WORKSHEETS", raising=False)
        monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
        monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)

        alpha_words = [f"{c1}{c2}ay" for c1 in "bcdfghjklm" for c2 in "bcdfghjk"]
        many_words = ", ".join(alpha_words)
        skill = LiteracySkillModel(
            grade_level="2",
            domain="phonics",
            specific_skill="vowel_teams",
            learning_objectives=["Read ay words"],
            target_words=alpha_words,
            response_types=["write"],
            source_items=[
                SourceItem(item_type="word_list", content=many_words, source_region_index=0),
                SourceItem(
                    item_type="sentence",
                    content="We play all day. May will stay in the hay. Ray has gray clay.",
                    source_region_index=1,
                ),
            ],
            extraction_confidence=1.0,
            template_type="ufli_word_work",
        )
        profile = LearnerProfile(name="Test", grade_level="2")

        worksheets = adapt_lesson(skill, profile)
        # Photo-path behavior preserved: dense content splits freely past 3.
        assert len(worksheets) > 3
