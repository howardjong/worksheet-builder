"""Tests for extract/ocr.py, extract/heuristics.py, and extract/schema.py."""

from __future__ import annotations

from extract.heuristics import detect_ufli_template, map_to_source_model
from extract.schema import (
    LOW_CONFIDENCE_THRESHOLD,
    OCRBlock,
    OCRResult,
    SourceWorksheetModel,
    flag_low_confidence,
)

# --- Fixtures: synthetic OCR results ---


def _word_work_ocr() -> OCRResult:
    """Synthetic OCR result mimicking a UFLI Word Work page."""
    blocks = [
        OCRBlock(text="Home Practice", bbox=(50, 10, 400, 60), confidence=0.98),
        OCRBlock(text="Lesson 43", bbox=(50, 70, 300, 110), confidence=0.97),
        OCRBlock(text="New Concept and Sample Words", bbox=(50, 150, 500, 200), confidence=0.95),
        OCRBlock(text="-all, -oll, -ull", bbox=(100, 210, 400, 250), confidence=0.93),
        OCRBlock(text="tall", bbox=(100, 260, 200, 290), confidence=0.96),
        OCRBlock(text="call", bbox=(100, 300, 200, 330), confidence=0.95),
        OCRBlock(text="wall", bbox=(100, 340, 200, 370), confidence=0.94),
        OCRBlock(text="Word Work Chains", bbox=(550, 150, 900, 200), confidence=0.97),
        OCRBlock(text="1. all → fall → mall → small", bbox=(550, 210, 950, 250), confidence=0.92),
        OCRBlock(text="2. call → hall → tall → stall", bbox=(550, 260, 960, 300), confidence=0.91),
        OCRBlock(
            text="Sample Word Work Chain Script",
            bbox=(550, 350, 950, 400),
            confidence=0.96,
        ),
        OCRBlock(
            text="1. Write the word all. [spelling]",
            bbox=(550, 410, 950, 450),
            confidence=0.94,
        ),
        OCRBlock(
            text="2. Add f at the beginning. What word is this? [reading]",
            bbox=(550, 460, 1000, 500),
            confidence=0.93,
        ),
        OCRBlock(text="New Irregular Words", bbox=(50, 500, 400, 540), confidence=0.96),
        OCRBlock(text="go*, no*, so*", bbox=(100, 550, 350, 580), confidence=0.90),
        OCRBlock(text="Sentences", bbox=(550, 500, 800, 540), confidence=0.97),
        OCRBlock(
            text="1. The bin is so full.",
            bbox=(550, 550, 900, 580),
            confidence=0.95,
        ),
        OCRBlock(
            text="2. I will go to the big mall.",
            bbox=(550, 590, 950, 620),
            confidence=0.94,
        ),
    ]
    raw_text = "\n".join(b.text for b in blocks)
    return OCRResult(blocks=blocks, engine="paddleocr", raw_text=raw_text)


def _decodable_story_ocr() -> OCRResult:
    """Synthetic OCR result mimicking a UFLI Decodable Story page."""
    blocks = [
        OCRBlock(text="Lesson 58", bbox=(50, 10, 300, 50), confidence=0.97),
        OCRBlock(text="June's Flute", bbox=(200, 100, 600, 150), confidence=0.96),
        OCRBlock(
            text=(
                "June has a flute. June likes to use the flute to make tunes. "
                "There is one tune June likes best. She likes the song Sand Dunes. "
                "June has a pal. Luke has no flute, but Luke likes to sing."
            ),
            bbox=(50, 300, 900, 600),
            confidence=0.94,
        ),
        OCRBlock(
            text=(
                "Once, June and Luke made tunes at lunch for their pals. "
                "The last song they did was Sand Dunes. June was on the flute "
                "and Luke sang. They did a fine job!"
            ),
            bbox=(50, 620, 900, 850),
            confidence=0.93,
        ),
    ]
    raw_text = "\n".join(b.text for b in blocks)
    return OCRResult(blocks=blocks, engine="paddleocr", raw_text=raw_text)


def _unknown_layout_ocr() -> OCRResult:
    """Synthetic OCR result for an unknown layout."""
    blocks = [
        OCRBlock(text="Math Quiz", bbox=(100, 10, 400, 60), confidence=0.98),
        OCRBlock(text="1. 2 + 3 = ___", bbox=(50, 100, 400, 140), confidence=0.95),
        OCRBlock(text="2. 5 + 1 = ___", bbox=(50, 160, 400, 200), confidence=0.94),
        OCRBlock(text="3. 4 + 4 = ___", bbox=(50, 220, 400, 260), confidence=0.96),
    ]
    raw_text = "\n".join(b.text for b in blocks)
    return OCRResult(blocks=blocks, engine="paddleocr", raw_text=raw_text)


