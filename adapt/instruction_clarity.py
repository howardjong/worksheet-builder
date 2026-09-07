"""Deterministic clarity contract for child-facing worksheet instructions.

Instructions are provider-authored content, so schema-valid strings are not
enough.  This module enforces a small, source-agnostic contract: every step
must name an observable action and its object, and repetition must name both
the action and the amount.  Ambiguous provider output is replaced with a
response-format-specific instruction set before it can reach rendering.
"""

from __future__ import annotations

import re

from adapt.schema import ActivityChunk, AdaptedActivityModel, Step

_ACTION_VERBS = frozenset(
    {
        "add",
        "ask",
        "change",
        "choose",
        "circle",
        "complete",
        "copy",
        "double",
        "do",
        "draw",
        "drop",
        "fill",
        "find",
        "follow",
        "get",
        "look",
        "listen",
        "point",
        "read",
        "remove",
        "say",
        "stand",
        "take",
        "tap",
        "think",
        "touch",
        "trace",
        "underline",
        "write",
    }
)

_AMBIGUOUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("attempt_without_action", re.compile(r"\btry\b", re.IGNORECASE)),
    ("vague_reference", re.compile(r"\b(each one|those words|these words|write it)\b", re.I)),
    ("vague_completion", re.compile(r"\bcomplete (?:the )?(?:activity|items?) below\b", re.I)),
    ("subjective_choice", re.compile(r"\bcircle (?:the )?(?:right|best|correct)\b", re.I)),
    ("unnamed_ending", re.compile(r"\badd the ending\b(?!\s+(?:shown|printed|named))", re.I)),
    (
        "unnamed_change",
        re.compile(r"\bmake the (?:verified|spelling) change\b(?!\s+printed)", re.I),
    ),
)


def instruction_clarity_issues(text: str) -> list[str]:
    """Return stable issue codes for an ambiguous instruction string."""
    normalized = " ".join(text.split())
    if not normalized:
        return ["empty_instruction"]

    issues = [code for code, pattern in _AMBIGUOUS_PATTERNS if pattern.search(normalized)]
    first_word_match = re.match(r"[A-Za-z]+", normalized)
    if first_word_match is None or first_word_match.group(0).lower() not in _ACTION_VERBS:
        issues.append("missing_observable_action")
    return issues


def instructions_are_clear(chunk: ActivityChunk) -> bool:
    """Return whether every instruction in a non-empty chunk is explicit."""
    return bool(chunk.instructions) and all(
        not instruction_clarity_issues(step.text) for step in chunk.instructions
    )


def _list_repetition(chunk: ActivityChunk) -> str | None:
    for step in chunk.instructions:
        match = re.search(
            r"\b(?:try|read) (?:the )?(?:entire )?list(?: aloud)? "
            r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+) times\b",
            step.text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).lower()
    return None


def canonical_instruction_texts(
    chunk: ActivityChunk, *, list_repetition: str | None = None
) -> list[str]:
    """Build explicit instructions from task semantics, never source branding."""
    formats = {item.response_format for item in chunk.items}
    displays = {str(item.metadata.get("display", "")) for item in chunk.items}

    if "roll_and_read" in displays or list_repetition is not None:
        repetition = list_repetition or "three"
        return [
            "Read every word aloud at a smooth pace.",
            f"Read the entire list aloud {repetition} times.",
            "Point to each word while you read it.",
        ]
    if displays & {"chain_step", "derived_word"} or any(
        item.transformation is not None for item in chunk.items
    ):
        return [
            "Read the base word in each problem aloud.",
            "Follow the spelling change printed in each problem.",
            "Write each complete new word on its line.",
        ]
    if formats == {"match"}:
        return [
            "Look at every picture and read every word.",
            "Draw one line from each picture to its matching word.",
        ]
    if formats == {"trace"}:
        return ["Say each printed word aloud.", "Trace every dotted letter in each word."]
    if formats == {"sound_box"}:
        return [
            "Say each printed word aloud.",
            "Tap once for every sound you hear.",
            "Write one sound in each box for that word.",
        ]
    if formats == {"read_aloud"}:
        has_connected_text = any(
            len(item.content.split()) > 1 or bool(re.search(r"[.!?]", item.content))
            for item in chunk.items
        )
        object_name = "printed sentence" if has_connected_text else "word in the list"
        return [
            f"Read every {object_name} aloud.",
            "Point to each word while you read it.",
        ]
    if formats == {"circle"}:
        multiple_answers = any("," in (item.answer or "") for item in chunk.items)
        if multiple_answers:
            return [
                "Read every word in the choice row.",
                "Circle every word that follows the named pattern.",
            ]
        return [
            "Read each prompt and every answer choice.",
            "Circle one answer for each prompt.",
        ]
    if formats == {"fill_blank"}:
        return [
            "Read each incomplete item and every answer choice.",
            "Circle or write one answer that completes each item.",
        ]
    if formats == {"verbal"}:
        return ["Say each printed word aloud."]
    if formats == {"write"}:
        return [
            "Read each printed item aloud.",
            "Write one complete answer on the line for that item.",
        ]
    return [
        "Read each printed prompt and its answer choices.",
        "Complete the printed action for each prompt.",
    ]


def ensure_clear_chunk_instructions(chunk: ActivityChunk) -> ActivityChunk:
    """Return a chunk whose steps satisfy the deterministic clarity contract."""
    texts = (
        [step.text.strip() for step in chunk.instructions]
        if instructions_are_clear(chunk)
        else canonical_instruction_texts(chunk, list_repetition=_list_repetition(chunk))
    )
    instructions = [Step(number=index, text=text) for index, text in enumerate(texts, start=1)]
    worked_example = chunk.worked_example
    if worked_example is not None and instruction_clarity_issues(worked_example.instruction):
        worked_example = worked_example.model_copy(
            update={"instruction": "Read the completed example before you begin."}
        )
    return chunk.model_copy(update={"instructions": instructions, "worked_example": worked_example})


def ensure_clear_instructions(
    worksheets: list[AdaptedActivityModel],
) -> list[AdaptedActivityModel]:
    """Normalize instruction clarity at an adapted-package stage boundary."""
    return [
        worksheet.model_copy(
            update={
                "chunks": [ensure_clear_chunk_instructions(chunk) for chunk in worksheet.chunks]
            }
        )
        for worksheet in worksheets
    ]
