"""Deterministic blocking gates for adapted worksheet packets (T5).

These gates are the last deterministic safety net before a worksheet reaches the
LLM judge. Each gate is a small, single-responsibility checker that fires only on
clear, locally verifiable defects — a false block is worse than a missed soft
issue, so every checker defaults to NOT blocking when the data shape is ambiguous
or unrepresentable.

Scope (deliberately dumb + local): T5 owns concrete answer-key / artifact / text
blockers at the item level only. It does NOT reason about objectives, sufficiency,
or "is this the sole evidence for an essential cell?" — that objective semantics
lives in T6.

Severity contract:
    - ``blocker``  → sets ``BlockingGateResult.passed = False``.
    - ``warning``  → recorded (visible / telemetered) but does NOT fail the gate.
      Used for ``teacher_checked`` situations: an unknown ``response_format`` or a
      free-text predicate that cannot be deterministically verified.

Pure + deterministic: no time, no randomness, no mutation of the input
worksheets/ledger. Violations are emitted in a stable order (worksheet index,
chunk id, item id, gate name).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from adapt.objective_ledger import ObjectiveLedger
from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel

GateName = Literal[
    "answer_key",
    "instruction_option_answer",
    "source_notation_artifact",
    "capitalization",
    "heading_as_item",
    "worked_example_consistency",
]

Severity = Literal["blocker", "warning"]


class BlockingViolation(BaseModel):
    """A single deterministic gate finding."""

    gate: GateName
    severity: Severity = "blocker"
    activity_id: str | None = None
    item_id: str | None = None
    message: str
    evidence: dict[str, str | list[str]] = Field(default_factory=dict)


class BlockingGateResult(BaseModel):
    """Aggregate result of running every gate over a worksheet packet.

    ``passed`` is True iff there are zero ``blocker``-severity violations.
    ``warning``-only results do NOT fail the gate.
    """

    passed: bool
    violations: list[BlockingViolation] = Field(default_factory=list)


# ============================================================================ #
# Normalization + shared regexes
# ============================================================================ #

# Format allowlist: the ONLY response formats where answer-in-options is
# unambiguously required (these carried the backtest defect).
_MEMBERSHIP_FORMATS = frozenset({"circle", "fill_blank"})

# Formats where answer != option is legitimate / membership must NOT be required.
_KNOWN_NON_MEMBERSHIP_FORMATS = frozenset(
    {"match", "sound_box", "read_aloud", "trace", "write", "verbal"}
)

# Trailing source-notation markers (mirror skill/extractor::_MARKER_PATTERN).
_MARKER_RE = re.compile(r"\w+[*♥❤]", re.UNICODE)
# Bracketed source annotations always block ([heart word], [hf], ...).
_BRACKET_RE = re.compile(r"\[[^\]]+\]")
# Parentheticals are NOT blocked by default: T4 strips paren annotations upstream,
# and ordinary K-3 parentheticals ("(and jump)", "(long u)") are legitimate. This
# safety-net only flags a paren whose inner text carries a SOURCE-ANNOTATION cue.
_PAREN_RE = re.compile(r"\([^)]+\)")
_ANNOTATION_CUE_RE = re.compile(r"\b(heart|trick|sight|hf|high-frequency|word)\b", re.IGNORECASE)

# "This model is wrong" tokens in a worked example. Bare ``no``/``not`` are
# excluded: they're far too common in instructional prose ("Do not forget the
# silent e", "Circle the word, not the picture") to be safe standalone triggers.
# A genuinely contradicted model ("cube -> kube. No, that's wrong.") is still
# caught via ``wrong``.
_NEGATION_RE = re.compile(r"(?<![a-z])(wrong|nope|incorrect)(?![a-z])", re.IGNORECASE)
_NEGATION_SYMBOLS = ("✗", "❌", "✘")

# Common UFLI section headings that must never appear as a practice item.
_UFLI_HEADINGS = frozenset(
    {
        "roll and read",
        "word chain",
        "word work",
        "sample words",
        "new concept",
        "new concept and sample words",
        "sentence reading",
        "sentence writing",
        "decodable text",
        "heart words",
        "trick words",
    }
)

_WORD_RE = re.compile(r"[A-Za-z]+")


def _normalize(text: str) -> str:
    """Casefold + strip leading/trailing non-alphanumerics (token comparison)."""
    return re.sub(r"^[^0-9a-z]+|[^0-9a-z]+$", "", text.casefold())


def _normalize_phrase(text: str) -> str:
    """Casefold + collapse whitespace + drop punctuation (heading comparison)."""
    return " ".join(_WORD_RE.findall(text.casefold()))


def _activity_id(ws_index: int) -> str:
    return f"ws{ws_index}"


def _item_id(ws_index: int, chunk: ActivityChunk, item: ActivityItem) -> str:
    return f"ws{ws_index}_chunk{chunk.chunk_id}_item{item.item_id}"


def _chunk_id(ws_index: int, chunk: ActivityChunk) -> str:
    return f"ws{ws_index}_chunk{chunk.chunk_id}"


# ============================================================================ #
# Gate 1: answer_key (format allowlist)
# ============================================================================ #


def _check_answer_key(
    item: ActivityItem, activity_id: str, item_id: str
) -> list[BlockingViolation]:
    """Require answer in options ONLY for circle / fill_blank with options set.

    match -> not membership-checked (answer != option is the mechanic).
    sound_box / read_aloud / trace / write / verbal / empty options -> not checked.
    Unknown response_format -> warning (teacher_checked), never a blocker.
    """
    fmt = item.response_format
    if fmt in _KNOWN_NON_MEMBERSHIP_FORMATS:
        return []

    if fmt in _MEMBERSHIP_FORMATS:
        if not item.options or item.answer is None:
            return []
        norm_options = {_normalize(o) for o in item.options}
        # Multi-answer: if the answer encodes several (comma/slash separated),
        # require every part present. Single-token answers fall through cleanly.
        answer_parts = [_normalize(p) for p in re.split(r"[,/]", item.answer) if _normalize(p)]
        if not answer_parts:
            return []
        missing = [p for p in answer_parts if p not in norm_options]
        if missing:
            return [
                BlockingViolation(
                    gate="answer_key",
                    severity="blocker",
                    activity_id=activity_id,
                    item_id=item_id,
                    message=(
                        f"{fmt} item answer "
                        f"{item.answer!r} is not among its options {item.options!r}"
                    ),
                    evidence={"answer": item.answer, "options": list(item.options)},
                )
            ]
        return []

    # Unknown / future response_format → teacher_checked warning, never a blocker.
    return [
        BlockingViolation(
            gate="answer_key",
            severity="warning",
            activity_id=activity_id,
            item_id=item_id,
            message=f"unknown response_format {fmt!r}; answer-key not deterministically checkable",
            evidence={"response_format": fmt},
        )
    ]


# ============================================================================ #
# Gate 2: instruction_option_answer (checkable subset only)
# ============================================================================ #


def _check_instruction_option_answer(
    item: ActivityItem,
    pattern: PatternPredicate | None,
    activity_id: str,
    item_id: str,
) -> list[BlockingViolation]:
    """If the instruction names a machine-checkable phonics predicate, the keyed
    answer must satisfy it (and be present in options). Free-text predicates →
    teacher_checked warning, not a block. Only blocks circle/fill_blank items with
    options + answer (the membership-bearing formats).
    """
    if item.response_format not in _MEMBERSHIP_FORMATS:
        return []
    if not item.options or item.answer is None:
        return []
    if pattern is None:
        # No machine-checkable predicate parsed from the instruction → defer to a
        # human (teacher_checked). Not a block.
        return []

    answer_norm = _normalize(item.answer)
    if not answer_norm:
        return []
    if pattern.matches(answer_norm):
        return []
    return [
        BlockingViolation(
            gate="instruction_option_answer",
            severity="blocker",
            activity_id=activity_id,
            item_id=item_id,
            message=(
                f"keyed answer {item.answer!r} does not satisfy the instruction "
                f"predicate ({pattern.describe()})"
            ),
            evidence={"answer": item.answer, "predicate": pattern.describe()},
        )
    ]


# ============================================================================ #
# Gate 3: source_notation_artifact
# ============================================================================ #


def _artifacts_in(text: str) -> list[str]:
    """Return raw source-notation artifacts found in student-facing text."""
    found: list[str] = []
    found.extend(_MARKER_RE.findall(text))
    found.extend(_BRACKET_RE.findall(text))
    # Parens only count as artifacts when the inner text reads as a source
    # annotation (e.g. "(heart word)", "(sight word)") — plain parentheticals
    # like "(and jump)" / "(long u)" are legitimate and must NOT block.
    for paren in _PAREN_RE.findall(text):
        if _ANNOTATION_CUE_RE.search(paren):
            found.append(paren)
    return found


def _check_source_notation(
    item: ActivityItem, activity_id: str, item_id: str
) -> list[BlockingViolation]:
    """Block if raw source notation (by*, [..], (..), heart markers) is visible."""
    surfaces: list[str] = [item.content]
    if item.options:
        surfaces.extend(item.options)
    artifacts: list[str] = []
    for surface in surfaces:
        artifacts.extend(_artifacts_in(surface))
    if not artifacts:
        return []
    return [
        BlockingViolation(
            gate="source_notation_artifact",
            severity="blocker",
            activity_id=activity_id,
            item_id=item_id,
            message=f"student-facing text contains raw source notation: {artifacts}",
            evidence={"artifacts": artifacts},
        )
    ]


# ============================================================================ #
# Gate 4: capitalization
# ============================================================================ #


def _known_proper_nouns(ledger: ObjectiveLedger) -> frozenset[str]:
    """Proper nouns = tokens capitalized NOT at sentence/line start in source.

    Example: in "cube, mute, fuse, tune, rule, June" the token `June` is
    capitalized mid-list, so it's a proper noun. Two guards against false
    positives from passage titles (G14, "Lily's Puppy"):

    1. Title-case segments (every alpha token capitalized, >= 2 tokens) are
       headings, not sentences — they contribute no proper-noun evidence.
    2. A token seen lowercase ANYWHERE in the source is exonerated: real
       proper nouns are never written lowercase in curriculum text.
    """
    candidates: set[str] = set()
    lowercase_seen: set[str] = set()
    for src in ledger.source_items:
        for segment in re.split(r"[\n.!?]", src.content):
            tokens = [t for t in re.split(r"[\s,]+", segment) if t]
            stripped_tokens = [re.sub(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$", "", t) for t in tokens]
            alpha = [t for t in stripped_tokens if t and t[0].isalpha()]
            if len(alpha) >= 2 and all(t[0].isupper() for t in alpha):
                continue  # title-case heading: no proper-noun evidence
            for pos, stripped in enumerate(stripped_tokens):
                if not stripped:
                    continue
                if stripped == stripped.lower():
                    lowercase_seen.add(stripped.casefold())
                if pos == 0:
                    continue  # sentence/line-initial: ambiguous, skip
                if len(stripped) >= 2 and stripped[0].isupper() and stripped[1:].islower():
                    candidates.add(stripped.casefold())
    return frozenset(candidates - lowercase_seen)


def _check_capitalization(
    item: ActivityItem,
    proper_nouns: frozenset[str],
    activity_id: str,
    item_id: str,
) -> list[BlockingViolation]:
    """Block if a known proper noun appears lowercased mid-sentence in visible text.

    A proper noun at the start of a sentence/line PASSES (can't distinguish from
    required sentence-initial capitalization).
    """
    if not proper_nouns:
        return []
    violations: list[BlockingViolation] = []
    seen_lowered: set[str] = set()
    for segment in re.split(r"[\n.!?]", item.content):
        tokens = [t for t in re.split(r"\s+", segment) if t]
        for pos, tok in enumerate(tokens):
            if pos == 0:
                continue  # sentence-initial → PASS
            stripped = re.sub(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$", "", tok)
            if not stripped:
                continue
            low = stripped.casefold()
            if low in proper_nouns and stripped == stripped.lower() and low not in seen_lowered:
                seen_lowered.add(low)
                violations.append(
                    BlockingViolation(
                        gate="capitalization",
                        severity="blocker",
                        activity_id=activity_id,
                        item_id=item_id,
                        message=(
                            f"proper noun {low!r} appears lowercased mid-sentence; "
                            f"expected capitalized"
                        ),
                        evidence={"token": stripped, "content": item.content},
                    )
                )
    return violations


# ============================================================================ #
# Gate 5: heading_as_item
# ============================================================================ #


def _known_headings(ledger: ObjectiveLedger) -> frozenset[str]:
    """Build the set of normalized headings/labels that must NOT be practice items.

    Sources: UFLI section headings, objective display_names + concepts, the
    primary pattern, and chain_script / supporting-evidence source-item content
    (these are labels/directions, not items).
    """
    headings: set[str] = set(_UFLI_HEADINGS)
    for obj in ledger.objectives:
        headings.add(_normalize_phrase(obj.display_name))
        headings.add(_normalize_phrase(obj.concept))
    if ledger.primary_pattern:
        headings.add(_normalize_phrase(ledger.primary_pattern))
    for src in ledger.source_items:
        if src.item_type == "chain_script":
            headings.add(_normalize_phrase(src.content))
    headings.discard("")
    return frozenset(headings)


def _check_heading_as_item(
    item: ActivityItem,
    headings: frozenset[str],
    activity_id: str,
    item_id: str,
) -> list[BlockingViolation]:
    """Block if an item's content exactly matches a known heading/label."""
    content_norm = _normalize_phrase(item.content)
    if content_norm and content_norm in headings:
        return [
            BlockingViolation(
                gate="heading_as_item",
                severity="blocker",
                activity_id=activity_id,
                item_id=item_id,
                message=(
                    f"item content {item.content!r} is a known section heading / label, "
                    f"not a practice item"
                ),
                evidence={"content": item.content},
            )
        ]
    return []


