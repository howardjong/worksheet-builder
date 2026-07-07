"""Build a LiteracySkillModel directly from a UFLI lesson number.

The photo pipeline (capture → OCR → extract_skill) has no entry point for the
MVP ask "make me a worksheet from lesson N". This module bridges the corpus
straight to a skill model, mirroring what skill/extractor._extract_word_work +
_enrich_from_corpus produce for a UFLI Word Work page — minus the OCR. Content
comes from corpus.ufli.lookup (real corpus when present, committed fixture
otherwise).
"""

from __future__ import annotations

from corpus.ufli.lookup import lookup_lesson
from skill.extractor import (
    build_word_work_objectives,
    clean_corpus_passage,
    grade_from_lesson,
    normalize_concept,
    sanitize_concept_text,
)
from skill.schema import LiteracySkillModel, SourceItem
from skill.taxonomy import match_phonics_pattern

_CORPUS_SOURCE: dict[str, str | int | float | bool] = {"source": "corpus"}


class LessonNotFoundError(ValueError):
    """Raised when a lesson number has no corpus entry (real or fixture)."""

    def __init__(self, lesson_number: int) -> None:
        super().__init__(
            f"No corpus data for UFLI lesson {lesson_number}. Provide "
            "data/ufli/normalized.jsonl or add the lesson to the fixture corpus."
        )
        self.lesson_number = lesson_number


def skill_model_from_lesson(lesson_number: int) -> LiteracySkillModel:
    """Build a LiteracySkillModel for a UFLI lesson straight from the corpus.

    Raises LessonNotFoundError if neither the real corpus nor the fixture has
    the lesson.
    """
    result = lookup_lesson(lesson_number)
    if result is None:
        raise LessonNotFoundError(lesson_number)

    concept_label = sanitize_concept_text(result.concept)
    specific_skill = "phonics_pattern"
    if concept_label:
        specific_skill = match_phonics_pattern(concept_label) or normalize_concept(concept_label)

    words = _roll_and_read_words(result.additional_text)

    source_items: list[SourceItem] = []
    # Practice word list — drives the word-discovery + word-practice worksheets.
    if words:
        source_items.append(
            SourceItem(
                item_type="word_list",
                content=", ".join(words),
                source_region_index=-1,
                metadata=dict(_CORPUS_SOURCE),
            )
        )
        # Roll and Read block (mirrors _enrich_from_corpus); the adapt engine
        # re-parses the raw text at consumption time.
        source_items.append(
            SourceItem(
                item_type="roll_and_read",
                content=result.additional_text.strip(),
                source_region_index=-1,
                metadata=dict(_CORPUS_SOURCE),
            )
        )
    # Decodable passage (mirrors _enrich_from_corpus).
    passage = clean_corpus_passage(result.decodable_text)
    if passage:
        source_items.append(
            SourceItem(
                item_type="passage",
                content=passage,
                source_region_index=-1,
                metadata=dict(_CORPUS_SOURCE),
            )
        )
    # Home-practice sentences — the adapt engine splits and dedupes them.
    if result.home_practice_text.strip():
        source_items.append(
            SourceItem(
                item_type="sentence",
                content=result.home_practice_text.strip(),
                source_region_index=-1,
                metadata=dict(_CORPUS_SOURCE),
            )
        )

    objectives = build_word_work_objectives(specific_skill, concept_label, words)

    return LiteracySkillModel(
        grade_level=grade_from_lesson(lesson_number),
        domain="phonics",
        specific_skill=specific_skill,
        learning_objectives=objectives,
        target_words=words,
        response_types=["write", "read_aloud"],
        source_items=source_items,
        extraction_confidence=1.0,
        template_type="ufli_word_work",
        lesson_number=lesson_number,
    )


def _roll_and_read_words(text: str) -> list[str]:
    """Clean words from a Roll and Read block.

    Mirrors adapt.engine._parse_roll_and_read: skip the header, copyright, and
    lesson-marker lines; keep alphabetic tokens of length >= 2, deduplicated in
    order. Kept local so skill/ stays independent of adapt/.
    """
    words: list[str] = []
    seen: set[str] = set()
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("©") or "University of Florida" in line:
            continue
        low = line.lower()
        if low.startswith("roll and read") or low.startswith("lesson"):
            continue
        for raw_token in line.replace(",", " ").split():
            token = raw_token.strip().lower()
            if len(token) < 2 or not token.isalpha():
                continue
            if token not in seen:
                seen.add(token)
                words.append(token)
    return words
