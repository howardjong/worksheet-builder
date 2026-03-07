"""Tests for skill/taxonomy.py, skill/extractor.py, and skill/schema.py."""

from __future__ import annotations

from extract.schema import SourceRegion, SourceWorksheetModel
from skill.extractor import extract_skill
from skill.schema import LiteracySkillModel
from skill.taxonomy import (
    LITERACY_DOMAINS,
    all_domains,
    get_domain_grade_range,
    get_domain_skills,
    is_valid_skill,
    match_phonics_pattern,
)

PIPELINE_VERSION = "0.1.0"


# --- Fixtures: synthetic SourceWorksheetModels ---


def _word_work_source() -> SourceWorksheetModel:
    """Synthetic UFLI Word Work source model (lesson 43: -all, -oll, -ull)."""
    return SourceWorksheetModel(
        source_image_hash="abc123",
        pipeline_version=PIPELINE_VERSION,
        template_type="ufli_word_work",
        regions=[
            SourceRegion(
                type="title",
                content="Home Practice Lesson 43",
                bbox=(50, 10, 400, 60),
                confidence=0.98,
                metadata={},
            ),
            SourceRegion(
                type="concept_label",
                content="New Concept and Sample Words: -all, -oll, -ull",
                bbox=(50, 150, 500, 200),
                confidence=0.95,
                metadata={},
            ),
            SourceRegion(
                type="sample_words",
                content="tall, call, wall",
                bbox=(100, 210, 400, 250),
                confidence=0.93,
                metadata={},
            ),
            SourceRegion(
                type="sample_words",
                content="doll, roll, poll",
                bbox=(100, 260, 400, 300),
                confidence=0.94,
                metadata={},
            ),
            SourceRegion(
                type="word_chain",
                content="1. all → fall → mall → small",
                bbox=(550, 210, 950, 250),
                confidence=0.92,
                metadata={},
            ),
            SourceRegion(
                type="word_chain",
                content="2. call → hall → tall → stall",
                bbox=(550, 260, 960, 300),
                confidence=0.91,
                metadata={},
            ),
            SourceRegion(
                type="chain_script",
                content="1. Write the word all. [spelling]",
                bbox=(550, 410, 950, 450),
                confidence=0.94,
                metadata={},
            ),
            SourceRegion(
                type="sight_word_list",
                content="go*, no*, so*",
                bbox=(100, 550, 350, 580),
                confidence=0.90,
                metadata={},
            ),
            SourceRegion(
                type="practice_sentences",
                content="1. The bin is so full.",
                bbox=(550, 550, 900, 580),
                confidence=0.95,
                metadata={},
            ),
        ],
        raw_text="Home Practice Lesson 43\nNew Concept and Sample Words: -all, -oll, -ull\n"
        "tall, call, wall\ndoll, roll, poll\n"
        "1. all → fall → mall → small\n2. call → hall → tall → stall\n"
        "1. Write the word all. [spelling]\ngo*, no*, so*\n"
        "1. The bin is so full.",
        ocr_engine="paddleocr",
        low_confidence_flags=[],
    )


def _decodable_story_source() -> SourceWorksheetModel:
    """Synthetic UFLI Decodable Story source model (lesson 58: u_e pattern)."""
    return SourceWorksheetModel(
        source_image_hash="def456",
        pipeline_version=PIPELINE_VERSION,
        template_type="ufli_decodable_story",
        regions=[
            SourceRegion(
                type="title",
                content="Lesson 58",
                bbox=(50, 10, 300, 50),
                confidence=0.97,
                metadata={},
            ),
            SourceRegion(
                type="story_title",
                content="June's Flute",
                bbox=(200, 100, 600, 150),
                confidence=0.96,
                metadata={},
            ),
            SourceRegion(
                type="decodable_passage",
                content=(
                    "June has a flute. June likes to use the flute to make tunes. "
                    "There is one tune June likes best. She likes the song Sand Dunes."
                ),
                bbox=(50, 300, 900, 600),
                confidence=0.94,
                metadata={},
            ),
            SourceRegion(
                type="decodable_passage",
                content=(
                    "Once, June and Luke made tunes at lunch for their pals. "
                    "The last song they did was Sand Dunes. June was on the flute "
                    "and Luke sang. They did a fine job!"
                ),
                bbox=(50, 620, 900, 850),
                confidence=0.93,
                metadata={},
            ),
        ],
        raw_text="Lesson 58\nJune's Flute\n"
        "June has a flute. June likes to use the flute to make tunes.\n"
        "Once, June and Luke made tunes at lunch.",
        ocr_engine="paddleocr",
        low_confidence_flags=[],
    )