# ============================================================================ #
# Gate 6: worked_example_consistency (NARROW)
# ============================================================================ #

_WE_ANSWER_RE = re.compile(r"answer\s*[:=]\s*(.+)$", re.IGNORECASE)
_WE_OPTIONS_RE = re.compile(r"(?:circle|options|choose)\s*[:=]?\s*(.+?)(?:\||$)", re.IGNORECASE)


def _check_worked_example(
    chunk: ActivityChunk,
    pattern: PatternPredicate | None,
    activity_id: str,
    chunk_id: str,
) -> list[BlockingViolation]:
    """Flag a CLEAR worked-example contradiction. Default to NOT flagging.

    Fires only on:
      (a) a post-answer negation token ("No.", "wrong", "✗") — a contradicted model;
      (b) the example demonstrates an answer that fails the chunk's OWN machine-
          checkable instruction predicate;
      (c) the example's own answer/options are internally mismatched (answer not in
          its displayed options).
    """
    ex = chunk.worked_example
    if ex is None:
        return []
    content = ex.content

    # (a) post-answer negation / contradiction marker.
    if _NEGATION_RE.search(content) or any(sym in content for sym in _NEGATION_SYMBOLS):
        return [
            BlockingViolation(
                gate="worked_example_consistency",
                severity="blocker",
                activity_id=activity_id,
                item_id=chunk_id,
                message="worked example contains a negation/contradiction marker after a model",
                evidence={"worked_example": content},
            )
        ]

    # (c) internal answer-vs-options mismatch (only when the example shows both).
    answer_match = _WE_ANSWER_RE.search(content)
    options_match = _WE_OPTIONS_RE.search(content)
    if answer_match and options_match:
        ans = _normalize(answer_match.group(1))
        opt_tokens = re.split(r"[\s,|]+", options_match.group(1))
        opts = {_normalize(t) for t in opt_tokens if _normalize(t)}
        if ans and opts and ans not in opts:
            return [
                BlockingViolation(
                    gate="worked_example_consistency",
                    severity="blocker",
                    activity_id=activity_id,
                    item_id=chunk_id,
                    message="worked example answer is not among its own displayed options",
                    evidence={"worked_example": content},
                )
            ]

    # (b) example answer fails the chunk's machine-checkable predicate.
    if pattern is not None and answer_match:
        ans = _normalize(answer_match.group(1))
        if ans and not pattern.matches(ans):
            return [
                BlockingViolation(
                    gate="worked_example_consistency",
                    severity="blocker",
                    activity_id=activity_id,
                    item_id=chunk_id,
                    message=(
                        f"worked example answer {answer_match.group(1).strip()!r} fails the "
                        f"instruction predicate ({pattern.describe()})"
                    ),
                    evidence={"worked_example": content, "predicate": pattern.describe()},
                )
            ]

    return []


