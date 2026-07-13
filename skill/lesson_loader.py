"""Build a LiteracySkillModel directly from a UFLI lesson number.

The photo pipeline (capture → OCR → extract_skill) has no entry point for the
MVP ask "make me a worksheet from lesson N". This module bridges the corpus
straight to a skill model, mirroring what skill/extractor._extract_word_work +
_enrich_from_corpus produce for a UFLI Word Work page — minus the OCR. Content
comes from corpus.ufli.lookup (real corpus when present, committed fixture
otherwise).
"""

from __future__ import annotations

import logging
import re

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

logger = logging.getLogger(__name__)

_CORPUS_SOURCE: dict[str, str | int | float | bool] = {"source": "corpus"}

# Known PDF-grid extraction fragments (observed live: lesson 74's Roll and Read
# grid extracted "la", a truncated word, which shipped into the cover title and
# match/write sections). Single source of truth — adapt.engine._parse_roll_and_read
# imports this so the two parsers cannot drift apart again.
EXTRACTION_ARTIFACTS = ("la", "le", "re", "de", "el", "al")

# Graphemes are short ("y", "sh", "eigh"); longer concept tokens are English
# words ("digraphs") that would produce junk patterns.
_MAX_GRAPHEME_LEN = 4

# If pattern filtering would drop more than this share of the pool, the
# derived pattern is untrustworthy (e.g. a grid with a review column) — keep
# every word instead.
_MAX_PATTERN_DROP_RATIO = 0.25


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
    words, dropped = _filter_pattern_words(words, _concept_patterns(concept_label))
    if dropped:
        logger.warning(
            "Lesson %d: dropped %d non-conforming Roll and Read token(s) "
            "(extraction artifacts): %s",
            lesson_number,
            len(dropped),
            ", ".join(dropped),
        )

    source_items: list[SourceItem] = []
    # Practice word list — drives the word-discovery + word-practice worksheets.
    if words:
        word_list_metadata = dict(_CORPUS_SOURCE)
        if dropped:
            word_list_metadata["dropped_tokens"] = ", ".join(dropped)
        source_items.append(
            SourceItem(
                item_type="word_list",
                content=", ".join(words),
                source_region_index=-1,
                metadata=word_list_metadata,
            )
        )
        # Roll and Read block (mirrors _enrich_from_corpus). The adapt engine
        # re-parses this content at consumption time, so it is rebuilt from the
        # FILTERED pool — shipping the raw block would resurrect dropped
        # fragments through that second parse.
        source_items.append(
            SourceItem(
                item_type="roll_and_read",
                content="\n".join(words),
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
    # Home-practice content. The real corpus's home_practice_text is a raw dump
    # of the home-practice PDF: section headers ("New Concept and Sample Words"),
    # word-work chain scripts ("Change the nn to dd. What word is this?"),
    # arrow chains with blanks, loose word lists, AND real student sentences —
    # all concatenated. Passing it through raw produced garbled student items
    # (observed live: lesson 74 "Story Time" shipped teacher-script fragments as
    # fill-in tasks). Extract the two usable kinds of content and drop the rest.
    chains, sentences = _home_practice_items(result.home_practice_text)
    for chain in chains:
        source_items.append(
            SourceItem(
                item_type="word_chain",
                content=chain,
                source_region_index=-1,
                metadata=dict(_CORPUS_SOURCE),
            )
        )
    if sentences:
        source_items.append(
            SourceItem(
                item_type="sentence",
                content=" ".join(sentences),
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


# Chain: 2+ alphabetic words joined by arrows. Blank placeholders ("____ →")
# ahead of the first real word are common in the source and are skipped.
_CHAIN_PATTERN = re.compile(r"[a-z]+(?:\s*(?:→|->)\s*[a-z]+)+", re.IGNORECASE)

# Teacher-script stems from UFLI word-work scripts — never student sentences.
_SCRIPT_STEMS = (
    "change the",
    "what word",
    "now change",
    "now spell",
    "if that word",
    "add the",
    "take away",
    "replace the",
    "make the word",
)


def _home_practice_items(text: str) -> tuple[list[str], list[str]]:
    """Extract (word chains, student sentences) from a raw home-practice dump.

    Everything else — section headers, chain scripts, loose word lists, blank
    markers — is dropped. Conservative on purpose: a dropped sentence costs a
    little practice; a kept script fragment ships garbage to a child.
    """
    if not text.strip():
        return [], []

    chains = [
        " → ".join(re.split(r"\s*(?:→|->)\s*", m.group(0))) for m in _CHAIN_PATTERN.finditer(text)
    ]

    # Sentences: split on terminal punctuation, keep the punctuation.
    sentences: list[str] = []
    for fragment in re.findall(r"[^.!?]+[.!?]", text):
        candidate = _strip_non_sentence_prefix(fragment.strip())
        if candidate is None:
            continue
        if len(candidate.split()) < 3:
            continue
        if any(marker in candidate for marker in ("→", "->", "_", "[", "]")):
            continue
        if any(stem in candidate.lower() for stem in _SCRIPT_STEMS):
            continue
        # Every token must be a plain word (letters, optional apostrophe).
        body = candidate[:-1]  # drop terminal punctuation
        if not all(re.fullmatch(r"[A-Za-z][a-z]*(?:'[a-z]+)?", w) for w in body.split()):
            continue
        sentences.append(candidate)
    return chains, sentences


# UFLI home-practice section-header vocabulary — a capitalized token from this
# set is header residue, never the first word of a student sentence.
_HEADER_TOKENS = frozenset(
    {
        "New",
        "Concept",
        "Sample",
        "Word",
        "Words",
        "Work",
        "Chain",
        "Script",
        "Sentences",
        "Irregular",
        "Lesson",
        "Practice",
        "Home",
        "Roll",
        "Read",
    }
)


def _strip_non_sentence_prefix(fragment: str) -> str | None:
    """Drop header/word-list residue that ran into a sentence without punctuation.

    E.g. "New Irregular Words Sentences forty I will bring a teddy for the baby."
    → "I will bring a teddy for the baby." A sentence start is a Capitalized word
    followed by a lowercase word — skipping starts that are themselves header
    vocabulary ("Sentences forty ..."). Returns None when the fragment contains
    no plausible sentence start at all.
    """
    tokens = fragment.split()
    for i in range(len(tokens) - 1):
        if tokens[i] in _HEADER_TOKENS:
            continue
        if re.fullmatch(r"[A-Z][a-z']*", tokens[i]) and re.fullmatch(r"[a-z']+", tokens[i + 1]):
            return " ".join(tokens[i:])
    return None


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
            if token in EXTRACTION_ARTIFACTS:
                continue
            if token not in seen:
                seen.add(token)
                words.append(token)
    return words


def _concept_patterns(concept_label: str) -> list[re.Pattern[str]]:
    """Derive grapheme search patterns from a concept label.

    'y /ē/' → [y]; 'oa, ow' → [oa, ow]; 'a_e' → [a[a-z]e] (split vowel).
    Phoneme notation like /ē/ self-excludes (non-ASCII); English-word tokens
    self-exclude via the length cap. An empty result disables filtering —
    junk tokens can only make the filter MORE permissive (a word is kept if
    ANY pattern matches), never more aggressive.
    """
    patterns: list[re.Pattern[str]] = []
    for token in re.findall(r"[a-z_]+", concept_label.lower()):
        if len(token) > _MAX_GRAPHEME_LEN:
            continue
        if "_" in token:
            parts = [re.escape(p) for p in token.split("_") if p]
            if len(parts) < 2:
                continue
            patterns.append(re.compile("[a-z]".join(parts)))
        else:
            patterns.append(re.compile(re.escape(token)))
    return patterns


def _filter_pattern_words(
    words: list[str], patterns: list[re.Pattern[str]]
) -> tuple[list[str], list[str]]:
    """Split words into (pattern-conformant, dropped extraction suspects).

    Safety valve: if more than _MAX_PATTERN_DROP_RATIO of the pool would be
    dropped, the pattern read is untrustworthy — return every word unchanged.
    """
    if not words or not patterns:
        return words, []
    kept: list[str] = []
    dropped: list[str] = []
    for word in words:
        (kept if any(p.search(word) for p in patterns) else dropped).append(word)
    if len(dropped) / len(words) > _MAX_PATTERN_DROP_RATIO:
        logger.warning(
            "Pattern filter would drop %d/%d Roll and Read words — pattern "
            "read untrustworthy, keeping all: %s",
            len(dropped),
            len(words),
            ", ".join(dropped),
        )
        return words, []
    return kept, dropped
