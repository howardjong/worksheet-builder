"""Data models for the objective-sufficiency coverage system.

This module defines the ObjectiveLedger schema, which tracks per-objective coverage
for a worksheet against UFLI curriculum standards. The ledger classifies source items
by coverage role (required form, samplable pool, etc.) and tracks word-level roles
with confidence signals to support strict validation.

Schema-only for now; builder logic (T2/T3) will be added in later tasks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
