"""Package-level, role/visibility-aware objective-coverage validator (T6).

This module is the single canonical home for two things:

1. ``build_evidence_index`` — converts the whole, post-``section_cap`` package of
   adapted worksheets into a flat, typed ``list[EvidenceItem]``. Visibility is
   derived ONCE here, from each item's ``response_format`` + which field a word
   lives in: the student-facing ``content`` (and the *correct* selection answer)
   is practice; distractor options and answer keys are NOT. "Presence ≠ practice"
   is made structural on a typed surface that the judge-input builder also consumes.

2. ``evaluate_objective_coverage`` — aggregates that evidence across the whole
   package per ledger objective cell and produces a deterministic, tri-state
   ``ObjectiveCoverageResult``:

   - ``"fail"``  (drives REJECT) — an essential cell has a *high-confidence*
     shortfall, is missing a required form, is a pattern cell satisfied only by
     contrast/review/irregular roles, or a package upper bound is breached.
   - ``"needs_verification"`` (drives ABSTAIN) — no hard failure, but ≥1 essential
     cell has ZERO distinct high-confidence practice (only advisory low-confidence
     / corpus-miss evidence). Abstain is safer than a false reject.
   - ``"pass"`` otherwise.

Both functions operate on the WHOLE package so objectives split across mini-
worksheets aggregate correctly. Pure + deterministic: no time, no randomness, no
input mutation; stable ordering throughout so two runs on the same input produce
byte-identical ``model_dump_json()``.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from adapt.objective_ledger import (
    EvidenceItem,
    ObjectiveCell,
    ObjectiveLedger,
    PatternContext,
    classify_word_role,
)
from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel

# ============================================================================ #
# Package upper bounds (deterministic; named constants; priors tunable in T11)
# ============================================================================ #
#
# Grounded in existing house values: per-grade chunk caps + TIME_ESTIMATE_MINUTES
# (adapt/rules.py), the dense-text rule (content > 100 words) and per-chunk time
# limit from validate/adhd_compliance.py, and MAX_SECTIONS_PER_WORKSHEET. These
# guard the PACKAGE total; per-worksheet section_cap already guards each page.

PACKAGE_MAX_TOTAL_MINUTES = 30
PACKAGE_MAX_TOTAL_ITEMS = 40
PACKAGE_MAX_DENSE_TEXT_BLOCKS = 1
PACKAGE_MAX_OBJECTIVES_PER_WORKSHEET = 4

# An item is a "dense text block" when its content exceeds this many words
# (mirrors validate/adhd_compliance.py::Check 5).
_DENSE_TEXT_WORD_LIMIT = 100


# ============================================================================ #
# Result schema
# ============================================================================ #


class ObjectiveCellResult(BaseModel):
    """Per-objective-cell coverage outcome, aggregated across the package."""

    objective_id: str
    importance: Literal["essential", "supporting"]
    status: Literal["pass", "fail", "needs_verification"]
    distinct_high_confidence_count: int
    min_practice_count: int
    advisory_low_confidence_count: int
    required_forms_present: bool
    missing_required_forms: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PackageBoundResult(BaseModel):
    """Deterministic ADHD-safety upper bounds on the whole package total."""

    passed: bool
    total_estimated_minutes: int
    total_item_count: int
    dense_text_block_count: int
    max_objectives_in_a_worksheet: int
    breaches: list[str] = Field(default_factory=list)


class ObjectiveCoverageResult(BaseModel):
    """Tri-state package-level objective-sufficiency result."""

    definition: Literal["objective_sufficiency_v1"] = "objective_sufficiency_v1"
    status: Literal["pass", "fail", "needs_verification"]
    passed: bool  # passed == (status == "pass")
    objective_results: list[ObjectiveCellResult]
    package_bounds: PackageBoundResult
    role_counts: dict[str, int] = Field(default_factory=dict)
    advisory_notes: list[str] = Field(default_factory=list)


# ============================================================================ #
# Practice roles + visibility (the crux)
# ============================================================================ #

# Production formats: written student output (encode/sentence-writing need these).
_PRODUCTION_FORMATS = frozenset({"write", "fill_blank", "trace", "sound_box", "spell", "dictation"})
# Recognition / reading formats: student identifies or reads (not production).
_RECOGNITION_FORMATS = frozenset({"read_aloud", "circle", "match", "verbal"})
# Selection formats where the CORRECT answer is the practiced target, and the
# WRONG options are distractors that must not count.
_SELECTION_FORMATS = frozenset({"circle", "match", "fill_blank"})

PRACTICE_STUDENT = "student_practice"
PRACTICE_KEY = "answer_key"
PRACTICE_DISTRACTOR = "distractor_option"
PRACTICE_WORKED_EXAMPLE = "worked_example"

_ARROW_RE = re.compile(r"[→\-]+>?|>")
_WORD_RE = re.compile(r"[A-Za-z]+")


def _normalize(word: str) -> str:
    """Casefold + strip non-alphabetic chars (matches the ledger normalizer)."""
    return re.sub(r"[^a-z]", "", word.casefold())


def _words(text: str) -> list[str]:
    """Ordered, de-duplicated normalized word tokens from a text surface."""
    cleaned = _ARROW_RE.sub(" ", text)
    seen: set[str] = set()
    out: list[str] = []
    for tok in _WORD_RE.findall(cleaned):
        norm = _normalize(tok)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _is_production(response_format: str) -> bool:
    """True for written-production formats (encode / spelling / sentence-writing)."""
    return response_format in _PRODUCTION_FORMATS


# ============================================================================ #
# Ledger word-role index (authoritative confidence from T2/T3)
# ============================================================================ #


class _LedgerIndex:
    """Resolves a practiced word's (role, confidence) against the ledger.

    Confidence is the load-bearing signal. The authoritative source is the
    per-word role data the builder already attached to the ledger source items
    (``LedgerWord.role`` / ``role_confidence``). For a practiced word that does
    not appear in that index we re-classify against a ``PatternContext``
    reconstructed from the ledger so the answer is still deterministic and
    confidence-capped on a corpus miss.
    """

    def __init__(self, ledger: ObjectiveLedger) -> None:
        # word -> best (role, confidence) seen in the ledger word-role data.
        self._roles: dict[str, tuple[str, str]] = {}
        for src in ledger.source_items:
            for lw in src.word_roles:
                norm = lw.normalized or _normalize(lw.text)
                if not norm:
                    continue
                self._record(norm, lw.role, lw.role_confidence)
        self._ctx = _reconstruct_pattern_context(ledger)

    def _record(self, norm: str, role: str, confidence: str) -> None:
        prior = self._roles.get(norm)
        if prior is None:
            self._roles[norm] = (role, confidence)
            return
        # Prefer a high-confidence target_pattern reading over a weaker one so a
        # word seen high-confidence anywhere counts (distinctness is per-word).
        prior_score = _role_score(prior[0], prior[1])
        new_score = _role_score(role, confidence)
        if new_score > prior_score:
            self._roles[norm] = (role, confidence)

    def resolve(self, word: str) -> tuple[str, str]:
        """Return (role, confidence) for a normalized practiced word."""
        norm = _normalize(word)
        if norm in self._roles:
            return self._roles[norm]
        role, confidence, _ = classify_word_role(norm, self._ctx)
        return role, confidence


def _role_score(role: str, confidence: str) -> int:
    """Rank a (role, confidence) so the strongest target signal wins de-dup."""
    if role == "target_pattern":
        return 3 if confidence == "high" else 2
    if role == "irregular_word":
        return 1
    return 0


def _reconstruct_pattern_context(ledger: ObjectiveLedger) -> PatternContext:
    """Rebuild a (T2) PatternContext from the ledger for fallback classification.

    Derives the pattern kind/vowel/rimes from ``primary_pattern`` and seeds the
    high-confidence target pool + irregulars from the objective cells. On a corpus
    miss (``corpus_status != "matched"``) every fallback result is capped to low.
    """
    key = ledger.primary_pattern or ""
    kind, vowel, rimes = _derive_pattern_shape(key)

    targets: set[str] = set()
    irregulars: set[str] = set()
    for cell in ledger.objectives:
        if cell.objective_type in ("decode_target_pattern", "encode_target_pattern"):
            targets.update(_normalize(w) for w in cell.target_words)
        if cell.objective_type == "irregular_word_reading":
            irregulars.update(_normalize(w) for w in cell.irregular_words)

    return PatternContext(
        pattern_key=key or "pattern",
        pattern_kind=kind,
        vowel=vowel,
        rimes=frozenset(rimes),
        corpus_target_words=frozenset(targets),
        irregular_words=frozenset(irregulars),
        corpus_matched=ledger.corpus_status == "matched",
    )


_VCE_KEY_RE = re.compile(r"^([aeiou])_e$")
_RIME_TOKEN_RE = re.compile(r"[a-z]{2,}")


def _derive_pattern_shape(key: str) -> tuple[Literal["vce", "rime"], str | None, set[str]]:
    """Map a ledger ``primary_pattern`` key to (kind, vowel, rimes).

    ``"u_e"`` → vce/'u'; ``"all_oll_ull"`` → rime/{all,oll,ull}; mixed/unknown
    (e.g. ``"vce_review_2"``) → vowel-less vce (the target pool drives membership).
    """
    low = key.lower()
    m = _VCE_KEY_RE.match(low)
    if m:
        return "vce", m.group(1), set()
    # Rime keys look like 'all_oll_ull' — alpha tokens, no single-vowel VCe match.
    tokens = [t for t in _RIME_TOKEN_RE.findall(low) if t not in ("vce", "cvce", "review")]
    if tokens and all(len(t) <= 4 for t in tokens) and "_" in low:
        # Heuristic: short alpha tokens joined by underscore → rime family.
        rimes = {t for t in tokens if any(v in t for v in "aeiou")}
        if rimes:
            return "rime", None, rimes
    return "vce", None, set()


# ============================================================================ #
# build_evidence_index
# ============================================================================ #


def build_evidence_index(
    worksheets: list[AdaptedActivityModel],
    ledger: ObjectiveLedger,
) -> list[EvidenceItem]:
    """Convert the whole package of adapted worksheets into typed evidence items.

    For each ``ActivityItem`` we emit one or more ``EvidenceItem``s, deriving
    visibility once:

    - the item ``content`` is student practice (what the child reads/writes) →
      ``practice_role="student_practice"``;
    - for selection formats (circle/match/fill_blank with options) the *correct*
      ``answer`` is what the child identifies → emitted as practice too, while the
      WRONG options are emitted as ``distractor_option`` (never counted);
    - a non-selection item's ``answer`` is a key → emitted as ``answer_key`` with
      ``is_student_production=False`` (never satisfies a cell);
    - a teacher worked-example surface → ``worked_example`` /
      ``is_student_production=False`` (never counts).

    ``objective_ids`` on each evidence item lists the ledger cells the practiced
    words exercise (matched against each cell's word lists by role + the item form
    against the cell's acceptable response formats). Pure + order-stable.
    """
    index = _LedgerIndex(ledger)
    out: list[EvidenceItem] = []
    for ws in worksheets:
        for chunk in ws.chunks:
            out.extend(_evidence_for_chunk(chunk, ledger, index))
    return out


def _evidence_for_chunk(
    chunk: ActivityChunk,
    ledger: ObjectiveLedger,
    index: _LedgerIndex,
) -> list[EvidenceItem]:
    out: list[EvidenceItem] = []

    # Teacher worked example → never counts; emitted for transparency / the judge.
    ex = chunk.worked_example
    if ex is not None:
        out.append(
            EvidenceItem(
                visible_text=ex.content,
                practice_role=PRACTICE_WORKED_EXAMPLE,
                response_format=chunk.response_format,
                is_student_production=False,
                objective_ids=[],
            )
        )

    for item in chunk.items:
        out.extend(_evidence_for_item(item, ledger, index))
    return out


def _evidence_for_item(
    item: ActivityItem,
    ledger: ObjectiveLedger,
    index: _LedgerIndex,
) -> list[EvidenceItem]:
    fmt = item.response_format
    is_production = _is_production(fmt)
    out: list[EvidenceItem] = []

    # 1. The item content is always student practice.
    content_words = _words(item.content)
    out.append(
        EvidenceItem(
            visible_text=item.content,
            practice_role=PRACTICE_STUDENT,
            answer_key_text=None,
            response_format=fmt,
            is_student_production=is_production,
            objective_ids=_match_cells(content_words, fmt, ledger, index, practice=True),
        )
    )

    # 2. Selection formats: the CORRECT answer is practice; wrong options are not.
    if fmt in _SELECTION_FORMATS and item.options:
        answer_parts = re.split(r"[,/]", item.answer or "")
        answer_norms = {_normalize(p) for p in answer_parts if _normalize(p)}
        for opt in item.options:
            opt_words = _words(opt)
            opt_norms = set(opt_words)
            is_correct = bool(answer_norms) and opt_norms <= answer_norms and opt_norms
            if is_correct:
                # The child identifies the correct word → counts as practice.
                out.append(
                    EvidenceItem(
                        visible_text=opt,
                        practice_role=PRACTICE_STUDENT,
                        response_format=fmt,
                        is_student_production=is_production,
                        objective_ids=_match_cells(opt_words, fmt, ledger, index, practice=True),
                    )
                )
            else:
                # A distractor option → recorded but never counts.
                out.append(
                    EvidenceItem(
                        visible_text=opt,
                        practice_role=PRACTICE_DISTRACTOR,
                        response_format=fmt,
                        is_student_production=False,
                        objective_ids=[],
                    )
                )
        # The answer field for a selection item is carried only for transparency;
        # it is realized as the correct-option practice above, so no extra key item.
        return out

    # 3. Non-selection items: any answer field is a KEY (never practice).
    if item.answer and item.answer.strip():
        out.append(
            EvidenceItem(
                visible_text="",
                practice_role=PRACTICE_KEY,
                answer_key_text=item.answer,
                response_format=fmt,
                is_student_production=False,
                objective_ids=[],
            )
        )

    return out


def _match_cells(
    words: list[str],
    response_format: str,
    ledger: ObjectiveLedger,
    index: _LedgerIndex,
    *,
    practice: bool,
) -> list[str]:
    """Return ledger cell ids whose word lists + acceptable forms this evidence hits.

    Order-stable (ledger objective order). Only practice surfaces are matched; key
    / distractor surfaces are emitted with empty ``objective_ids`` upstream.
    """
    if not practice or not words:
        return []
    matched: list[str] = []
    for cell in ledger.objectives:
        if _cell_touched(cell, words, response_format, index):
            matched.append(cell.objective_id)
    return matched


def _cell_touched(
    cell: ObjectiveCell,
    words: list[str],
    response_format: str,
    index: _LedgerIndex,
) -> bool:
    """True when at least one practiced word plausibly exercises this cell."""
    if cell.objective_type in ("decode_target_pattern", "encode_target_pattern"):
        targets = {_normalize(w) for w in cell.target_words}
        contrast = {_normalize(w) for w in cell.contrast_words}
        for w in words:
            role, _ = index.resolve(w)
            # Target words count; contrast/review words are tagged too so the
            # evaluator can hard-fail a pattern cell "satisfied" only by them.
            if (
                w in targets
                or w in contrast
                or role
                in (
                    "target_pattern",
                    "contrast_word",
                    "review_word",
                )
            ):
                return True
        return False
    if cell.objective_type == "irregular_word_reading":
        irregulars = {_normalize(w) for w in cell.irregular_words}
        return any(w in irregulars for w in words)
    if cell.objective_type in ("connected_text_fluency", "sentence_reading_or_writing"):
        # Connected text is exercised by multi-word surfaces.
        return len(words) >= 2
    if cell.objective_type == "phoneme_grapheme_manipulation":
        return response_format in ("word_chain",) or _ARROW_RE.search(" ".join(words)) is not None
    if cell.objective_type == "contrast_discrimination":
        contrast = {_normalize(w) for w in cell.contrast_words}
        return any(w in contrast for w in words)
    return False


# ============================================================================ #
# evaluate_objective_coverage
# ============================================================================ #


def evaluate_objective_coverage(
    ledger: ObjectiveLedger,
    evidence: list[EvidenceItem],
    worksheets: list[AdaptedActivityModel] | None = None,
) -> ObjectiveCoverageResult:
    """Aggregate evidence across the whole package and return a tri-state result.

    See module docstring for the tri-state policy. Deterministic: objective
    results are ordered by ledger objective order, role_counts and notes are
    stable, and the chain-completeness check is order-sensitive but pure.

    ``worksheets`` is the same post-``section_cap`` package passed to
    ``build_evidence_index``. It is required for the package-level ADHD upper
    bounds (total minutes, total item count, dense-text blocks, objectives per
    worksheet), which are chunk/worksheet facts not carried on the typed
    ``EvidenceItem`` surface. When omitted, the bound checker reports zero counts
    and passes (objective sufficiency is still evaluated from the evidence alone).
    """
    index = _LedgerIndex(ledger)
    role_counts = _role_counts(evidence)

    objective_results: list[ObjectiveCellResult] = []
    advisory_notes: list[str] = []
    any_hard_fail = False
    any_needs_verification = False

    for cell in ledger.objectives:
        cell_res = _evaluate_cell(cell, evidence, ledger, index)
        objective_results.append(cell_res)
        if cell.importance == "essential":
            if cell_res.status == "fail":
                any_hard_fail = True
            elif cell_res.status == "needs_verification":
                any_needs_verification = True
        advisory_notes.extend(
            f"{cell.objective_id}: {n}" for n in cell_res.notes if "advisory" in n.lower()
        )

    package_bounds = _evaluate_package_bounds(worksheets, ledger, index)
    if not package_bounds.passed:
        any_hard_fail = True

    if any_hard_fail:
        status: Literal["pass", "fail", "needs_verification"] = "fail"
    elif any_needs_verification:
        status = "needs_verification"
    else:
        status = "pass"

    return ObjectiveCoverageResult(
        status=status,
        passed=(status == "pass"),
        objective_results=objective_results,
        package_bounds=package_bounds,
        role_counts=role_counts,
        advisory_notes=advisory_notes,
    )


def _role_counts(evidence: list[EvidenceItem]) -> dict[str, int]:
    """Stable per-practice-role tally for transparency / the judge."""
    counts: dict[str, int] = {}
    for ev in evidence:
        counts[ev.practice_role] = counts.get(ev.practice_role, 0) + 1
    return dict(sorted(counts.items()))


def _evaluate_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
    ledger: ObjectiveLedger,
    index: _LedgerIndex,
) -> ObjectiveCellResult:
    """Evaluate one objective cell against the aggregated package evidence."""
    if cell.objective_type in ("decode_target_pattern", "encode_target_pattern"):
        return _evaluate_pattern_cell(cell, evidence, index)
    if cell.objective_type == "phoneme_grapheme_manipulation":
        return _evaluate_manipulation_cell(cell, evidence, ledger)
    if cell.objective_type == "connected_text_fluency":
        return _evaluate_connected_cell(cell, evidence)
    if cell.objective_type == "irregular_word_reading":
        return _evaluate_irregular_cell(cell, evidence, index)
    # contrast / sentence_reading_or_writing / fallback: count practiced words.
    return _evaluate_generic_cell(cell, evidence)


def _practice_words_for_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
    *,
    require_production: bool = False,
) -> list[str]:
    """All distinct practiced (student) words tagged to this cell, order-stable."""
    seen: set[str] = set()
    out: list[str] = []
    for ev in evidence:
        if ev.practice_role != PRACTICE_STUDENT:
            continue
        if cell.objective_id not in ev.objective_ids:
            continue
        if require_production and not ev.is_student_production:
            continue
        for w in _words(ev.visible_text):
            if w not in seen:
                seen.add(w)
                out.append(w)
    return out


def _evaluate_pattern_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
    index: _LedgerIndex,
) -> ObjectiveCellResult:
    """Decode/encode cell: numerator = distinct HIGH-confidence target_pattern words
    practiced in an acceptable form. Contrast/review/irregular/ambiguous never count.
    Encode requires student production."""
    is_encode = cell.objective_type == "encode_target_pattern"
    targets = {_normalize(w) for w in cell.target_words}
    contrast = {_normalize(w) for w in cell.contrast_words}

    high: set[str] = set()
    low: set[str] = set()
    wrong_role: set[str] = set()  # DELIBERATE contrast words practiced for this cell
    for w in _practice_words_for_cell(cell, evidence, require_production=is_encode):
        role, confidence = index.resolve(w)
        # Only target_pattern words count; a corpus target word is high by defn.
        is_target = w in targets or role == "target_pattern"
        if not is_target:
            # A deliberate contrast word (declared on the cell, or classified as a
            # contrast role) "satisfying" the cell is a real defect → hard fail.
            # Incidental review words in instruction text are NOT (they'd abstain).
            if w in contrast or role == "contrast_word":
                wrong_role.add(w)
            continue
        if confidence == "high" or w in targets:
            high.add(w)
        else:
            low.add(w)

    distinct_high = len(high)
    advisory_low = len(low)
    notes: list[str] = []
    if wrong_role:
        notes.append(
            f"pattern cell 'satisfied' by deliberate contrast words "
            f"({', '.join(sorted(wrong_role))}); these never count toward the "
            f"target-pattern numerator"
        )
    if advisory_low:
        notes.append(
            f"advisory: {advisory_low} distinct low-confidence target word(s) "
            f"({', '.join(sorted(low))}) not counted toward the threshold"
        )

    # Required form: encode needs written production evidence.
    missing_forms: list[str] = []
    required_present = True
    if is_encode and "encoding_or_spelling" in cell.required_forms:
        has_production = any(
            ev.practice_role == PRACTICE_STUDENT
            and ev.is_student_production
            and cell.objective_id in ev.objective_ids
            for ev in evidence
        )
        if not has_production:
            required_present = False
            missing_forms.append("encoding_or_spelling")
            notes.append("required form missing: written production (encoding/spelling)")

    status = _pattern_status(
        distinct_high,
        advisory_low,
        len(wrong_role),
        cell.min_practice_count,
        cell.importance,
        required_present,
    )
    if status == "needs_verification":
        notes.append(
            "essential cell has zero distinct high-confidence practice "
            "(only advisory low-confidence / corpus-miss evidence) → needs_verification"
        )

    return ObjectiveCellResult(
        objective_id=cell.objective_id,
        importance=cell.importance,
        status=status,
        distinct_high_confidence_count=distinct_high,
        min_practice_count=cell.min_practice_count,
        advisory_low_confidence_count=advisory_low,
        required_forms_present=required_present,
        missing_required_forms=missing_forms,
        notes=notes,
    )


def _pattern_status(
    distinct_high: int,
    advisory_low: int,
    wrong_role_count: int,
    min_count: int,
    importance: str,
    required_present: bool,
) -> Literal["pass", "fail", "needs_verification"]:
    """Tri-state status for a pattern cell.

    Hard FAIL (→ REJECT) for an essential cell when: a required form is missing,
    OR there is a high-confidence shortfall (1..min-1 distinct high-conf words),
    OR the cell is "satisfied" only by off-target roles (contrast/review/irregular)
    with zero high-confidence target practice. ABSTAIN (needs_verification) when
    the only signal is advisory low-confidence / corpus-miss evidence.
    """
    if not required_present:
        return "fail" if importance == "essential" else "needs_verification"
    if distinct_high >= min_count:
        return "pass"
    # Below threshold on high-confidence distinct practice.
    if importance != "essential":
        return "pass"  # supporting cells never hard-fail the package
    if distinct_high == 0:
        # A pattern cell practiced only with off-target roles (contrast/review/
        # irregular) is a real defect, not an abstain — hard FAIL.
        if wrong_role_count > 0:
            return "fail"
        # Otherwise zero high-confidence practice with only advisory low-confidence
        # / corpus-miss evidence (or nothing) → ABSTAIN, not a hard reject.
        return "needs_verification"
    # distinct_high in (1 .. min-1): a real high-confidence shortfall → REJECT.
    return "fail"


def _evaluate_manipulation_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
    ledger: ObjectiveLedger,
) -> ObjectiveCellResult:
    """Manipulation (word_chain/chain_script): satisfied ONLY by an authored chain
    preserving the ledger chain's full ordered transformation sequence. An
    incomplete chain (missing early steps) → required-form FAIL."""
    ledger_chains = _ledger_chain_sequences(ledger)
    authored_chains = _authored_chain_sequences(cell, evidence)

    notes: list[str] = []
    required_present: bool
    missing_forms: list[str] = []

    if not ledger_chains:
        # No canonical chain to compare against — cannot deterministically verify.
        # Pass only if SOME authored chain exists; else abstain.
        required_present = bool(authored_chains)
    else:
        required_present = any(
            _chain_covers(authored, ledger_chain)
            for ledger_chain in ledger_chains
            for authored in authored_chains
        )
        if not required_present:
            missing_forms.append("word_chain")
            if authored_chains:
                notes.append(
                    "authored chain is incomplete (missing early transformation steps "
                    "vs. the ledger chain) → required-form fail"
                )
            else:
                notes.append("no authored build/change chain present → required-form fail")

    if required_present:
        status: Literal["pass", "fail", "needs_verification"] = "pass"
    elif cell.importance == "essential":
        status = "fail"
    else:
        status = "needs_verification"

    return ObjectiveCellResult(
        objective_id=cell.objective_id,
        importance=cell.importance,
        status=status,
        distinct_high_confidence_count=1 if required_present else 0,
        min_practice_count=cell.min_practice_count,
        advisory_low_confidence_count=0,
        required_forms_present=required_present,
        missing_required_forms=missing_forms,
        notes=notes,
    )


def _ledger_chain_sequences(ledger: ObjectiveLedger) -> list[list[str]]:
    """Ordered word sequences for each ledger chain source item.

    Drops chain-script directive tokens (keeps the canonical arrow sequence when
    present; otherwise the ordered word tokens).
    """
    out: list[list[str]] = []
    for src in ledger.source_items:
        if src.item_type not in ("word_chain", "chain_script"):
            continue
        seq = _chain_words_ordered(src.content)
        if len(seq) >= 2:
            out.append(seq)
    return out


def _authored_chain_sequences(cell: ObjectiveCell, evidence: list[EvidenceItem]) -> list[list[str]]:
    """Ordered word sequences from authored chain practice items for this cell."""
    out: list[list[str]] = []
    for ev in evidence:
        if ev.practice_role != PRACTICE_STUDENT:
            continue
        if cell.objective_id not in ev.objective_ids:
            continue
        seq = _chain_words_ordered(ev.visible_text)
        if len(seq) >= 2:
            out.append(seq)
    return out


_CHAIN_DIRECTIVE_RE = re.compile(r"\[[^\]]*\]|\b\d+\.")


def _chain_words_ordered(content: str) -> list[str]:
    """Ordered (NON-deduplicated) word sequence of a chain, arrows as separators.

    A real chain's value is the ordered build/transformation; we keep order and
    repeats. Directive tokens ([spelling]/numbering) and connector verbs are
    dropped so 'mule -> mute' and a scripted 'Make mule. Change ... mute.' both
    reduce to the same ordered word sequence where possible.
    """
    cleaned = _CHAIN_DIRECTIVE_RE.sub(" ", content)
    # Prefer the explicit arrow sequence when present.
    if _ARROW_RE.search(cleaned):
        parts = _ARROW_RE.split(cleaned)
        out: list[str] = []
        for part in parts:
            toks = [_normalize(t) for t in _WORD_RE.findall(part)]
            toks = [t for t in toks if t]
            if toks:
                # An arrow segment names one target word — take the last alpha token.
                out.append(toks[-1])
        return out
    # Fallback: ordered alpha tokens (chain-script without arrows).
    return [_normalize(t) for t in _WORD_RE.findall(cleaned) if _normalize(t)]


def _chain_covers(authored: list[str], ledger_chain: list[str]) -> bool:
    """True iff the authored chain contains the ledger chain's full ordered words.

    The ledger chain words must appear in the authored chain in the same relative
    order (a superset/extension is fine; a missing early step is not).
    """
    i = 0
    for word in authored:
        if i < len(ledger_chain) and word == ledger_chain[i]:
            i += 1
    return i == len(ledger_chain)


def _evaluate_connected_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
) -> ObjectiveCellResult:
    """Connected-text: satisfied by an actual passage / connected text (a multi-
    sentence surface), NOT a title or a lone word/label."""
    has_connected = False
    for ev in evidence:
        if ev.practice_role != PRACTICE_STUDENT:
            continue
        if cell.objective_id not in ev.objective_ids:
            continue
        if _is_connected_text(ev.visible_text):
            has_connected = True
            break

    notes: list[str] = []
    missing_forms: list[str] = []
    if has_connected:
        status: Literal["pass", "fail", "needs_verification"] = "pass"
    else:
        missing_forms.append("decodable_passage")
        if cell.importance == "essential":
            status = "fail"
            notes.append("no connected decodable text (passage / 2+ sentences) present")
        else:
            status = "needs_verification"

    return ObjectiveCellResult(
        objective_id=cell.objective_id,
        importance=cell.importance,
        status=status,
        distinct_high_confidence_count=1 if has_connected else 0,
        min_practice_count=cell.min_practice_count,
        advisory_low_confidence_count=0,
        required_forms_present=has_connected,
        missing_required_forms=missing_forms,
        notes=notes,
    )


_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")


def _is_connected_text(text: str) -> bool:
    """True for a passage or 2+ connected sentences (not a title or lone sentence)."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if len(_words(s)) >= 2]
    if len(sentences) >= 2:
        return True
    # A single long-ish sentence with a sentence terminator counts as connected
    # text only if it reads as a real sentence (>= 5 words + terminator).
    if sentences and _SENTENCE_SPLIT_RE.search(text):
        return len(_words(sentences[0])) >= 5
    return False


def _evaluate_irregular_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
    index: _LedgerIndex,
) -> ObjectiveCellResult:
    """Irregular/heart-word cell: distinct irregular words practiced (>= min)."""
    irregulars = {_normalize(w) for w in cell.irregular_words}
    distinct: set[str] = set()
    for w in _practice_words_for_cell(cell, evidence):
        if w in irregulars or index.resolve(w)[0] == "irregular_word":
            distinct.add(w)

    count = len(distinct)
    notes: list[str] = []
    if count >= cell.min_practice_count:
        status: Literal["pass", "fail", "needs_verification"] = "pass"
    elif cell.importance != "essential":
        status = "pass"
    elif count == 0:
        status = "needs_verification"
        notes.append("no irregular-word practice found → needs_verification")
    else:
        status = "fail"
        notes.append(f"irregular-word shortfall: {count}/{cell.min_practice_count}")

    return ObjectiveCellResult(
        objective_id=cell.objective_id,
        importance=cell.importance,
        status=status,
        distinct_high_confidence_count=count,
        min_practice_count=cell.min_practice_count,
        advisory_low_confidence_count=0,
        required_forms_present=True,
        missing_required_forms=[],
        notes=notes,
    )


