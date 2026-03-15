"""Tests for RAG-influenced adaptation behavior."""

from __future__ import annotations

from adapt.engine import adapt_activity, adapt_lesson
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


def _curriculum_refs(document: str) -> list[dict[str, object]]:
    return [
        {
            "lesson_id": "59",
            "concept": "VCe Review 2",
            "_rag_doc_id": "curriculum_ufli_59",
            "_rag_score": 0.96,
            "_rag_document": document,
        }
    ]


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


def test_curriculum_prioritizes_supported_target_words() -> None:
    skill = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read words with CVCe pattern"],
        target_words=["grsde", "grade", "sllde", "slide", "quite"],
        response_types=["write", "read_aloud"],
        source_items=[],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )

    worksheets = adapt_lesson(
        skill,
        _profile(),
        rag_curriculum_references=_curriculum_refs(
            "Lesson 59 VCe Review 2 words: grade slide quite froze these",
        ),
    )
    discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"][0]
    match_words = [
        item.content
        for chunk in discovery.chunks
        for item in chunk.items
        if item.response_format == "match"
    ]

    assert match_words[:3] == ["grade", "slide", "quite"]
    assert discovery.chunks[0].items[0].metadata["curriculum_supported"] is True


def test_curriculum_requires_multiple_matches_before_reordering() -> None:
    skill = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read words with CVCe pattern"],
        target_words=["grsde", "grade", "sllde", "quite"],
        response_types=["write"],
        source_items=[],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )

    adapted = adapt_activity(
        skill,
        _profile(),
        rag_curriculum_references=_curriculum_refs("Lesson 59 target word: grade"),
    )
    words = [item.content for chunk in adapted.chunks for item in chunk.items]

    assert words[:4] == ["grsde", "grade", "sllde", "quite"]
