"""Tests for RAG-influenced adaptation behavior."""

from __future__ import annotations

from adapt.engine import adapt_lesson
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read words with CVCe pattern"],
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
                content="1. tune -> tone -> cone -> cane",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sight_words",
                content="who, by, my",
                source_region_index=2,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="medium",
            response_format_prefs=["write", "circle", "match"],
        ),
    )


def test_distractor_blacklist_from_rag() -> None:
    prior: list[dict[str, object]] = [
        {
            "source_hash": "prev_1",
            "response_formats": "match,trace,circle",
            "distractor_words": "the,and,cat,dog",
        }
    ]

    worksheets = adapt_lesson(_skill(), _profile(), rag_prior_adaptations=prior)
    discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"][0]

    circle_items = [
        item
        for chunk in discovery.chunks
        for item in chunk.items
        if item.response_format == "circle"
    ]
    assert circle_items

    options = circle_items[0].options or []
    answers = {
        answer.strip().lower()
        for answer in (circle_items[0].answer or "").split(",")
        if answer.strip()
    }
    distractors = {opt.lower() for opt in options if opt.lower() not in answers}

    assert "the" not in distractors
    assert "and" not in distractors
    assert "cat" not in distractors
    assert "dog" not in distractors


def test_format_mix_rotation_from_rag() -> None:
    prior: list[dict[str, object]] = [
        {
            "source_hash": "prev_1",
            "response_formats": "match,trace,circle",
        }
    ]

    worksheets = adapt_lesson(_skill(), _profile(), rag_prior_adaptations=prior)
    discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"][0]

    chunk_formats = [chunk.response_format for chunk in discovery.chunks]
    assert chunk_formats[:2] == ["trace", "match"]
