"""Data models for the objective-sufficiency coverage system.

This module defines the ObjectiveLedger schema, which tracks per-objective coverage
for a worksheet against UFLI curriculum standards. The ledger classifies source items
by coverage role (required form, samplable pool, etc.) and tracks word-level roles
with confidence signals to support strict validation.

Schema-only for now; builder logic (T2/T3) will be added in later tasks.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from corpus.ufli.lookup import CorpusLookupResult, lookup_lesson
from skill.schema import LiteracySkillModel, SourceItem
from skill.taxonomy import match_phonics_pattern

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

# Practice-role vocabulary for typed evidence items (see EvidenceItem). Exported
# here so the validator (validate/objective_coverage.py) and the judge-input
# builder (adapt/llm_judge.py) share one source of truth without reaching across
# packages. The string values are the same bare constants the validator already
# uses; this alias just gives them a checked type.
PracticeRole = Literal[
    "student_practice",
    "answer_key",
    "distractor_option",
    "worked_example",
]


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

    ``evidence_item_id`` is a stable, deterministic provenance id (worksheet /
    chunk / item position) populated by ``build_evidence_index``; it lets the
    judge cite a specific item and lets the per-cell judge output (T8) carry
    ``evidence_item_ids``. It is optional/defaulted so hand-built evidence (tests,
    fixtures) stays valid.
    """

    visible_text: str
    practice_role: PracticeRole
    answer_key_text: str | None = None
    response_format: str
    is_student_production: bool
    objective_ids: list[str] = Field(default_factory=list)
    evidence_item_id: str | None = None


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


# ============================================================================
# Deterministic objective-ledger builder (T3)
# ============================================================================
#
# build_objective_ledger() turns a LiteracySkillModel (+ the UFLI corpus, by
# lesson_number) into an ObjectiveLedger: objective cells, classified source
# items, role-tagged words, and sufficiency thresholds. Pure + deterministic —
# same skill model + same corpus_version → byte-identical model_dump_json().

CorpusLookup = Callable[[int], CorpusLookupResult | None]

# Sufficiency priors (research spec §"Compute sufficiency thresholds").
# (min_practice_count, max_recommended_count).
_DECODE_MIN, _DECODE_MAX = 6, 12
_DECODE_MIN_EARLY = 4  # very-early-K / very-short tasks
_ENCODE_MIN, _ENCODE_MAX = 3, 6
_MANIP_MIN, _MANIP_MAX = 1, 1  # counted in coherent chains, not words
_CONNECTED_MIN, _CONNECTED_MAX = 1, 1
_IRREGULAR_MIN, _IRREGULAR_MAX = 2, 7
_CONTRAST_MIN, _CONTRAST_MAX = 1, 1

# Response/format helpers per cell.
_DECODE_FORMATS = ("read_aloud", "circle", "write")
_ENCODE_FORMATS = ("write", "fill_blank")
_MANIP_FORMATS = ("word_chain",)
_CONNECTED_FORMATS = ("read_aloud",)
_IRREGULAR_FORMATS = ("read_aloud", "write")
_CONTRAST_FORMATS = ("sort", "circle")

# Production-implying response formats → an encoding objective is warranted.
_PRODUCTION_RESPONSES = frozenset({"write", "spell", "dictation", "fill_blank", "trace"})

_ARROW_RE = re.compile(r"[→\-]+>?|>")
_VCE_CONCEPT_RE = re.compile(r"\b([aeiou])_e\b")
_RIME_RE = re.compile(r"-([a-z]+)")


