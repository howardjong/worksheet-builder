"""Exhaustive practice evidence for photographed content, never lesson sampling."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel

from adapt.schema import ActivityItem, AdaptedActivityModel
from skill.schema import LiteracySkillModel
from validate.content_coverage import _fill_blank, _has_blank_marker, _is_teacher_only
from validate.schema import ValidationResult


class PracticeEvidence(BaseModel):
    kind: str
    source: str
    practice_refs: list[str]


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z]+", text.lower()))


def _practice_text(item: ActivityItem) -> str:
    text = item.content
    # A correct production answer is practice even though it is not printed.
    # Distractors, examples, goals and hidden answers to other tasks aren't evidence.
    if item.answer:
        if item.response_format == "write" and item.metadata.get("display") == "chain_step":
            text += " " + item.answer
        elif item.response_format == "fill_blank" and _has_blank_marker(text):
            text = _fill_blank(text, item.answer)
        elif item.response_format == "circle" and item.answer in (item.options or []):
            text += " " + item.answer
    return _normalize(text)


def photo_coverage_ledger(
    skill: LiteracySkillModel, worksheets: Sequence[AdaptedActivityModel]
) -> list[PracticeEvidence]:
    practice = [
        (
            f"worksheet:{index}/chunk:{chunk.chunk_id}/item:{item.item_id}",
            _practice_text(item),
            item,
        )
        for index, worksheet in enumerate(worksheets, 1)
        for chunk in worksheet.chunks
        for item in chunk.items
    ]
    required: list[tuple[str, str]] = [("target_word", word) for word in skill.target_words]
    for source in skill.source_items:
        if _is_teacher_only(source) or source.item_type == "chain_script":
            continue
        if source.item_type in {"word_list", "sight_words", "word_chain"}:
            required.extend(("source_word", word) for word in _normalize(source.content).split())
        elif source.item_type == "sentence":
            required.extend(
                ("source_sentence", sentence)
                for sentence in re.split(r"[.!?]+", source.content)
                if _normalize(sentence)
            )
        elif source.item_type == "passage":
            required.append(("source_passage", source.content))
        else:
            required.append(("unsupported_source", source.content))

    evidence: list[PracticeEvidence] = []
    for kind, content in dict.fromkeys(required):
        normalized = _normalize(content)
        refs = [
            ref
            for ref, text, item in practice
            if normalized
            and kind != "unsupported_source"
            and f" {normalized} " in f" {text} "
            and (kind != "source_passage" or item.response_format == "read_aloud")
        ]
        # A full passage can be deliberately split into consecutive read-aloud items.
        if kind == "source_passage" and not refs:
            reads = [
                (ref, text) for ref, text, item in practice if item.response_format == "read_aloud"
            ]
            if normalized and f" {normalized} " in " " + " ".join(t for _, t in reads) + " ":
                refs = [ref for ref, _ in reads]
        evidence.append(PracticeEvidence(kind=kind, source=content, practice_refs=refs))
    return evidence


def validate_photo_coverage(
    skill: LiteracySkillModel, worksheets: Sequence[AdaptedActivityModel]
) -> tuple[ValidationResult, list[PracticeEvidence]]:
    ledger = photo_coverage_ledger(skill, worksheets)
    result = ValidationResult(
        validator="photo_content_coverage", passed=True, checks_run=len(ledger)
    )
    if not worksheets or not ledger:
        result.add_violation(
            check="verifiable_source", message="No verifiable photo practice content"
        )
    for entry in ledger:
        if not entry.practice_refs:
            result.add_violation(
                check=entry.kind,
                message=f"No practice evidence for {entry.kind}: {entry.source}",
                details={"source": entry.source},
            )
    return result, ledger