def _evaluate_generic_cell(
    cell: ObjectiveCell,
    evidence: list[EvidenceItem],
) -> ObjectiveCellResult:
    """Fallback (contrast / sentence): distinct practiced words >= min."""
    count = len(_practice_words_for_cell(cell, evidence))
    if count >= cell.min_practice_count:
        status: Literal["pass", "fail", "needs_verification"] = "pass"
    elif cell.importance != "essential":
        status = "pass"
    elif count == 0:
        status = "needs_verification"
    else:
        status = "fail"
    return ObjectiveCellResult(
        objective_id=cell.objective_id,
        importance=cell.importance,
        status=status,
        distinct_high_confidence_count=count,
        min_practice_count=cell.min_practice_count,
        advisory_low_confidence_count=0,
        required_forms_present=True,
        missing_required_forms=[],
        notes=[],
    )


# ============================================================================ #
# Package upper bounds
# ============================================================================ #


def _parse_minutes(text: str) -> int:
    """Extract minutes from a time-estimate string like 'About 5 minutes' (0 if none).

    Mirrors validate/adhd_compliance.py::_parse_minutes (kept local to avoid
    importing a private symbol; same parsing approach + house style).
    """
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def _evaluate_package_bounds(
    worksheets: list[AdaptedActivityModel] | None,
    ledger: ObjectiveLedger,
    index: _LedgerIndex,
) -> PackageBoundResult:
    """Deterministic ADHD-safety upper bounds on the whole package total.

    Aggregating sufficiency across worksheets can "pass" by spreading too much
    total work across the package; these guard the package TOTAL (per-worksheet
    ``section_cap`` already guards each page). Any breach → ``passed=False`` + a
    breach note + (in the caller) overall ``status="fail"``.
    """
    if not worksheets:
        return PackageBoundResult(
            passed=True,
            total_estimated_minutes=0,
            total_item_count=0,
            dense_text_block_count=0,
            max_objectives_in_a_worksheet=0,
        )

    total_minutes = 0
    total_items = 0
    dense_blocks = 0
    max_objectives = 0

    for ws in worksheets:
        ws_objectives: set[str] = set()
        for chunk in ws.chunks:
            total_minutes += _parse_minutes(chunk.time_estimate)
            for item in chunk.items:
                total_items += 1
                if len(item.content.split()) > _DENSE_TEXT_WORD_LIMIT:
                    dense_blocks += 1
                ws_objectives.update(
                    _match_cells(
                        _words(item.content), item.response_format, ledger, index, practice=True
                    )
                )
        max_objectives = max(max_objectives, len(ws_objectives))

    breaches: list[str] = []
    if total_minutes > PACKAGE_MAX_TOTAL_MINUTES:
        breaches.append(
            f"package total {total_minutes} minutes exceeds the "
            f"{PACKAGE_MAX_TOTAL_MINUTES}-minute upper bound"
        )
    if total_items > PACKAGE_MAX_TOTAL_ITEMS:
        breaches.append(
            f"package total {total_items} items exceeds the "
            f"{PACKAGE_MAX_TOTAL_ITEMS}-item upper bound"
        )
    if dense_blocks > PACKAGE_MAX_DENSE_TEXT_BLOCKS:
        breaches.append(
            f"package has {dense_blocks} dense-text blocks "
            f"(> {_DENSE_TEXT_WORD_LIMIT} words), exceeds the "
            f"{PACKAGE_MAX_DENSE_TEXT_BLOCKS}-block upper bound"
        )
    if max_objectives > PACKAGE_MAX_OBJECTIVES_PER_WORKSHEET:
        breaches.append(
            f"a worksheet exercises {max_objectives} objectives, exceeds the "
            f"{PACKAGE_MAX_OBJECTIVES_PER_WORKSHEET}-per-worksheet upper bound"
        )

    return PackageBoundResult(
        passed=not breaches,
        total_estimated_minutes=total_minutes,
        total_item_count=total_items,
        dense_text_block_count=dense_blocks,
        max_objectives_in_a_worksheet=max_objectives,
        breaches=breaches,
    )