def build_objective_ledger(
    skill: LiteracySkillModel,
    corpus_lookup: CorpusLookup = lookup_lesson,
) -> ObjectiveLedger:
    """Build a deterministic objective-sufficiency ledger from a skill model.

    Resolves lesson context from the UFLI corpus (by ``lesson_number`` via
    ``corpus_lookup``), creates objective cells per the deterministic builder
    rules, classifies each typed source item to a coverage class / required
    form, attaches confidence-tagged word roles, and stamps sufficiency
    thresholds. On a corpus miss / non-UFLI input it degrades gracefully:
    ``corpus_status`` is ``"missing"`` / ``"not_applicable"``, ``corpus_version``
    is the ``"no_corpus"`` sentinel, and every word's confidence is capped at
    ``low`` (the classifier does this when ``corpus_matched`` is False).

    Deterministic and stable: two calls on the same input produce byte-identical
    ``model_dump_json()`` output (no time/random, no set-order leakage).
    """
    ctx = _resolve_corpus_context(skill, corpus_lookup)
    pattern_ctx = _build_pattern_context(skill, ctx)

    objectives: list[ObjectiveCell] = []
    source_items: list[ClassifiedSourceItem] = []
    warnings: list[str] = list(ctx.warnings)

    # --- Objective cells (importance + thresholds; ids are stable strings) ---
    decode_cell = _make_decode_cell(skill, pattern_ctx)
    objectives.append(decode_cell)

    encode_cell: ObjectiveCell | None = None
    if _wants_encoding(skill):
        encode_cell = _make_encode_cell(skill, pattern_ctx)
        objectives.append(encode_cell)

    manip_cell: ObjectiveCell | None = None
    if _has_item(skill, ("word_chain", "chain_script")):
        manip_cell = _make_manipulation_cell(skill, pattern_ctx)
        objectives.append(manip_cell)

    irregular_cell: ObjectiveCell | None = None
    sight_item = _first_item(skill, "sight_words")
    corpus_heart = ctx.heart_words
    if sight_item is not None or corpus_heart:
        irregular_cell = _make_irregular_cell(pattern_ctx)
        objectives.append(irregular_cell)

    # Connected-text cell: created if the skill model has a passage OR the corpus
    # supplied decodable text OR sentence items provide connected decodable text.
    has_passage_source = _has_item(skill, ("passage",))
    has_corpus_passage = bool(ctx.cleaned_passage)
    has_sentences = _has_item(skill, ("sentence",))
    connected_cell: ObjectiveCell | None = None
    if has_passage_source or has_corpus_passage or has_sentences:
        connected_cell = _make_connected_cell(pattern_ctx)
        objectives.append(connected_cell)

    # NOTE: no contrast_discrimination cell — the fixtures carry no deliberate
    # contrast/sort task. Such a cell is created only for explicit sort/odd-one-out
    # tasks (none present here); contrast WORDS are still excluded from decode.

    # --- Classify each skill-model source item, dedup against corpus injects ---
    seen_norm: set[str] = set()
    sentence_is_sole_connected = not has_passage_source and not has_corpus_passage
    for idx, item in enumerate(skill.source_items):
        classified = _classify_source_item(
            item,
            idx,
            pattern_ctx,
            decode_cell=decode_cell,
            encode_cell=encode_cell,
            manip_cell=manip_cell,
            irregular_cell=irregular_cell,
            connected_cell=connected_cell,
            sentence_is_sole_connected=sentence_is_sole_connected,
        )
        source_items.append(classified)
        seen_norm.add(classified.normalized_content)

    # --- Corpus enrichment (mirrors skill/extractor::_enrich_from_corpus) ---
    if ctx.cleaned_passage and connected_cell is not None:
        passage_norm = _normalize_content(ctx.cleaned_passage)
        if passage_norm not in seen_norm:
            ci = _make_corpus_passage_item(ctx.cleaned_passage, connected_cell)
            source_items.append(ci)
            seen_norm.add(ci.normalized_content)
            connected_cell.source_item_ids.append(ci.source_item_id)

    if ctx.roll_and_read and ctx.roll_and_read_words:
        pool_norm = _normalize_content(ctx.roll_and_read)
        if pool_norm not in seen_norm:
            ci = _make_roll_and_read_item(
                ctx.roll_and_read, ctx.roll_and_read_words, decode_cell, pattern_ctx
            )
            source_items.append(ci)
            seen_norm.add(ci.normalized_content)
            decode_cell.source_item_ids.append(ci.source_item_id)

    # Adjust the decode lower bound for very-early / sparse-target lessons.
    _apply_early_decode_floor(skill, decode_cell)

    return ObjectiveLedger(
        source_skill_hash=_hash_skill(skill),
        lesson_number=skill.lesson_number,
        corpus_status=ctx.status,
        corpus_version=ctx.corpus_version,
        corpus_lesson_id=ctx.lesson_id,
        primary_pattern=pattern_ctx.pattern_key or None,
        objectives=objectives,
        source_items=source_items,
        builder_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Corpus context resolution
# ---------------------------------------------------------------------------


class _CorpusContext(BaseModel):
    """Resolved lesson context (corpus-or-fallback) the builder threads through."""

    model_config = ConfigDict(frozen=True)

    status: Literal["matched", "missing", "not_applicable"]
    corpus_version: str
    lesson_id: str | None
    concept: str | None
    cleaned_passage: str
    roll_and_read: str
    roll_and_read_words: tuple[str, ...]
    heart_words: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return self.status == "matched"


def _resolve_corpus_context(skill: LiteracySkillModel, lookup: CorpusLookup) -> _CorpusContext:
    """Resolve lesson context from the corpus, else fall back to skill fields."""
    if skill.lesson_number is None:
        return _CorpusContext(
            status="not_applicable",
            corpus_version="no_corpus",
            lesson_id=None,
            concept=None,
            cleaned_passage="",
            roll_and_read="",
            roll_and_read_words=(),
            heart_words=(),
            warnings=("no lesson_number; corpus lookup not applicable",),
        )

    result = lookup(skill.lesson_number)
    if result is None:
        return _CorpusContext(
            status="missing",
            corpus_version="no_corpus",
            lesson_id=None,
            concept=None,
            cleaned_passage="",
            roll_and_read="",
            roll_and_read_words=(),
            heart_words=(),
            warnings=(f"corpus miss for lesson {skill.lesson_number}; degraded to skill fields",),
        )

    cleaned_passage = _clean_corpus_passage(result.decodable_text)
    roll_and_read = result.additional_text.strip()
    rr_words = _extract_pool_words(result.additional_text)
    return _CorpusContext(
        status="matched",
        corpus_version=_hash_corpus(result),
        lesson_id=result.lesson_id,
        concept=result.concept,
        cleaned_passage=cleaned_passage,
        roll_and_read=roll_and_read,
        roll_and_read_words=rr_words,
        heart_words=(),  # corpus heart words not separately modeled here
        warnings=(),
    )


# ---------------------------------------------------------------------------
# PatternContext derivation
# ---------------------------------------------------------------------------


def _build_pattern_context(skill: LiteracySkillModel, ctx: _CorpusContext) -> PatternContext:
    """Derive the (T2) PatternContext once from corpus concept + skill fields.

    Pattern key/kind come from the corpus concept when matched, else the skill's
    ``specific_skill``. The corpus Roll-and-Read pool + the skill's word_list
    target words seed ``corpus_target_words`` (membership → corpus_exact/high).
    Sight words seed ``irregular_words``.
    """
    concept_source = ctx.concept if ctx.matched and ctx.concept else skill.specific_skill
    kind, vowel, rimes, key = _derive_pattern(concept_source)

    # ONLY the curated corpus Roll-and-Read pool seeds high-confidence membership.
    # The skill-model word_list mixes in deliberate contrast/review words (e.g.
    # 'mop'/'jazz' in the -oll lesson) which must NOT count as target_pattern;
    # those words still classify correctly via the pattern rule (→ review/contrast).
    corpus_targets: set[str] = set(ctx.roll_and_read_words)

    irregulars: set[str] = set()
    sight = _first_item(skill, "sight_words")
    if sight is not None:
        for w in _split_words(sight.content):
            irregulars.add(w)
    irregulars.update(ctx.heart_words)

    # Irregulars must never sit in the target pool (they win role resolution
    # anyway, but keep the sets disjoint so the decode numerator stays clean).
    corpus_targets -= irregulars

    return PatternContext(
        pattern_key=key,
        pattern_kind=kind,
        vowel=vowel,
        rimes=frozenset(rimes),
        corpus_target_words=frozenset(corpus_targets),
        irregular_words=frozenset(irregulars),
        review_words=frozenset(),
        is_contrast_context=False,
        corpus_matched=ctx.matched,
    )


def _derive_pattern(concept: str) -> tuple[PatternKind, str | None, set[str], str]:
    """Return (pattern_kind, vowel, rimes, pattern_key) for a concept descriptor.

    - ``"u_e /ū/"`` → vce, vowel 'u', key 'u_e'.
    - ``"-all, -oll, -ull"`` → rime, rimes {all,oll,ull}, key 'all_oll_ull'.
    - ``"VCe review 2"`` / ``"cvce"`` → vce, vowel None (mixed; corpus pool drives
      membership), key derived from the concept text.
    """
    low = concept.lower()

    rimes = sorted(set(_RIME_RE.findall(low)))
    if rimes:
        return "rime", None, set(rimes), "_".join(rimes)

    m = _VCE_CONCEPT_RE.search(low)
    if m:
        vowel = m.group(1)
        return "vce", vowel, set(), f"{vowel}_e"

    # Mixed VCe / generic cvce: no single target vowel — rely on the corpus pool.
    if "vce" in low or "cvce" in low or "silent" in low or "magic" in low:
        return "vce", None, set(), _normalize_key(low)

    # Last resort: ask the taxonomy; treat cvce family as vowel-less vce, else
    # fall back to a vowel-less vce keyed on the raw concept (corpus pool drives).
    matched = match_phonics_pattern(concept)
    if matched == "cvce":
        return "vce", None, set(), _normalize_key(low)
    return "vce", None, set(), _normalize_key(low)


def _normalize_key(text: str) -> str:
    """Stable slug for a pattern key (lowercase, alnum/underscore only)."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "pattern"


# ---------------------------------------------------------------------------
# Objective-cell factories
# ---------------------------------------------------------------------------


def _make_decode_cell(skill: LiteracySkillModel, ctx: PatternContext) -> ObjectiveCell:
    return ObjectiveCell(
        objective_id="obj_decode",
        objective_type="decode_target_pattern",
        display_name=f"Decode {ctx.pattern_key} words",
        concept=skill.specific_skill,
        target_pattern=ctx.pattern_key or None,
        importance="essential",
        required_forms=[],
        min_practice_count=_DECODE_MIN,
        max_recommended_count=_DECODE_MAX,
        acceptable_response_formats=list(_DECODE_FORMATS),
        sufficiency_rule=(
            f"≥{_DECODE_MIN} distinct high-confidence {ctx.pattern_key or 'target'}-pattern "
            f"words read/decoded (comfort upper bound {_DECODE_MAX})"
        ),
    )


def _make_encode_cell(skill: LiteracySkillModel, ctx: PatternContext) -> ObjectiveCell:
    return ObjectiveCell(
        objective_id="obj_encode",
        objective_type="encode_target_pattern",
        display_name=f"Spell {ctx.pattern_key} words",
        concept=skill.specific_skill,
        target_pattern=ctx.pattern_key or None,
        importance="essential",
        required_forms=["encoding_or_spelling"],
        min_practice_count=_ENCODE_MIN,
        max_recommended_count=_ENCODE_MAX,
        acceptable_response_formats=list(_ENCODE_FORMATS),
        sufficiency_rule=(
            f"≥{_ENCODE_MIN} target-pattern words written/spelled "
            f"(comfort upper bound {_ENCODE_MAX})"
        ),
    )


def _manipulation_chain_shape(skill: LiteracySkillModel) -> str:
    """ "single_hop" iff this is a suffix lesson whose chain source items are
    ALL 2-word pairs (no chain has a second hop to build through) — e.g.
    lesson 101's "quick → quickly". Any 3+-word chain, or any non-suffix
    lesson, is "multi_hop" (the classic build/change chain shape). Descriptive
    only: consumed by the sufficiency_rule text the judge reads, never by the
    deterministic evaluator.

    Reuses the canonical suffix-chain parser (adapt/engine.py) rather than
    re-deriving hop count from a raw arrow split, so this agrees with what
    the deterministic engine actually renders (and doesn't miscount hyphens
    inside a source item, e.g. a stray "-ly" in chain_script prose, as an
    arrow — `_ARROW_RE` matches bare hyphens too)."""
    from adapt.engine import _parse_suffix_chain_steps
    from skill.taxonomy import is_suffix_skill, suffixes_for_skill

    if not is_suffix_skill(skill.specific_skill):
        return "multi_hop"
    suffixes = suffixes_for_skill(skill.specific_skill)
    longest = 0
    for item in skill.source_items:
        if item.item_type not in ("word_chain", "chain_script"):
            continue
        steps = _parse_suffix_chain_steps([item.content], suffixes)
        longest = max(longest, len(steps))
    return "single_hop" if 0 < longest <= 1 else "multi_hop"


def _make_manipulation_cell(skill: LiteracySkillModel, ctx: PatternContext) -> ObjectiveCell:
    if _manipulation_chain_shape(skill) == "single_hop":
        rule = (
            "≥2 add-the-ending transformations (base + suffix → new word); this "
            "suffix forms no multi-step chain, so independent pairs ARE this "
            "lesson's manipulation form"
        )
    else:
        rule = "≥1 coherent build/change chain (count steps, not words)"
    return ObjectiveCell(
        objective_id="obj_manipulation",
        objective_type="phoneme_grapheme_manipulation",
        display_name="Build and change words (word chain)",
        concept="phoneme-grapheme manipulation",
        target_pattern=ctx.pattern_key or None,
        importance="essential",
        required_forms=["word_chain", "chain_script"],
        min_practice_count=_MANIP_MIN,
        max_recommended_count=_MANIP_MAX,
        acceptable_response_formats=list(_MANIP_FORMATS),
        sufficiency_rule=rule,
    )


def _make_connected_cell(ctx: PatternContext) -> ObjectiveCell:
    return ObjectiveCell(
        objective_id="obj_connected_text",
        objective_type="connected_text_fluency",
        display_name="Read connected decodable text",
        concept="connected-text fluency",
        target_pattern=ctx.pattern_key or None,
        importance="essential",
        required_forms=["decodable_passage"],
        min_practice_count=_CONNECTED_MIN,
        max_recommended_count=_CONNECTED_MAX,
        acceptable_response_formats=list(_CONNECTED_FORMATS),
        sufficiency_rule="≥1 decodable passage (or 2-4 connected sentences); 1 page chunk",
    )


def _make_irregular_cell(ctx: PatternContext) -> ObjectiveCell:
    return ObjectiveCell(
        objective_id="obj_irregular",
        objective_type="irregular_word_reading",
        display_name="Read irregular / heart words",
        concept="irregular high-frequency words",
        target_pattern=None,
        importance="essential",
        required_forms=["irregular_word_practice"],
        min_practice_count=_IRREGULAR_MIN,
        max_recommended_count=_IRREGULAR_MAX,
        acceptable_response_formats=list(_IRREGULAR_FORMATS),
        sufficiency_rule=(
            f"≥{_IRREGULAR_MIN} irregular/heart words read (comfort upper bound {_IRREGULAR_MAX})"
        ),
    )


def _apply_early_decode_floor(skill: LiteracySkillModel, decode_cell: ObjectiveCell) -> None:
    """Lower the decode floor to 4 for very-early-K / sparse-target lessons."""
    distinct_targets = len(decode_cell.target_words)
    is_early = skill.lesson_number is not None and skill.lesson_number <= 30
    if is_early or distinct_targets < 4:
        decode_cell.min_practice_count = _DECODE_MIN_EARLY
        decode_cell.sufficiency_rule = (
            f"≥{_DECODE_MIN_EARLY} target-pattern words (early/short-task floor; "
            f"comfort upper bound {decode_cell.max_recommended_count})"
        )


# ---------------------------------------------------------------------------
# Source-item classification
# ---------------------------------------------------------------------------


def _classify_source_item(
    item: SourceItem,
    idx: int,
    ctx: PatternContext,
    *,
    decode_cell: ObjectiveCell,
    encode_cell: ObjectiveCell | None,
    manip_cell: ObjectiveCell | None,
    irregular_cell: ObjectiveCell | None,
    connected_cell: ObjectiveCell | None,
    sentence_is_sole_connected: bool,
) -> ClassifiedSourceItem:
    """Classify one skill-model source item; attach role-tagged words + cell links."""
    item_id = f"src_{idx}_{item.item_type}"
    normalized = _normalize_content(item.content)
    coverage_class: CoverageClass
    required_form: RequiredForm | None
    mandatory: bool
    objective_ids: list[str] = []
    notes: list[str] = []

    if item.item_type in ("word_chain", "chain_script"):
        coverage_class = "required_form"
        required_form = "word_chain" if item.item_type == "word_chain" else "chain_script"
        mandatory = True
        if manip_cell is not None:
            objective_ids.append(manip_cell.objective_id)
            manip_cell.source_item_ids.append(item_id)

    elif item.item_type == "passage":
        coverage_class = "required_form"
        required_form = "decodable_passage"
        mandatory = True
        if connected_cell is not None:
            objective_ids.append(connected_cell.objective_id)
            connected_cell.source_item_ids.append(item_id)

    elif item.item_type == "sight_words":
        coverage_class = "required_form"
        required_form = "irregular_word_practice"
        mandatory = True
        if irregular_cell is not None:
            objective_ids.append(irregular_cell.objective_id)
            irregular_cell.source_item_ids.append(item_id)

    elif item.item_type in ("word_list", "roll_and_read"):
        coverage_class = "samplable_pool"
        required_form = None
        mandatory = False
        objective_ids.append(decode_cell.objective_id)
        decode_cell.source_item_ids.append(item_id)
        if encode_cell is not None:
            objective_ids.append(encode_cell.objective_id)

    elif item.item_type == "sentence":
        # A sentence is required connected-text evidence only when it is the sole
        # connected-text form; otherwise it is samplable connected-text evidence.
        coverage_class = "required_form" if sentence_is_sole_connected else "samplable_pool"
        required_form = "decodable_sentence" if sentence_is_sole_connected else None
        mandatory = sentence_is_sole_connected
        if connected_cell is not None:
            objective_ids.append(connected_cell.objective_id)
            connected_cell.source_item_ids.append(item_id)

    else:
        coverage_class = "supporting_evidence"
        required_form = None
        mandatory = False
        notes.append("establishes lesson concept/title/directions only")

    words = _classify_words_for_item(
        item.content,
        ctx,
        item_id,
        objective_ids,
        decode_cell=decode_cell,
        encode_cell=encode_cell,
        irregular_cell=irregular_cell,
        is_sight=item.item_type == "sight_words",
    )

    return ClassifiedSourceItem(
        source_item_id=item_id,
        item_type=item.item_type,
        content=item.content,
        normalized_content=normalized,
        coverage_class=coverage_class,
        required_form=required_form,
        word_roles=words,
        objective_ids=objective_ids,
        mandatory=mandatory,
        notes=notes,
    )


def _make_corpus_passage_item(passage: str, connected_cell: ObjectiveCell) -> ClassifiedSourceItem:
    """A required-form decodable_passage item synthesized from corpus decodable_text."""
    item_id = "src_corpus_passage"
    return ClassifiedSourceItem(
        source_item_id=item_id,
        item_type="passage",
        content=passage,
        normalized_content=_normalize_content(passage),
        coverage_class="required_form",
        required_form="decodable_passage",
        word_roles=[],
        objective_ids=[connected_cell.objective_id],
        mandatory=True,
        notes=["source: corpus decodable_text"],
    )


def _make_roll_and_read_item(
    pool: str,
    pool_words: tuple[str, ...],
    decode_cell: ObjectiveCell,
    ctx: PatternContext,
) -> ClassifiedSourceItem:
    """A samplable_pool item from the corpus Roll-and-Read word list.

    Its words feed the decode cell's high-confidence target list (corpus_exact).
    """
    item_id = "src_corpus_roll_and_read"
    words: list[LedgerWord] = []
    for w in pool_words:
        role, conf, src = classify_word_role(w, ctx)
        lw = LedgerWord(
            text=w,
            normalized=_normalize_word(w),
            role=role,
            role_confidence=conf,
            role_source=src,
            objective_ids=[decode_cell.objective_id],
            source_item_id=item_id,
            reason=f"Roll-and-Read pool word classified as {role} ({conf})",
        )
        words.append(lw)
        _route_word_to_cell(lw, decode_cell=decode_cell, encode_cell=None, irregular_cell=None)
    return ClassifiedSourceItem(
        source_item_id=item_id,
        item_type="roll_and_read",
        content=pool,
        normalized_content=_normalize_content(pool),
        coverage_class="samplable_pool",
        required_form=None,
        word_roles=words,
        objective_ids=[decode_cell.objective_id],
        mandatory=False,
        notes=["source: corpus additional_text (Roll and Read)"],
    )


# ---------------------------------------------------------------------------
# Word classification + routing
# ---------------------------------------------------------------------------


def _classify_words_for_item(
    content: str,
    ctx: PatternContext,
    item_id: str,
    objective_ids: list[str],
    *,
    decode_cell: ObjectiveCell,
    encode_cell: ObjectiveCell | None,
    irregular_cell: ObjectiveCell | None,
    is_sight: bool,
) -> list[LedgerWord]:
    """Classify each word in an item and route it to the right objective cell list."""
    words: list[LedgerWord] = []
    for w in _split_words(content):
        if is_sight:
            # Sight-word items are irregular by construction (validator-load-bearing).
            role: SourceRole = "irregular_word"
            conf: RoleConfidence = "high" if ctx.corpus_matched else "low"
            src: RoleSource = "corpus_exact"
        else:
            role, conf, src = classify_word_role(w, ctx)
        lw = LedgerWord(
            text=w,
            normalized=_normalize_word(w),
            role=role,
            role_confidence=conf,
            role_source=src,
            objective_ids=list(objective_ids),
            source_item_id=item_id,
            reason=f"{role} ({conf}) via {src}",
        )
        words.append(lw)
        _route_word_to_cell(
            lw, decode_cell=decode_cell, encode_cell=encode_cell, irregular_cell=irregular_cell
        )
    return words


def _route_word_to_cell(
    lw: LedgerWord,
    *,
    decode_cell: ObjectiveCell,
    encode_cell: ObjectiveCell | None,
    irregular_cell: ObjectiveCell | None,
) -> None:
    """Append a word to the correct cell list per its role (dedup, order-stable).

    Only ``target_pattern``-role words enter the decode (and encode) numerator;
    contrast words go to ``contrast_words``; irregulars to the irregular cell.
    """
    norm = lw.normalized
    if lw.role == "target_pattern":
        if norm not in decode_cell.target_words:
            decode_cell.target_words.append(norm)
        if encode_cell is not None and norm not in encode_cell.target_words:
            encode_cell.target_words.append(norm)
    elif lw.role == "contrast_word":
        if norm not in decode_cell.contrast_words:
            decode_cell.contrast_words.append(norm)
    elif lw.role == "irregular_word":
        if irregular_cell is not None and norm not in irregular_cell.irregular_words:
            irregular_cell.irregular_words.append(norm)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _wants_encoding(skill: LiteracySkillModel) -> bool:
    """True when source formats imply written production (→ encoding objective)."""
    return any(r.lower() in _PRODUCTION_RESPONSES for r in skill.response_types)


def _has_item(skill: LiteracySkillModel, types: tuple[str, ...]) -> bool:
    return any(si.item_type in types for si in skill.source_items)


def _first_item(skill: LiteracySkillModel, item_type: str) -> SourceItem | None:
    return next((si for si in skill.source_items if si.item_type == item_type), None)


def _split_words(text: str) -> list[str]:
    """Split a region into normalized words, order-stable and de-duplicated.

    Drops arrows/markers/numbering; keeps alphabetic tokens only.
    """
    cleaned = text.replace("*", " ").replace("♥", " ").replace("❤", " ")
    cleaned = _ARROW_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)  # drop [spelling]/[reading] tags
    cleaned = re.sub(r"\b\d+\.", " ", cleaned)  # drop list numbering "1."
    seen: set[str] = set()
    out: list[str] = []
    for tok in re.split(r"[^A-Za-z]+", cleaned):
        norm = _normalize_word(tok)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _extract_pool_words(additional_text: str) -> tuple[str, ...]:
    """Extract Roll-and-Read pool words from corpus additional_text, order-stable.

    Skips the 'Roll and Read' / 'Lesson NN:' headers and copyright footer.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in additional_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("roll and read") or low.startswith("lesson") or low.startswith("©"):
            continue
        # Pool lines are single words; guard against any stray multi-token line.
        for tok in re.split(r"[^A-Za-z]+", line):
            norm = _normalize_word(tok)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(norm)
    return tuple(out)


def _normalize_content(text: str) -> str:
    """Lowercase + collapse whitespace for stable dedup of item content."""
    return re.sub(r"\s+", " ", text.strip().lower())


# Corpus-passage cleaning — mirrors skill/extractor::_clean_corpus_passage so the
# adapt stage stays self-contained (no cross-stage import) and deterministic.
_COPYRIGHT_RE = re.compile(r"©\s*\d{4}.*?Institute\s*", re.IGNORECASE)
_LESSON_HEADER_RE = re.compile(r"Lesson\s+\d+.*?\n", re.IGNORECASE)
_ILLUSTRATE_RE = re.compile(r"Illustrate the story here:?\s*", re.IGNORECASE)


def _clean_corpus_passage(text: str) -> str:
    """Strip corpus boilerplate from a decodable passage, keeping title + narrative."""
    cleaned = text.strip()
    cleaned = _COPYRIGHT_RE.sub("", cleaned)
    cleaned = _LESSON_HEADER_RE.sub("", cleaned)
    cleaned = _ILLUSTRATE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    words = cleaned.split()
    if len(words) > 200:
        cleaned = " ".join(words[:200]) + "..."
    return cleaned


def _hash_skill(skill: LiteracySkillModel) -> str:
    """Order-stable sha256 of the input skill model."""
    payload = skill.model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_corpus(result: CorpusLookupResult) -> str:
    """Stable sha256 over the corpus metadata actually used."""
    payload = "\x1f".join(
        (
            result.concept,
            result.decodable_text,
            result.additional_text,
            result.home_practice_text,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
