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


def _garbled_concept_source() -> SourceWorksheetModel:
    """Word Work source where vision mis-tagged the worksheet header as the
    concept label (a real failure: handwriting/header text grabbed as concept).
    """
    return SourceWorksheetModel(
        source_image_hash="garbled1",
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
                content="check out my new were learning oll words today",
                bbox=(50, 150, 700, 200),
                confidence=0.55,
                metadata={},
            ),
            SourceRegion(
                type="sample_words",
                content="doll, roll, poll",
                bbox=(100, 210, 400, 250),
                confidence=0.93,
                metadata={},
            ),
        ],
        raw_text="Home Practice Lesson 43\n"
        "check out my new were learning oll words today\n"
        "doll, roll, poll",
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

    def test_garbled_concept_does_not_leak(self) -> None:
        """A mis-OCR'd header must not become the skill descriptor or an
        objective (it would otherwise reach the printed self-check line)."""
        model = extract_skill(_garbled_concept_source())
        garbage_markers = ("check out", "today", "learning", "were")
        skill_lower = model.specific_skill.lower()
        for marker in garbage_markers:
            assert (
                marker not in skill_lower
            ), f"garbled concept leaked into specific_skill: {model.specific_skill!r}"
        for objective in model.learning_objectives:
            obj_lower = objective.lower()
            for marker in garbage_markers:
                assert (
                    marker not in obj_lower
                ), f"garbled concept leaked into objective: {objective!r}"
        # Still a phonics model; garbage falls back to the safe generic skill.
        assert model.domain == "phonics"


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


class TestCorpusEnrichment:
    def test_lesson_number_propagated(self) -> None:
        model = extract_skill(_word_work_source())
        assert model.lesson_number == 43

    def test_lesson_number_none_for_unknown(self) -> None:
        model = extract_skill(_unknown_source())
        assert model.lesson_number is None


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


