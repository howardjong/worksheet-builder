"""Deterministic coverage ledger — the hard contract for source preservation.

Built from the frozen ``LiteracySkillModel`` with NO LLM call. Every source
word, word-chain step, sentence, and passage becomes a ledger entry with a
stable id and the ``exact_text`` that MUST appear in an authored practice item.
The planner prompt carries this ledger (Task S1), a deterministic verifier
checks the authored plan against it (Task S2), and a deterministic repair pass
fills any gaps (Task S3) — so content coverage stops being a source of
generation variance.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from skill.schema import LiteracySkillModel

ItemType = Literal[
    "word",
    "word_chain",
    "word_chain_step",
    "sentence",
    "passage",
    "roll_and_read_word",
    "sight_word",
]


class CoverageLedgerEntry(BaseModel):
    """One unit of source content that the authored plan must preserve."""

    source_item_id: str  # stable, e.g. "word_003", "chain_001_step_2"
    item_type: ItemType
    exact_text: str  # the text that MUST appear in an authored item
    parent_source_text: str | None = None  # e.g. the full chain a step came from
    priority: Literal["required", "optional_enrichment"]
    allowed_practice_forms: list[str]


# Practice forms each content type can legitimately be exercised through.
_ALLOWED_FORMS: dict[str, list[str]] = {
    "word": ["write", "read_aloud", "fill_blank", "circle"],
    "word_chain": ["word_chain"],
    "word_chain_step": ["word_chain", "write"],
    "sentence": ["read_aloud", "write", "sentence_completion"],
    "passage": ["read_aloud"],
    "roll_and_read_word": ["read_aloud"],
    "sight_word": ["write", "read_aloud"],
}

_TOKEN_SPLIT = re.compile(r"[,\n;]+")
_CHAIN_SPLIT = re.compile(r"\s*(?:->|→)\s*")


def _split_tokens(content: str) -> list[str]:
    """Split a comma/newline-separated content blob into clean tokens."""
    return [tok.strip() for tok in _TOKEN_SPLIT.split(content) if tok.strip()]


def _chain_words(content: str) -> list[str]:
    """Split an arrow chain ('mule -> mute -> cute') into its words."""
    return [w.strip() for w in _CHAIN_SPLIT.split(content) if w.strip()]


def build_coverage_ledger(skill: LiteracySkillModel) -> list[CoverageLedgerEntry]:
    """Build the deterministic coverage contract from the frozen skill model."""
    entries: list[CoverageLedgerEntry] = []

    # Words: deduped union of target_words and any word_list source tokens.
    word_tokens: list[str] = list(skill.target_words)
    for si in skill.source_items:
        if si.item_type == "word_list":
            word_tokens.extend(_split_tokens(si.content))
    seen: set[str] = set()
    word_index = 0
    for token in word_tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        word_index += 1
        entries.append(
            CoverageLedgerEntry(
                source_item_id=f"word_{word_index:03d}",
                item_type="word",
                exact_text=token,
                priority="required",
                allowed_practice_forms=_ALLOWED_FORMS["word"],
            )
        )

    # Word chains: one entry for the whole chain (enrichment) plus one required
    # entry per arrow step (the step result is the text that must be authored).
    chain_index = 0
    for si in skill.source_items:
        if si.item_type != "word_chain":
            continue
        chain_index += 1
        chain_id = f"chain_{chain_index:03d}"
        entries.append(
            CoverageLedgerEntry(
                source_item_id=chain_id,
                item_type="word_chain",
                exact_text=si.content.strip(),
                priority="optional_enrichment",
                allowed_practice_forms=_ALLOWED_FORMS["word_chain"],
            )
        )
        words = _chain_words(si.content)
        for step_idx, to_word in enumerate(words[1:], start=1):
            entries.append(
                CoverageLedgerEntry(
                    source_item_id=f"{chain_id}_step_{step_idx}",
                    item_type="word_chain_step",
                    exact_text=to_word,
                    parent_source_text=si.content.strip(),
                    priority="required",
                    allowed_practice_forms=_ALLOWED_FORMS["word_chain_step"],
                )
            )

    # Sentences: full text preserved verbatim, one required entry each.
    sentence_index = 0
    for si in skill.source_items:
        if si.item_type not in ("sentence", "practice_sentences"):
            continue
        sentence_index += 1
        entries.append(
            CoverageLedgerEntry(
                source_item_id=f"sentence_{sentence_index:03d}",
                item_type="sentence",
                exact_text=si.content.strip(),
                priority="required",
                allowed_practice_forms=_ALLOWED_FORMS["sentence"],
            )
        )

    # Passages: full text preserved verbatim, one required entry each.
    passage_index = 0
    for si in skill.source_items:
        if si.item_type != "passage":
            continue
        passage_index += 1
        entries.append(
            CoverageLedgerEntry(
                source_item_id=f"passage_{passage_index:03d}",
                item_type="passage",
                exact_text=si.content.strip(),
                priority="required",
                allowed_practice_forms=_ALLOWED_FORMS["passage"],
            )
        )

    # Sight words: required content, one entry per token.
    sight_index = 0
    for si in skill.source_items:
        if si.item_type not in ("sight_words", "sight_word"):
            continue
        for token in _split_tokens(si.content):
            sight_index += 1
            entries.append(
                CoverageLedgerEntry(
                    source_item_id=f"sight_{sight_index:03d}",
                    item_type="sight_word",
                    exact_text=token,
                    priority="required",
                    allowed_practice_forms=_ALLOWED_FORMS["sight_word"],
                )
            )

    return entries
