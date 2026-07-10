"""Deterministic content coverage validation for source-preserving adaptations."""

from __future__ import annotations

import re
from collections.abc import Sequence

from adapt.schema import ActivityItem, AdaptedActivityModel
from skill.schema import LiteracySkillModel, SourceItem
from validate.schema import ValidationResult

_ALPHA_RE = re.compile(r"[a-z]+")
_NUMBERED_ITEM_RE = re.compile(r"\b\d+\.\s*")
_BLANK_RE = re.compile(r"_{2,}|\[[^\]]*blank[^\]]*\]", re.IGNORECASE)
_MAX_STUDENT_SENTENCE_WORDS = 20


def validate_content_coverage(
    source_skill: LiteracySkillModel,
    adapted: AdaptedActivityModel,
    min_target_coverage: float = 0.8,
) -> ValidationResult:
    """Validate that adapted worksheet text preserves source content coverage."""
    result = ValidationResult(validator="content_coverage", passed=True, checks_run=0)
    adapted_text = _adapted_text(adapted)
    adapted_words = _words_from_text(adapted_text)

    if source_skill.template_type == "ufli_word_work":
        result.checks_run += 1
        missing_targets = _target_word_coverage(source_skill, adapted_words, min_target_coverage)
        if missing_targets:
            target_count = len(_target_words(source_skill))
            present_count = target_count - len(missing_targets)
            coverage = present_count / target_count if target_count else 1.0
            result.add_violation(
                check="target_word_coverage",
                message=(
                    f"Adapted worksheet covers {present_count}/{target_count} target words "
                    f"({coverage:.0%}); missing: {', '.join(missing_targets)}"
                ),
                details={
                    "target_count": target_count,
                    "present_count": present_count,
                    "coverage": round(coverage, 3),
                    "missing": ", ".join(missing_targets),
                },
            )

    chain_items = [item for item in source_skill.source_items if item.item_type == "word_chain"]
    if chain_items:
        result.checks_run += 1
        missing_chain_words = sorted(
            {
                word
                for item in chain_items
                for word in _chain_words(item.content)
                if word not in adapted_words
            }
        )
        if missing_chain_words:
            result.add_violation(
                check="word_chain_coverage",
                message=(
                    "Adapted worksheet is missing word-chain words: "
                    f"{', '.join(missing_chain_words)}"
                ),
                details={"missing": ", ".join(missing_chain_words)},
            )

    student_sentences = _student_facing_sentences(source_skill.source_items)
    if student_sentences:
        result.checks_run += 1
        covered_sentences = [
            sentence for sentence in student_sentences if _sentence_covered(sentence, adapted_text)
        ]
        if not covered_sentences:
            result.add_violation(
                check="source_sentence_coverage",
                message=("Adapted worksheet is missing student-facing source sentence coverage"),
                details={
                    "source_sentence_count": len(student_sentences),
                    "source_sentences": " | ".join(student_sentences),
                },
            )

    passage_items = [item for item in source_skill.source_items if item.item_type == "passage"]
    if source_skill.template_type == "ufli_decodable_story" and passage_items:
        result.checks_run += 1
        if not _read_aloud_covers_passage(adapted, passage_items):
            result.add_violation(
                check="decodable_passage_coverage",
                message=(
                    "Decodable passage worksheets must include a read-aloud item "
                    "with the passage title or a substantial passage excerpt"
                ),
                details={"passage_count": len(passage_items)},
            )

    return result


def validate_content_coverage_for_package(
    source_skill: LiteracySkillModel,
    adapted_worksheets: Sequence[AdaptedActivityModel],
    min_target_coverage: float = 0.8,
) -> ValidationResult:
    """Validate content coverage across a multi-worksheet lesson package."""
    if not adapted_worksheets:
        result = ValidationResult(validator="content_coverage", passed=True, checks_run=0)
        result.add_violation(
            check="package_non_empty",
            message="Multi-worksheet package has no adapted worksheets",
        )
        return result

    first = adapted_worksheets[0]
    combined = first.model_copy(
        update={
            "chunks": [chunk for adapted in adapted_worksheets for chunk in adapted.chunks],
            "worksheet_title": " ".join(
                adapted.worksheet_title or "" for adapted in adapted_worksheets
            ),
        }
    )
    return validate_content_coverage(source_skill, combined, min_target_coverage)


def _adapted_text(adapted: AdaptedActivityModel) -> str:
    """Collect visible adapted worksheet text."""
    parts: list[str] = []
    if adapted.worksheet_title:
        parts.append(adapted.worksheet_title)
    if adapted.feedback:
        parts.append(adapted.feedback.goal_statement)
        parts.append(adapted.feedback.child_prompt)

    for chunk in adapted.chunks:
        parts.append(chunk.micro_goal)
        parts.extend(step.text for step in chunk.instructions)
        if chunk.worked_example:
            parts.append(chunk.worked_example.instruction)
            parts.append(chunk.worked_example.content)
        for item in chunk.items:
            parts.append(item.content)
            if item.options:
                parts.extend(item.options)
            parts.extend(_student_facing_answer_text(item))

    return "\n".join(parts)


