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
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from skill.schema import LiteracySkillModel

if TYPE_CHECKING:
    from adapt.llm_adapt import LessonPlan, PlannedItem
    from adapt.rules import AccommodationRules

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


class CoverageReport(BaseModel):
    """Result of verifying an authored plan against the coverage ledger."""

    missing: list[CoverageLedgerEntry]  # required entries not actually covered
    unknown_claims: list[str]  # claimed ids that aren't in the ledger


def _normalize(text: str) -> str:
    """Casefold and collapse whitespace for exact-text presence checks."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def _item_haystack(item: PlannedItem) -> str:
    """All authored text of an item where source content could legitimately appear."""
    parts = [item.content, *item.options]
    if item.answer:
        parts.append(item.answer)
    return _normalize(" ".join(p for p in parts if p))


def verify_coverage(plan: LessonPlan, ledger: list[CoverageLedgerEntry]) -> CoverageReport:
    """Check the plan against the ledger: claim AND exact-text presence both required.

    A required entry is covered iff some authored item (a) lists the entry's id in
    ``covered_source_item_ids`` AND (b) the entry's ``exact_text`` actually appears
    (normalized) in that item's content/options/answer. A claimed id without the
    matching text never counts (closes the trust loophole). Claimed ids absent from
    the ledger are reported as ``unknown_claims``.
    """
    known_ids = {e.source_item_id for e in ledger}
    items = [
        item for ws in plan.worksheets for activity in ws.activities for item in activity.items
    ]
    # Per-item normalized text, paired with the set of ids that item claims.
    authored = [(set(item.covered_source_item_ids), _item_haystack(item)) for item in items]

    missing: list[CoverageLedgerEntry] = []
    for entry in ledger:
        if entry.priority != "required":
            continue
        needle = _normalize(entry.exact_text)
        covered = any(
            entry.source_item_id in claimed and needle in haystack for claimed, haystack in authored
        )
        if not covered:
            missing.append(entry)

    unknown_claims: list[str] = []
    for claimed, _ in authored:
        for cid in claimed:
            if cid not in known_ids and cid not in unknown_claims:
                unknown_claims.append(cid)

    return CoverageReport(missing=missing, unknown_claims=unknown_claims)


# Deterministic catch-up chunk size when no rules are passed (a safe ADHD chunk).
_REPAIR_CHUNK_DEFAULT = 4
# Content types practiced by reading the whole text rather than writing it.
_REPAIR_READ_TYPES = {"sentence", "passage"}


def repair_coverage(
    plan: LessonPlan,
    missing: list[CoverageLedgerEntry],
    rules: AccommodationRules | None = None,
) -> LessonPlan:
    """Append a deterministic "Catch-up practice" worksheet covering every gap.

    No LLM call: each missing required entry becomes its own practice item
    (content = exact_text, tagged with its source id) so the verifier passes.
    Items are chunked to the per-section item cap so translation keeps them all;
    ``enforce_section_cap`` later splits the catch-up worksheet across pages.
    Returns the plan unchanged when nothing is missing.
    """
    if not missing:
        return plan

    from adapt.llm_adapt import ActivityPlan, PlannedItem, WorksheetPlan

    chunk_size = rules.max_items_per_chunk if rules is not None else _REPAIR_CHUNK_DEFAULT
    items = [
        PlannedItem(
            content=entry.exact_text,
            response_format=("read_aloud" if entry.item_type in _REPAIR_READ_TYPES else "write"),
            covered_source_item_ids=[entry.source_item_id],
        )
        for entry in missing
    ]
    activities = [
        ActivityPlan(
            activity_type="write",
            micro_goal="Practice the words and sentences from your lesson.",
            items=items[i : i + chunk_size],
            instructions=["Read each one out loud.", "Then write it."],
            response_format="write",
            rationale="Deterministic catch-up: every source item gets its own practice.",
        )
        for i in range(0, len(items), chunk_size)
    ]
    catch_up = WorksheetPlan(title="Catch-up practice", activities=activities)
    return plan.model_copy(update={"worksheets": [*plan.worksheets, catch_up]})