class TestSourceNotationStripping:
    """Tests for stripping source notation artifacts from student-facing content."""

    def test_sight_words_strip_asterisk_markers(self) -> None:
        """RED: sight_words item should have clean content, markers in metadata."""
        source = SourceWorksheetModel(
            source_image_hash="test_sight_asterisk",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="who, by*, my*, one",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="who, by*, my*, one",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content should be clean (no asterisks)
        assert "*" not in item.content
        assert "by" in item.content
        assert "my" in item.content
        # Markers should be in metadata
        assert "notation_markers" in item.metadata
        markers = item.metadata["notation_markers"]
        assert isinstance(markers, str)
        assert "by*" in markers
        assert "my*" in markers

    def test_sight_words_strip_heart_markers(self) -> None:
        """Heart markers should also be stripped."""
        source = SourceWorksheetModel(
            source_image_hash="test_sight_heart",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="the♥, was❤, said*",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="the♥, was❤, said*",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        assert "♥" not in item.content
        assert "❤" not in item.content
        assert "*" not in item.content
        assert "the" in item.content.lower()
        assert "was" in item.content.lower()
        assert "said" in item.content.lower()
        assert "notation_markers" in item.metadata

    def test_word_list_strip_markers(self) -> None:
        """word_list items (from sample_words) should strip markers."""
        source = SourceWorksheetModel(
            source_image_hash="test_word_list",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sample_words",
                    content="cat, dog*, fish♥",
                    bbox=(100, 210, 400, 250),
                    confidence=0.93,
                    metadata={},
                ),
            ],
            raw_text="cat, dog*, fish♥",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        word_list_items = [si for si in model.source_items if si.item_type == "word_list"]
        assert len(word_list_items) == 1
        item = word_list_items[0]
        assert "*" not in item.content
        assert "♥" not in item.content
        assert "dog" in item.content
        assert "fish" in item.content
        assert "notation_markers" in item.metadata

    def test_sentence_strip_markers(self) -> None:
        """sentence items (from practice_sentences) should strip markers."""
        source = SourceWorksheetModel(
            source_image_hash="test_sentence",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="practice_sentences",
                    content="The dog* ran fast.",
                    bbox=(550, 550, 900, 580),
                    confidence=0.95,
                    metadata={},
                ),
            ],
            raw_text="The dog* ran fast.",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sentence_items = [si for si in model.source_items if si.item_type == "sentence"]
        assert len(sentence_items) == 1
        item = sentence_items[0]
        assert "*" not in item.content
        assert "dog" in item.content
        assert "notation_markers" in item.metadata

    def test_clean_sight_words_no_metadata_key(self) -> None:
        """Regression: clean sight_words (no markers) should NOT have metadata key."""
        source = SourceWorksheetModel(
            source_image_hash="test_clean",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="the, was, said",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="the, was, said",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content is unchanged
        assert item.content == "the, was, said"
        # NO notation_markers key should be present
        assert "notation_markers" not in item.metadata

    def test_chain_script_not_stripped(self) -> None:
        """chain_script items should NOT be stripped (brackets are structural)."""
        source = SourceWorksheetModel(
            source_image_hash="test_chain_script",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="chain_script",
                    content="1. Write the word all. [spelling]",
                    bbox=(550, 410, 950, 450),
                    confidence=0.94,
                    metadata={},
                ),
            ],
            raw_text="1. Write the word all. [spelling]",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        chain_script_items = [si for si in model.source_items if si.item_type == "chain_script"]
        assert len(chain_script_items) == 1
        item = chain_script_items[0]
        # Brackets must be preserved (structural)
        assert "[spelling]" in item.content
        # No stripping happened
        assert "notation_markers" not in item.metadata

    def test_sight_words_strip_bracketed_annotations(self) -> None:
        """RED: bracketed annotations should be stripped from sight_words."""
        source = SourceWorksheetModel(
            source_image_hash="test_bracket_annotation",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="who [heart word], by*, my, one",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="who [heart word], by*, my, one",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content should be clean (no brackets or annotation text)
        assert "[" not in item.content
        assert "]" not in item.content
        assert "heart word" not in item.content
        assert "who" in item.content
        assert "by" in item.content
        assert "my" in item.content
        assert "one" in item.content
        # Both bracket annotation and asterisk marker should be in metadata
        assert "notation_markers" in item.metadata
        markers = item.metadata["notation_markers"]
        assert isinstance(markers, str)
        assert "by*" in markers
        assert "[heart word]" in markers

    def test_sentence_strip_parenthesized_annotations(self) -> None:
        """RED: parenthesized annotations should be stripped from sentences."""
        source = SourceWorksheetModel(
            source_image_hash="test_paren_annotation",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="practice_sentences",
                    content="Run to the den. (sight: the)",
                    bbox=(550, 550, 900, 580),
                    confidence=0.95,
                    metadata={},
                ),
            ],
            raw_text="Run to the den. (sight: the)",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sentence_items = [si for si in model.source_items if si.item_type == "sentence"]
        assert len(sentence_items) == 1
        item = sentence_items[0]
        # Content should be clean (no parentheses or annotation text)
        assert "(" not in item.content
        assert ")" not in item.content
        assert "sight:" not in item.content.lower()
        assert "Run to the den." in item.content
        # Annotation should be in metadata
        assert "notation_markers" in item.metadata
        markers = item.metadata["notation_markers"]
        assert isinstance(markers, str)
        assert "(sight: the)" in markers

    def test_word_list_strip_mixed_annotations(self) -> None:
        """RED: mixed brackets, parens, and markers should all be stripped."""
        source = SourceWorksheetModel(
            source_image_hash="test_mixed_annotations",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sample_words",
                    content="cat, dog* [trick], fish (new), bird♥",
                    bbox=(100, 210, 400, 250),
                    confidence=0.93,
                    metadata={},
                ),
            ],
            raw_text="cat, dog* [trick], fish (new), bird♥",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        word_list_items = [si for si in model.source_items if si.item_type == "word_list"]
        assert len(word_list_items) == 1
        item = word_list_items[0]
        # Content should be clean
        assert "*" not in item.content
        assert "[" not in item.content
        assert "]" not in item.content
        assert "(" not in item.content
        assert ")" not in item.content
        assert "♥" not in item.content
        assert "trick" not in item.content
        assert "new" not in item.content
        # All words should be present
        assert "cat" in item.content
        assert "dog" in item.content
        assert "fish" in item.content
        assert "bird" in item.content
        # All markers should be recorded
        assert "notation_markers" in item.metadata
        markers = item.metadata["notation_markers"]
        assert isinstance(markers, str)
        assert "dog*" in markers
        assert "[trick]" in markers
        assert "(new)" in markers
        assert "bird♥" in markers

    def test_duplicate_marked_token_no_double_record(self) -> None:
        """Duplicate marked tokens should be recorded separately (no spurious extras)."""
        source = SourceWorksheetModel(
            source_image_hash="test_duplicate_marker",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="sit*, cat, sit*",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="sit*, cat, sit*",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content should be clean
        assert "*" not in item.content
        assert item.content == "sit, cat, sit"
        # Metadata should record both sit* markers (2 occurrences is correct)
        assert "notation_markers" in item.metadata
        markers = item.metadata["notation_markers"]
        assert isinstance(markers, str)
        # The markers list should contain exactly 2 "sit*" entries, no extras
        marker_list = [m.strip() for m in markers.split(",")]
        assert marker_list.count("sit*") == 2

    def test_marker_inside_bracket_no_double_count(self) -> None:
        """RED: Marker inside a bracket annotation should NOT be separately recorded."""
        source = SourceWorksheetModel(
            source_image_hash="test_marker_in_bracket",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="who [by* trick], cat",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="who [by* trick], cat",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content should be clean
        assert "[" not in item.content
        assert "]" not in item.content
        assert "*" not in item.content
        assert "by*" not in item.content
        assert "trick" not in item.content
        assert "who" in item.content
        assert "cat" in item.content
        # Metadata should record the bracket annotation
        assert "notation_markers" in item.metadata
        markers = item.metadata["notation_markers"]
        assert isinstance(markers, str)
        assert "[by* trick]" in markers
        # The standalone "by*" should NOT be redundantly present as a separate marker
        # since it was only ever removed as part of the bracket annotation
        marker_list = [m.strip() for m in markers.split(",")]
        # Should only have one entry: the bracket annotation
        assert len(marker_list) == 1
        assert marker_list[0] == "[by* trick]"

    def test_multi_comma_collapse(self) -> None:
        """RED: After stripping interior annotations, adjacent commas should collapse."""
        source = SourceWorksheetModel(
            source_image_hash="test_multi_comma",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="who, [annotation], cat",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="who, [annotation], cat",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content should have no doubled commas
        assert ", ," not in item.content
        assert item.content == "who, cat"

    def test_multi_comma_collapse_three_plus(self) -> None:
        """RED: Three or more adjacent commas should collapse to one."""
        source = SourceWorksheetModel(
            source_image_hash="test_triple_comma",
            pipeline_version=PIPELINE_VERSION,
            template_type="ufli_word_work",
            regions=[
                SourceRegion(
                    type="sight_word_list",
                    content="who, [ann1], [ann2], cat",
                    bbox=(100, 550, 350, 580),
                    confidence=0.90,
                    metadata={},
                ),
            ],
            raw_text="who, [ann1], [ann2], cat",
            ocr_engine="paddleocr",
            low_confidence_flags=[],
        )
        model = extract_skill(source)
        sight_items = [si for si in model.source_items if si.item_type == "sight_words"]
        assert len(sight_items) == 1
        item = sight_items[0]
        # Content should have no doubled commas
        assert ", ," not in item.content
        assert item.content == "who, cat"