# ============================================================================ #
# Instruction predicate parsing (shared by gates 2 + 6)
# ============================================================================ #


class PatternPredicate:
    """A machine-checkable 'words with pattern X' predicate parsed from an
    instruction. Conservative: only constructed when we can clearly evaluate it.
    """

    def __init__(self, kind: str, key: str) -> None:
        self._kind = kind  # "vce" | "rime" | "substring"
        self._key = key  # the vowel, the rime, or the substring

    def matches(self, word: str) -> bool:
        if self._kind == "vce":
            # silent-e word with the target vowel as the nucleus: ...<vowel><cons>e
            if len(word) < 4 or not word.endswith("e"):
                return False
            body = word[:-1]
            return len(body) >= 3 and body[-2] == self._key and body[-1] not in "aeiou"
        if self._kind == "rime":
            return word.endswith(self._key)
        return self._key in word

    def describe(self) -> str:
        return f"{self._kind}:{self._key}"


_INSTR_VCE_RE = re.compile(r"\b([aeiou])_e\b", re.IGNORECASE)
_INSTR_LONG_VOWEL_RE = re.compile(r"\blong[\s-]+([aeiou])\b", re.IGNORECASE)
# Rime hyphen must be at a token start (after start-of-string or whitespace) so
# hyphenated words ("sound-by-sound", "well-known", "twenty-one") don't read as a
# rime; a genuine cue ("the -oll words", "the -ull family") still does.
_INSTR_RIME_RE = re.compile(r"(?:^|\s)-([a-z]{2,})\b", re.IGNORECASE)