def _unknown_source() -> SourceWorksheetModel:
    """Synthetic unknown layout source model."""
    return SourceWorksheetModel(
        source_image_hash="ghi789",
        pipeline_version=PIPELINE_VERSION,
        template_type="unknown",
        regions=[
            SourceRegion(
                type="title",
                content="Math Quiz",
                bbox=(100, 10, 400, 60),
                confidence=0.98,
                metadata={},
            ),
            SourceRegion(
                type="question",
                content="1. 2 + 3 = ___",
                bbox=(50, 100, 400, 140),
                confidence=0.95,
                metadata={},
            ),
            SourceRegion(
                type="question",
                content="2. 5 + 1 = ___",
                bbox=(50, 160, 400, 200),
                confidence=0.94,
                metadata={},
            ),
        ],
        raw_text="Math Quiz\n1. 2 + 3 = ___\n2. 5 + 1 = ___",
        ocr_engine="paddleocr",
        low_confidence_flags=[],
    )


# --- Taxonomy Tests ---


class TestTaxonomy:
    def test_six_domains(self) -> None:
        domains = all_domains()
        assert len(domains) == 6
        assert set(domains) == {
            "phonemic_awareness",
            "phonics",
            "fluency",
            "vocabulary",
            "comprehension",
            "writing",
        }

    def test_each_domain_has_skills(self) -> None:
        for domain in all_domains():
            skills = get_domain_skills(domain)
            assert len(skills) >= 1, f"{domain} has no skills"

    def test_each_domain_has_grade_range(self) -> None:
        for domain in all_domains():
            grades = get_domain_grade_range(domain)
            assert len(grades) >= 1, f"{domain} has no grade range"
            assert all(g in ("K", "1", "2", "3") for g in grades)

    def test_is_valid_skill(self) -> None:
        assert is_valid_skill("phonics", "cvc_blending")
        assert is_valid_skill("phonics", "cvce")
        assert not is_valid_skill("phonics", "nonexistent_skill")
        assert not is_valid_skill("fake_domain", "cvc_blending")

    def test_phonics_has_expected_skills(self) -> None:
        skills = get_domain_skills("phonics")
        for expected in ["cvc_blending", "cvce", "digraphs", "blends", "vowel_teams"]:
            assert expected in skills

    def test_unknown_domain_returns_empty(self) -> None:
        assert get_domain_skills("nonexistent") == []
        assert get_domain_grade_range("nonexistent") == []

    def test_phonics_pattern_matching(self) -> None:
        assert match_phonics_pattern("-all, -oll, -ull") == "cvc_blending"
        assert match_phonics_pattern("a_e pattern") == "cvce"
        assert match_phonics_pattern("u_e words") == "cvce"
        assert match_phonics_pattern("digraphs sh, ch") == "digraphs"
        assert match_phonics_pattern("just some random text") is None

    def test_literacy_domains_structure(self) -> None:
        for domain, info in LITERACY_DOMAINS.items():
            assert "skills" in info
            assert "grade_range" in info
            assert isinstance(info["skills"], list)
            assert isinstance(info["grade_range"], list)


# --- Skill Extraction Tests ---


