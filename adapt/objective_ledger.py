"""Data models for the objective-sufficiency coverage system.

This module defines the ObjectiveLedger schema, which tracks per-objective coverage
for a worksheet against UFLI curriculum standards. The ledger classifies source items
by coverage role (required form, samplable pool, etc.) and tracks word-level roles
with confidence signals to support strict validation.

Schema-only for now; builder logic (T2/T3) will be added in later tasks.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Type Aliases (Literal enums)
# ============================================================================

ObjectiveType = Literal[
    "decode_target_pattern",
    "encode_target_pattern",
    "phoneme_grapheme_manipulation",
    "connected_text_fluency",
    "irregular_word_reading",
    "sentence_reading_or_writing",
    "contrast_discrimination",
]

SourceRole = Literal[
    "target_pattern",
    "contrast_word",
    "irregular_word",
    "review_word",
    "supporting_evidence",
    "ambiguous_review_word",
]

CoverageClass = Literal[
    "required_form",
    "samplable_pool",
    "contrast_role",
    "supporting_evidence",
]

RequiredForm = Literal[
    "word_chain",
    "chain_script",
    "encoding_or_spelling",
    "decodable_sentence",
    "decodable_passage",
    "irregular_word_practice",
    "contrast_sort_or_discrimination",
]

RoleConfidence = Literal["high", "low"]

RoleSource = Literal["corpus_exact", "pattern_rule", "source_context", "unknown"]


# ============================================================================
# Core Models
# ============================================================================


class LedgerWord(BaseModel):
    """A single word extracted from a source item, classified by role and confidence.

    The role_confidence and role_source fields enable the validator (T6) to hard-fail
    only on high-confidence classifications and treat low-confidence ones as advisory.
    """

    text: str
    normalized: str
    role: SourceRole
    role_confidence: RoleConfidence  # REQUIRED (no default) — review addition
    role_source: RoleSource  # REQUIRED (no default) — review addition
    objective_ids: list[str] = Field(default_factory=list)
    source_item_id: str | None = None
    reason: str


class ClassifiedSourceItem(BaseModel):
    """A source item (from the skill extraction stage) classified by coverage role.

    Each item is tagged with a coverage_class (required_form, samplable_pool, etc.)
    and may carry a required_form tag if it satisfies a pedagogical form requirement.
    Word-level roles are tracked in word_roles for fine-grained coverage analysis.
    """

    source_item_id: str
    item_type: str
    content: str
    normalized_content: str
    coverage_class: CoverageClass
    required_form: RequiredForm | None = None
    word_roles: list[LedgerWord] = Field(default_factory=list)
    objective_ids: list[str] = Field(default_factory=list)
    mandatory: bool
    notes: list[str] = Field(default_factory=list)


class ObjectiveCell(BaseModel):
    """A single learning objective with its coverage requirements.

    Tracks the minimum/maximum practice counts, required pedagogical forms,
    and acceptable response formats for a single objective (e.g., "decode sh pattern").
    The sufficiency_rule is a human-readable description of what constitutes
    sufficient practice for this objective.
    """

    objective_id: str
    objective_type: ObjectiveType
    display_name: str
    concept: str
    target_pattern: str | None = None
    importance: Literal["essential", "supporting"] = "essential"
    required_forms: list[RequiredForm] = Field(default_factory=list)
    source_item_ids: list[str] = Field(default_factory=list)
    target_words: list[str] = Field(default_factory=list)
    contrast_words: list[str] = Field(default_factory=list)
    irregular_words: list[str] = Field(default_factory=list)
    min_practice_count: int
    max_recommended_count: int
    acceptable_response_formats: list[str] = Field(default_factory=list)
    sufficiency_rule: str


class BlockingGateSpec(BaseModel):
    """Controls which deterministic gates block worksheet publication.

    Each gate checks for a specific extraction artifact or ambiguity:
    - answer_key_gate: blocks if answer-key notation leaks into visible items
    - source_notation_artifact_gate: blocks if (CIRCLE), (UNDERLINE) etc. are visible
    - instruction_option_answer_gate: blocks if instructions/options/answers are conflated
    - capitalization_gate: blocks if ALL CAPS words appear in non-title contexts
    """

    answer_key_gate: bool = True
    source_notation_artifact_gate: bool = True
    instruction_option_answer_gate: bool = True
    capitalization_gate: bool = True


class EvidenceItem(BaseModel):
    """A typed evidence item for objective-coverage validation.

    T6 (the validator) adapts each ActivityItem into EvidenceItem(s), giving the
    validator and judge a clean typed surface without changing ActivityItem/planner/
    renderer schema. This model captures the visible text, practice role, answer key,
    response format, and whether the item is student production (vs. model/given).
    """

    visible_text: str
    practice_role: str
    answer_key_text: str | None = None
    response_format: str
    is_student_production: bool
    objective_ids: list[str] = Field(default_factory=list)


class ObjectiveLedger(BaseModel):
    """The top-level objective-sufficiency ledger for a single worksheet.

    Tracks all objectives, classified source items, blocking rules, and corpus
    metadata. The corpus_version field ensures idempotency: same photo/profile/theme
    + same corpus_version => byte-identical ledger.

    The ledger is built in T2/T3 and consumed by the validator (T6) and judge.
    """

    ledger_version: Literal["objective_sufficiency_v1"] = "objective_sufficiency_v1"
    source_skill_hash: str
    lesson_number: int | None
    corpus_status: Literal["matched", "missing", "not_applicable"]
    corpus_version: str  # REQUIRED (no default) — review addition (idempotency)
    corpus_lesson_id: str | None = None
    primary_pattern: str | None = None
    objectives: list[ObjectiveCell]
    source_items: list[ClassifiedSourceItem]
    blocking_rules: BlockingGateSpec = Field(default_factory=BlockingGateSpec)
    builder_warnings: list[str] = Field(default_factory=list)


# ============================================================================
# Deterministic word-role classifier (T2)
# ============================================================================
#
# classify_word_role() tags each word with a (role, confidence, source) triple.
# Confidence is the load-bearing signal: T6 hard-fails a pattern cell's count
# only on `high`-confidence target_pattern words; `low`-confidence results are
# advisory and never auto-reject. Ambiguity (mixed-VCe, vowel teams, y-as-vowel,
# schwa/multisyllable, pattern-containing irregulars) collapses to `low`.


PatternKind = Literal["vce", "rime"]

_VOWELS = frozenset("aeiou")


class PatternContext(BaseModel):
    """The target-pattern signal + corpus word sets a classifier needs.

    Built by T3 from a `lookup_lesson()` corpus result and a `LiteracySkillModel`,
    then passed per-word to :func:`classify_word_role`. Frozen so it stays a stable,
    hashable, deterministic input (same context → same classification).

    Two pattern kinds are supported:
    - ``"vce"``: a silent-e (CVCe/VCe) pattern keyed on a single ``vowel`` (e.g.
      ``pattern_key="u_e"``, ``vowel="u"``).
    - ``"rime"``: a word-family pattern matched on a set of ``rimes`` / word
      endings (e.g. ``pattern_key="oll"``, ``rimes={"all", "oll", "ull"}``).
    """

    model_config = ConfigDict(frozen=True)

    pattern_key: str = Field(description="Normalized pattern id, e.g. 'u_e' or 'oll'.")
    pattern_kind: PatternKind = Field(description="How to match: VCe vowel vs. rime family.")
    vowel: str | None = Field(
        default=None,
        description="Single target vowel for a 'vce' pattern (e.g. 'u'); None for rimes.",
    )
    rimes: frozenset[str] = Field(
        default_factory=frozenset,
        description="Word-family endings for a 'rime' pattern, e.g. {'all','oll','ull'}.",
    )
    corpus_target_words: frozenset[str] = Field(
        default_factory=frozenset,
        description="Lesson's UFLI target pool (Roll and Read etc.); membership → corpus_exact.",
    )
    irregular_words: frozenset[str] = Field(
        default_factory=frozenset,
        description="Heart/trick/sight words supplied by the lesson; membership → irregular_word.",
    )
    review_words: frozenset[str] = Field(
        default_factory=frozenset,
        description="Optional known prior-lesson decodable words (advisory; not load-bearing).",
    )
    is_contrast_context: bool = Field(
        default=False,
        description="True only when the task deliberately uses non-target words for contrast.",
    )
    corpus_matched: bool = Field(
        default=True,
        description="False on corpus miss / non-UFLI input: caps every result at 'low' confidence.",
    )


# --- normalization ---


def _normalize_word(word: str) -> str:
    """Casefold and strip non-alphabetic edge characters.

    Consistent with skill/extractor.py word handling (lowercase, alpha-only).
    Inner punctuation (rare for single words) is dropped so 'Cute!' -> 'cute'.
    """
    return re.sub(r"[^a-z]", "", word.casefold())


# --- explicit phonics helpers ---


def _strip_silent_e(word: str) -> str:
    """Return the word without a single trailing silent 'e' (>=2 chars remain)."""
    if len(word) >= 3 and word.endswith("e"):
        return word[:-1]
    return word


def _vowel_count(word: str) -> int:
    """Count a/e/i/o/u letters (y excluded — handled separately)."""
    return sum(1 for ch in word if ch in _VOWELS)


def _has_y_as_vowel(word: str) -> bool:
    """True when 'y' is functioning as the syllable's vowel (e.g. 'type', 'gym').

    Heuristic: 'y' appears not at the very start, and once any single trailing
    silent 'e' is removed there is no a/e/i/o/u vowel left to be the nucleus.
    """
    if "y" not in word[1:]:
        return False
    core = _strip_silent_e(word)
    return _vowel_count(core) == 0


def _is_clean_vce(word: str, vowel: str) -> bool:
    """True for a clean single-pattern CVCe/VCe match on `vowel` (e.g. 'cute' for u).

    Requires: ends with <vowel><single consonant>e, exactly one a/e/i/o/u vowel
    in the body (the target vowel — no competing vowel team), no y-as-vowel.
    Rejects mixed-VCe, vowel teams, schwa/multisyllable.
    """
    if len(word) < 4 or not word.endswith("e"):
        return False
    if _has_y_as_vowel(word):
        return False
    # Pattern body up to the silent e: ...<vowel><consonant>
    body = word[:-1]
    if len(body) < 3:
        return False
    nucleus, consonant = body[-2], body[-1]
    if nucleus != vowel or consonant in _VOWELS or consonant == "y":
        return False
    # Exactly one a/e/i/o/u vowel in the body → single, clean pattern (no team).
    return _vowel_count(body) == 1


def _matches_rime(word: str, rimes: frozenset[str]) -> bool:
    """True when the word ends with one of the family rimes (e.g. 'roll' for 'oll')."""
    return any(word.endswith(rime) for rime in rimes)


def _is_ambiguous(word: str, ctx: PatternContext) -> bool:
    """True for words whose role can't be settled safely by a clean rule.

    Covers y-as-vowel (type/gym), vowel teams, and (for VCe lessons) silent-e
    words that aren't a clean single-pattern match on the target vowel.
    """
    if _has_y_as_vowel(word):
        return True
    if ctx.pattern_kind == "vce":
        # A silent-e word that isn't a clean target-vowel CVCe is a mixed/competing
        # VCe (e.g. wrong vowel, or a vowel team before the e) → ambiguous.
        if word.endswith("e") and ctx.vowel is not None and not _is_clean_vce(word, ctx.vowel):
            return True
    return False


def classify_word_role(
    word: str, pattern_ctx: PatternContext
) -> tuple[SourceRole, RoleConfidence, RoleSource]:
    """Classify a word's pedagogical role against the lesson's target pattern.

    Returns ``(role, confidence, source)``. Resolution order (first match wins):

    1. Corpus target-word membership → ``target_pattern`` / ``high`` / ``corpus_exact``.
    2. Supplied irregular/heart word → ``irregular_word`` / ``high`` / ``corpus_exact``.
       (Checked before pattern rules so pattern-containing irregulars like 'use'
       don't get mis-read as the target.)
    3. Genuine ambiguity (y-as-vowel, mixed-VCe, vowel teams) →
       ``ambiguous_review_word`` / ``low`` / ``unknown``.
    4. Clean target-pattern rule match → ``target_pattern`` / ``high`` / ``pattern_rule``.
    5. Clean decodable non-target word → ``contrast_word`` (under contrast framing) or
       ``review_word``, ``high`` / ``pattern_rule`` (we're confident it is NOT the target).

    When ``pattern_ctx.corpus_matched`` is False, every result's confidence is
    capped at ``low`` (graceful degrade — the validator must never hard-fail a
    count it cannot confidently compute).
    """
    normalized = _normalize_word(word)
    role, confidence, source = _resolve_role(normalized, pattern_ctx)
    if not pattern_ctx.corpus_matched:
        confidence = "low"
    return role, confidence, source


def _resolve_role(word: str, ctx: PatternContext) -> tuple[SourceRole, RoleConfidence, RoleSource]:
    """Core role resolution before the corpus-miss confidence cap is applied."""
    # 1. Exact corpus target-word membership — strongest signal.
    if word in ctx.corpus_target_words:
        return "target_pattern", "high", "corpus_exact"

    # 2. Supplied irregular / heart / sight word — beats any visual pattern match.
    if word in ctx.irregular_words:
        return "irregular_word", "high", "corpus_exact"

    # 3. Genuine ambiguity → low, advisory (does not count toward sufficiency).
    if _is_ambiguous(word, ctx):
        return "ambiguous_review_word", "low", "unknown"

    # 4. Clean target-pattern rule match.
    if _matches_target_pattern(word, ctx):
        return "target_pattern", "high", "pattern_rule"

    # 5. A clean decodable word that is clearly NOT the target pattern.
    if _is_clean_decodable(word):
        role: SourceRole = "contrast_word" if ctx.is_contrast_context else "review_word"
        return role, "high", "pattern_rule"

    # Unresolved — cannot classify safely.
    return "ambiguous_review_word", "low", "unknown"


def _matches_target_pattern(word: str, ctx: PatternContext) -> bool:
    """True when the word cleanly instantiates the lesson's target pattern."""
    if ctx.pattern_kind == "vce":
        return ctx.vowel is not None and _is_clean_vce(word, ctx.vowel)
    return _matches_rime(word, ctx.rimes)


def _is_clean_decodable(word: str) -> bool:
    """True for a short, clean, single-vowel decodable word (no y-as-vowel).

    Used to confidently tag non-target words as review/contrast. Deliberately
    conservative: multisyllable / vowel-team / y-as-vowel words fall through to
    low-confidence rather than being asserted as clean review words.
    """
    if not word or _has_y_as_vowel(word):
        return False
    # Exactly one a/e/i/o/u vowel → a single closed/open syllable (e.g. mop, jazz).
    return _vowel_count(word) == 1