def _parse_instruction_predicate(chunk: ActivityChunk) -> PatternPredicate | None:
    """Parse a single machine-checkable phonics predicate from chunk instructions.

    Returns None for free-text / unparseable predicates (→ teacher_checked, no
    block). Deliberately narrow: only `X_e` / `long X` (VCe) and `-rime` forms.
    """
    text = " ".join(step.text for step in chunk.instructions)
    m = _INSTR_VCE_RE.search(text) or _INSTR_LONG_VOWEL_RE.search(text)
    if m:
        return PatternPredicate("vce", m.group(1).lower())
    rime = _INSTR_RIME_RE.search(text)
    if rime:
        return PatternPredicate("rime", rime.group(1).lower())
    return None


# ============================================================================ #
# Orchestration
# ============================================================================ #


def run_blocking_gates(
    worksheets: list[AdaptedActivityModel],
    ledger: ObjectiveLedger,
) -> BlockingGateResult:
    """Run every deterministic gate over every worksheet/chunk/item.

    Collects violations in a stable order (worksheet index, chunk id, item id,
    gate name) and returns a result whose ``passed`` is True iff there are zero
    ``blocker``-severity violations. Pure + deterministic; inputs are not mutated.
    """
    proper_nouns = _known_proper_nouns(ledger)
    headings = _known_headings(ledger)

    violations: list[BlockingViolation] = []

    for ws_index, ws in enumerate(worksheets):
        activity_id = _activity_id(ws_index)
        for chunk in ws.chunks:
            chunk_id = _chunk_id(ws_index, chunk)
            predicate = _parse_instruction_predicate(chunk)

            # Chunk-level gate: worked-example consistency.
            violations.extend(_check_worked_example(chunk, predicate, activity_id, chunk_id))

            for item in chunk.items:
                item_id = _item_id(ws_index, chunk, item)
                violations.extend(_check_answer_key(item, activity_id, item_id))
                violations.extend(
                    _check_instruction_option_answer(item, predicate, activity_id, item_id)
                )
                violations.extend(_check_source_notation(item, activity_id, item_id))
                violations.extend(_check_capitalization(item, proper_nouns, activity_id, item_id))
                violations.extend(_check_heading_as_item(item, headings, activity_id, item_id))

    violations.sort(key=lambda v: (v.activity_id or "", v.item_id or "", v.gate))
    has_blocker = any(v.severity == "blocker" for v in violations)
    return BlockingGateResult(passed=not has_blocker, violations=violations)