# --- Template Detection Tests ---


class TestDetectUfliTemplate:
    def test_word_work_detected(self) -> None:
        result = detect_ufli_template(_word_work_ocr())
        assert result == "ufli_word_work"

    def test_decodable_story_detected(self) -> None:
        result = detect_ufli_template(_decodable_story_ocr())
        assert result == "ufli_decodable_story"

    def test_unknown_layout(self) -> None:
        result = detect_ufli_template(_unknown_layout_ocr())
        assert result == "unknown"

    def test_empty_ocr(self) -> None:
        empty = OCRResult(blocks=[], engine="paddleocr", raw_text="")
        result = detect_ufli_template(empty)
        assert result == "unknown"


# --- Source Model Mapping Tests ---


class TestMapToSourceModel:
    def test_word_work_regions(self) -> None:
        ocr = _word_work_ocr()
        model = map_to_source_model(ocr, source_image_hash="abc123")

        assert model.template_type == "ufli_word_work"
        assert model.source_image_hash == "abc123"
        assert model.ocr_engine == "paddleocr"
        assert len(model.regions) > 0

        types = {r.type for r in model.regions}
        assert "title" in types
        assert "concept_label" in types
        assert "word_chain" in types or "chain_script" in types
        assert "sight_word_list" in types or "sample_words" in types

    def test_word_work_has_sample_words(self) -> None:
        ocr = _word_work_ocr()
        model = map_to_source_model(ocr, source_image_hash="abc123")
        sample_word_regions = [r for r in model.regions if r.type == "sample_words"]
        # Should have extracted at least some sample words (tall, call, wall, etc.)
        assert len(sample_word_regions) >= 1

    def test_decodable_story_regions(self) -> None:
        ocr = _decodable_story_ocr()
        model = map_to_source_model(ocr, source_image_hash="def456")

        assert model.template_type == "ufli_decodable_story"
        types = {r.type for r in model.regions}
        assert "story_title" in types or "decodable_passage" in types
        # Must have passage content
        passage_regions = [r for r in model.regions if r.type == "decodable_passage"]
        assert len(passage_regions) >= 1

    def test_unknown_layout_regions(self) -> None:
        ocr = _unknown_layout_ocr()
        model = map_to_source_model(ocr, source_image_hash="ghi789")

        assert model.template_type == "unknown"
        assert len(model.regions) > 0
        # Should have title from top region
        types = {r.type for r in model.regions}
        assert "title" in types

    def test_pydantic_validation(self) -> None:
        ocr = _word_work_ocr()
        model = map_to_source_model(ocr, source_image_hash="test")

        # Should serialize and deserialize cleanly
        json_str = model.model_dump_json()
        restored = SourceWorksheetModel.model_validate_json(json_str)
        assert restored.template_type == model.template_type
        assert len(restored.regions) == len(model.regions)

    def test_deterministic(self) -> None:
        ocr = _word_work_ocr()
        m1 = map_to_source_model(ocr, source_image_hash="test")
        m2 = map_to_source_model(ocr, source_image_hash="test")

        assert m1.model_dump() == m2.model_dump()


# --- Confidence Gating Tests ---


class TestConfidenceGating:
    def test_flags_low_confidence(self) -> None:
        ocr = _word_work_ocr()
        model = map_to_source_model(ocr, source_image_hash="test")

        # Check that any regions below threshold are flagged
        for idx in model.low_confidence_flags:
            assert model.regions[idx].confidence < LOW_CONFIDENCE_THRESHOLD

    def test_flag_function_direct(self) -> None:
        from extract.schema import SourceRegion

        regions = [
            SourceRegion(
                type="word_list", content="hello", bbox=(0, 0, 1, 1), confidence=0.9, metadata={}
            ),
            SourceRegion(
                type="word_list", content="world", bbox=(0, 0, 1, 1), confidence=0.5, metadata={}
            ),
            SourceRegion(
                type="word_list", content="test", bbox=(0, 0, 1, 1), confidence=0.3, metadata={}
            ),
        ]
        flags = flag_low_confidence(regions)
        assert flags == [1, 2]

    def test_no_flags_when_all_confident(self) -> None:
        from extract.schema import SourceRegion

        regions = [
            SourceRegion(
                type="word_list", content="hello", bbox=(0, 0, 1, 1), confidence=0.9, metadata={}
            ),
        ]
        flags = flag_low_confidence(regions)
        assert flags == []