def _student_facing_answer_text(item: ActivityItem) -> list[str]:
    """Return answer text only when answering is the visible student task."""
    if not item.answer:
        return []

    answer = item.answer.strip()
    if not answer:
        return []

    if item.response_format == "write" and item.metadata.get("display") == "chain_step":
        return [answer]

    if item.response_format == "fill_blank" and _has_blank_marker(item.content):
        return [answer, _fill_blank(item.content, answer)]

    return []


def _has_blank_marker(text: str) -> bool:
    return bool(_BLANK_RE.search(text))


def _fill_blank(text: str, answer: str) -> str:
    return _BLANK_RE.sub(answer, text)


def _words_from_text(text: str) -> set[str]:
    """Return lowercase alphabetic tokens from text."""
    return set(_ALPHA_RE.findall(text.lower()))


def _target_word_coverage(
    source_skill: LiteracySkillModel,
    adapted_words: set[str],
    min_target_coverage: float,
) -> list[str]:
    targets = _target_words(source_skill)
    if not targets:
        return []

    missing = sorted(word for word in targets if word not in adapted_words)
    if len(targets) < 4:
        return missing

    covered = len(targets) - len(missing)
    coverage = covered / len(targets)
    return missing if coverage < min_target_coverage else []


def _target_words(source_skill: LiteracySkillModel) -> set[str]:
    return _words_from_text(" ".join(source_skill.target_words))


def _chain_words(content: str) -> set[str]:
    return _words_from_text(content)


def _student_facing_sentences(source_items: list[SourceItem]) -> list[str]:
    sentences: list[str] = []
    for item in source_items:
        if item.item_type != "sentence" or _is_teacher_only(item):
            continue

        cleaned = _NUMBERED_ITEM_RE.sub("", item.content)
        for sentence in re.findall(r"[^.!?]+[.!?]?", cleaned):
            sentence = sentence.strip()
            words = _ALPHA_RE.findall(sentence.lower())
            if 1 < len(words) <= _MAX_STUDENT_SENTENCE_WORDS:
                sentences.append(sentence.rstrip(".!?"))

    return sentences


def _is_teacher_only(item: SourceItem) -> bool:
    if bool(item.metadata.get("teacher_only", False)):
        return True
    role = item.metadata.get("role")
    return isinstance(role, str) and role.lower() == "teacher"


def _sentence_covered(sentence: str, adapted_text: str) -> bool:
    source_exact = sentence.lower().strip()
    adapted_lower = adapted_text.lower()
    if source_exact and source_exact in adapted_lower:
        return True

    normalized_sentence = _normalize_phrase(sentence)
    normalized_adapted = _normalize_phrase(adapted_text)
    return bool(normalized_sentence and normalized_sentence in normalized_adapted)


def _normalize_phrase(text: str) -> str:
    return " ".join(_ALPHA_RE.findall(text.lower()))


def _read_aloud_covers_passage(
    adapted: AdaptedActivityModel,
    passage_items: list[SourceItem],
) -> bool:
    read_aloud_text = "\n".join(
        item.content
        for chunk in adapted.chunks
        for item in chunk.items
        if item.response_format == "read_aloud"
    )
    if not read_aloud_text:
        return False

    normalized_read_aloud = _normalize_phrase(read_aloud_text)
    read_aloud_words = normalized_read_aloud.split()
    for passage_item in passage_items:
        title = _passage_title(passage_item.content)
        if title and _normalize_phrase(title) in normalized_read_aloud:
            return True

        passage_words = _normalize_phrase(passage_item.content).split()
        if _has_substantial_excerpt(passage_words, read_aloud_words):
            return True

    return False


def _passage_title(content: str) -> str | None:
    first_sentence = re.split(r"[.!?]", content, maxsplit=1)[0].strip()
    if not first_sentence:
        return None
    words = _ALPHA_RE.findall(first_sentence.lower())
    if len(words) <= 6:
        return first_sentence
    return None


def _has_substantial_excerpt(passage_words: list[str], read_aloud_words: list[str]) -> bool:
    if not passage_words or not read_aloud_words:
        return False

    excerpt_len = min(8, max(4, len(passage_words) // 4))
    if len(passage_words) < excerpt_len:
        excerpt_len = len(passage_words)

    read_aloud_text = " ".join(read_aloud_words)
    for start in range(0, len(passage_words) - excerpt_len + 1):
        excerpt = " ".join(passage_words[start : start + excerpt_len])
        if excerpt in read_aloud_text:
            return True
    return False