class TestExtractWordWork:
    def test_domain_is_phonics(self) -> None:
        model = extract_skill(_word_work_source())
        assert model.domain == "phonics"

    def test_specific_skill_from_concept_label(self) -> None:
        model = extract_skill(_word_work_source())
        # -all pattern should map to cvc_blending
        assert model.specific_skill == "cvc_blending"

    def test_target_words_extracted(self) -> None:
        model = extract_skill(_word_work_source())
        assert len(model.target_words) > 0
        # Should include sample words
        assert "tall" in model.target_words
        assert "call" in model.target_words
        # Should include chain words
        assert "fall" in model.target_words
        assert "mall" in model.target_words

    def test_sight_words_extracted(self) -> None:
        model = extract_skill(_word_work_source())
        assert "go" in model.target_words
        assert "no" in model.target_words

    def test_grade_level_from_lesson(self) -> None:
        model = extract_skill(_word_work_source())
        # Lesson 43 → Grade 1
        assert model.grade_level == "1"

    def test_source_items_populated(self) -> None:
        model = extract_skill(_word_work_source())
        assert len(model.source_items) > 0
        item_types = {item.item_type for item in model.source_items}
        assert "word_list" in item_types or "word_chain" in item_types

    def test_learning_objectives(self) -> None:
        model = extract_skill(_word_work_source())
        assert len(model.learning_objectives) >= 1
        # Should mention the concept
        objectives_text = " ".join(model.learning_objectives).lower()
        assert "all" in objectives_text or "pattern" in objectives_text

    def test_response_types(self) -> None:
        model = extract_skill(_word_work_source())
        assert "write" in model.response_types
        assert "read_aloud" in model.response_types

    def test_extraction_confidence(self) -> None:
        model = extract_skill(_word_work_source())
        assert 0.0 < model.extraction_confidence <= 1.0

    def test_template_type_passed_through(self) -> None:
        model = extract_skill(_word_work_source())
        assert model.template_type == "ufli_word_work"


class TestExtractDecodableStory:
    def test_domain_is_fluency(self) -> None:
        model = extract_skill(_decodable_story_source())
        assert model.domain == "fluency"

    def test_specific_skill_is_decodable(self) -> None:
        model = extract_skill(_decodable_story_source())
        assert model.specific_skill.startswith("decodable_text")

    def test_target_words_from_passage(self) -> None:
        model = extract_skill(_decodable_story_source())
        assert len(model.target_words) > 0
        # Should include content words from the passage
        assert "june" in model.target_words
        assert "flute" in model.target_words

    def test_cvce_pattern_detected(self) -> None:
        model = extract_skill(_decodable_story_source())
        # "flute", "June", "tune", "dune", "Luke" → CVCe pattern
        # The passage has multiple u_e words
        assert "cvce" in model.specific_skill or "decodable_text" in model.specific_skill

    def test_grade_level_from_lesson(self) -> None:
        model = extract_skill(_decodable_story_source())
        # Lesson 58 → Grade 1
        assert model.grade_level == "1"

    def test_response_types(self) -> None:
        model = extract_skill(_decodable_story_source())
        assert "read_aloud" in model.response_types

    def test_source_items_include_passages(self) -> None:
        model = extract_skill(_decodable_story_source())
        passage_items = [i for i in model.source_items if i.item_type == "passage"]
        assert len(passage_items) >= 1


class TestExtractGeneric:
    def test_unknown_template(self) -> None:
        model = extract_skill(_unknown_source())
        assert model.template_type == "unknown"

    def test_low_confidence(self) -> None:
        model = extract_skill(_unknown_source())
        # Generic extraction should have lower confidence
        assert model.extraction_confidence < 0.9

    def test_still_produces_valid_model(self) -> None:
        model = extract_skill(_unknown_source())
        assert model.domain in (
            "phonics",
            "phonemic_awareness",
            "fluency",
            "vocabulary",
            "comprehension",
            "writing",
        )
        assert model.grade_level in ("K", "1", "2", "3")


# --- Schema Validation Tests ---


class TestSkillSchema:
    def test_pydantic_round_trip(self) -> None:
        model = extract_skill(_word_work_source())
        json_str = model.model_dump_json()
        restored = LiteracySkillModel.model_validate_json(json_str)
        assert restored.domain == model.domain
        assert restored.specific_skill == model.specific_skill
        assert len(restored.target_words) == len(model.target_words)
        assert len(restored.source_items) == len(model.source_items)

    def test_deterministic(self) -> None:
        m1 = extract_skill(_word_work_source())
        m2 = extract_skill(_word_work_source())
        assert m1.model_dump() == m2.model_dump()

    def test_decodable_round_trip(self) -> None:
        model = extract_skill(_decodable_story_source())
        json_str = model.model_dump_json()
        restored = LiteracySkillModel.model_validate_json(json_str)
        assert restored.domain == model.domain
        assert restored.template_type == model.template_type
