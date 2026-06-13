# Objective-Sufficiency Coverage Rubric Research And Implementation Spec

Date: 2026-06-13

Status: revised implementation plan. This replaces the draft page-fidelity `content_coverage` criterion with a shared objective-sufficiency definition used by both the LLM judge and the deterministic validation scorecard.

## Executive Decision

Coverage should mean: did the adaptation give enough correct, low-overwhelm practice for each literacy objective in the source lesson?

Coverage should not mean: did the adaptation reproduce every source page item?

The release gate must therefore move from page fidelity to an objective ledger:

1. Build a deterministic `ObjectiveLedger` from `LiteracySkillModel.source_items`, `lesson_number`, and the UFLI corpus.
2. Classify source material deterministically as `required_form`, `samplable_pool`, `contrast_role`, or `supporting_evidence`.
3. Run deterministic blocking gates for answer-key correctness and source-notation artifacts before any LLM judging.
4. Use the same ledger in both coverage signals:
   - the judge's old `content_coverage` slot, temporarily mapped to `objective_sufficiency`
   - the deterministic `validate/` coverage column in the battery scorecard
5. Ask the LLM judge only to score adaptation evidence against the ledger it is handed. The judge must not extract objectives, classify items, or decide whether a source item is mandatory.

This preserves the product rule: skill-preserving, not page-faithful. It also respects the ADHD design constraint: short, chunked, low-overwhelm practice can be sufficient even when a source worksheet contains a long repetition pool.

## Evidence Basis

The education frame is stable: backward design starts with desired results and acceptable evidence before activities; Bloom-style taxonomies distinguish the kind of cognitive performance required; mastery learning treats practice and assessment as aligned with objectives and corrective feedback; curriculum-based measurement samples repeatable performance indicators rather than requiring every possible item.

For structured literacy, the relevant objectives in an early phonics lesson are not one flat "word coverage" bucket. They commonly include decoding a target pattern, encoding or spelling the pattern, manipulating phonemes or graphemes through chains, reading irregular or high-frequency words, and applying the pattern in connected text. UFLI-aligned routines make form matter: a word chain must be built or transformed; a decodable passage must be read as connected text; a long roll-and-read or fluency list is a practice pool.

For ADHD and cognitive load, the evidence supports explicit instruction, repeated practice for automaticity, short tasks, immediate feedback, and reduced extraneous load. The precise "right number" of items per objective for ages 5-8 with ADHD is not settled. The practical implementation should therefore use conservative sufficiency priors, enforce upper bounds against overwhelm, and calibrate thresholds against expert human raters.

## Deterministic Objective Ledger

### Builder Placement

Add a deterministic builder between `LiteracySkillModel` and planning/judging:

```text
SourceWorksheetModel
  -> LiteracySkillModel
  -> ObjectiveLedgerBuilder
  -> AdaptedActivityModel generation
  -> DeterministicBlockingGates
  -> DeterministicObjectiveCoverageValidator
  -> LLM judge, handed the ledger and deterministic evidence index
```

The builder should live in a shared module such as `skill/objective_ledger.py` or replace/upgrade `adapt/coverage_ledger.py`. It must be importable from both `adapt/` and `validate/`.

Inputs:

- `LiteracySkillModel`
  - `lesson_number`
  - `specific_skill`
  - `learning_objectives`
  - `target_words`
  - `source_items: list[SourceItem]`
- UFLI corpus lesson lookup by `lesson_number`, when available
- deterministic phonics pattern helpers, initially simple and explicit

Non-goals:

- No LLM extraction.
- No in-prompt objective discovery.
- No judge-side item classification.

### Ledger Schema

Use Pydantic and keep the schema serializable so it can be stored in artifacts and passed to the judge.

```python
from typing import Literal
from pydantic import BaseModel, Field

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

class LedgerWord(BaseModel):
    text: str
    normalized: str
    role: SourceRole
    objective_ids: list[str] = Field(default_factory=list)
    source_item_id: str | None = None
    reason: str

class ClassifiedSourceItem(BaseModel):
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
    answer_key_gate: bool = True
    source_notation_artifact_gate: bool = True
    instruction_option_answer_gate: bool = True
    capitalization_gate: bool = True

class ObjectiveLedger(BaseModel):
    ledger_version: Literal["objective_sufficiency_v1"] = "objective_sufficiency_v1"
    source_skill_hash: str
    lesson_number: int | None
    corpus_status: Literal["matched", "missing", "not_applicable"]
    corpus_lesson_id: str | None = None
    primary_pattern: str | None = None
    objectives: list[ObjectiveCell]
    source_items: list[ClassifiedSourceItem]
    blocking_rules: BlockingGateSpec = Field(default_factory=BlockingGateSpec)
    builder_warnings: list[str] = Field(default_factory=list)
```

### Deterministic Builder Rules

The mapping from typed source item to objective and coverage class is a fixed function.

1. Resolve lesson context.
   - If `lesson_number` is present and UFLI corpus lookup succeeds, use corpus lesson metadata as the canonical source for pattern, lesson title, irregular words, decodable text, and known routines.
   - If corpus lookup fails, fall back to `LiteracySkillModel.specific_skill`, `learning_objectives`, `target_words`, and source item metadata.
   - Record `corpus_status` and warnings. Do not ask the judge to repair a missing corpus match.

2. Create objective cells.
   - Always create a decoding objective when a target phonics pattern is known.
   - Create encoding when the source includes spelling, dictation, fill-in, or response formats implying production.
   - Create phoneme or grapheme manipulation when `word_chain` or `chain_script` appears.
   - Create connected-text fluency when a `passage` appears, or when sentence items are used as connected decodable text.
   - Create irregular-word reading when `sight_words` appear or corpus lesson metadata contains heart/high-frequency words.
   - Create contrast discrimination when non-pattern words are used deliberately in sort, choose, odd-one-out, or pattern/not-pattern tasks.

3. Classify each source item.
   - `word_chain` and `chain_script` are `required_form`.
   - `passage` is `required_form`.
   - `sight_words` is `required_form` for the irregular-word objective, but individual words can be sampled if the source pool is large and the objective still reaches its minimum.
   - `word_list` and `roll_and_read` are `samplable_pool` unless metadata explicitly marks them as an assessment list requiring exhaustive coverage.
   - `sentence` is `required_form` only when it is the sole connected-text evidence or a sentence-writing task; otherwise it is samplable connected-text evidence.
   - Items that only establish the lesson concept, title, or directions are `supporting_evidence`.

4. Classify words by role.
   - A word matching the lesson target pattern is `target_pattern`.
   - A corpus-marked heart word, trick word, or sight word is `irregular_word`.
   - A decodable word that does not match the current pattern but plausibly belongs to prior lessons is `review_word`.
   - A non-pattern word included among pattern words is `contrast_word` only if the surrounding source item or adapted task uses it for sorting, discrimination, or negative examples.
   - If the role cannot be determined safely, tag it `ambiguous_review_word`. It must not count toward the primary pattern objective's sufficiency.

5. Compute sufficiency thresholds from objectives, not page item count.
   - Decoding target pattern: enough distinct target-pattern words to show practice across the pattern, usually 6-10 for K-3 short worksheets; lower bound can be 4 for very early K or very short tasks.
   - Encoding or spelling: usually 3-6 production items, because production is harder and slower than recognition.
   - Word chain or chain script: at least one coherent chain segment with the transformations preserved; count steps, not just words mentioned.
   - Connected text: at least one decodable sentence group or passage excerpt that preserves connected reading; long passages may be shortened only if the target pattern and meaning remain coherent.
   - Irregular words: usually 2-5 words, prioritizing words introduced by the lesson; very large review pools are samplable.
   - Contrast discrimination: at least one deliberate compare/sort/choose task with both target and contrast examples.

These thresholds are priors, not law. Store them in the ledger so the judge and validator see the same expectation.

## Typed Source Item Mapping

| Source item type | Objective mapping | Coverage class | Mandatory? | Sufficiency rule | Contrast handling |
|---|---|---:|---:|---|---|
| `word_chain` | `phoneme_grapheme_manipulation`, often decoding/encoding support | `required_form` | yes | Must preserve a build/change sequence; mentioning the words is not enough | Non-pattern steps may be review/contrast if the chain deliberately contrasts sounds; they do not count toward target-pattern decoding |
| `chain_script` | `phoneme_grapheme_manipulation` | `required_form` | yes | Must adapt into an executable chain, teacher prompt, or child transformation task | Same as `word_chain`; transformations are the evidence |
| `word_list` | decoding, encoding if production is requested | `samplable_pool` | no, unless explicitly assessment | Sample enough target-pattern words to meet the objective threshold | Non-pattern words are `review_word`, `contrast_word`, or `ambiguous_review_word`; they do not count for pattern sufficiency |
| `sentence` | sentence reading/writing; connected text support | required only when sole connected-text or writing form | conditional | Preserve a sentence-level practice form when sentence reading/writing is an objective | Non-pattern words are normal context unless used as contrast; do not penalize their presence in decodable sentences |
| `passage` | connected-text fluency | `required_form` | yes | Must include connected-text reading, not just isolated words; may shorten if target pattern and coherence remain | Irregular/review words in passage are context, not failures |
| `sight_words` | irregular-word reading | `required_form` objective, samplable within large pool | yes for objective | Practice lesson-introduced irregular words; sample large review pools | Never count sight words toward target-pattern decoding |
| `roll_and_read` | decoding fluency | `samplable_pool` | no | Sample enough target-pattern words; preserve quick repeated-read feel if appropriate | Contrast words can be used for sort/discrimination but should not dilute primary pattern practice |

## Contrast And Concept-Dilution Handling

Sampling alone does not prevent concept dilution. A long source page may contain distractors, review words, proper nouns, and irregular sight words. The planner can accidentally practice them as if they were the target pattern.

The ledger must therefore separate role from presence:

- `target_pattern` words count toward target decoding/encoding sufficiency.
- `irregular_word` words count only toward irregular-word objectives.
- `review_word` words may appear in connected text or warmups but do not count toward the current pattern.
- `contrast_word` words receive credit only inside a deliberate contrast task.
- `ambiguous_review_word` words are allowed as context but do not count toward any essential objective.

Example: in an `-oll` lesson, words such as `roll`, `toll`, and `doll` can count toward the target pattern. Words like `jazz`, `hill`, and `mop` should be classified as review or contrast, depending on source context. They should not reduce the score merely because they appear, and they should not help satisfy the `-oll` decoding objective. If the adaptation creates a "sort -oll/not -oll" task using `roll`, `doll`, `jazz`, and `mop`, that can satisfy a `contrast_discrimination` objective while leaving the `decode_target_pattern` objective to be satisfied by target-pattern items.

Implementation rule: the validator and judge must report counts by role. A pattern objective's numerator is only target-pattern practice in acceptable forms; deliberate contrast tasks are credited in their own objective cell.

## Deterministic Blocking Gates

Wrong answer keys and source-notation artifacts are not low-weight quality issues. They are release blockers.

Run blocking gates after `AdaptedActivityModel` generation and before LLM judging. If any blocking gate fails, the package is not approved and the judge may be skipped. The deterministic coverage validator can still run for diagnostics, but the final quality decision is blocked.

### Gate Result Schema

```python
class BlockingViolation(BaseModel):
    gate: Literal[
        "answer_key",
        "instruction_option_answer",
        "source_notation_artifact",
        "capitalization",
    ]
    severity: Literal["blocker", "warning"] = "blocker"
    activity_id: str | None = None
    item_id: str | None = None
    message: str
    evidence: dict[str, str | list[str]] = Field(default_factory=dict)

class BlockingGateResult(BaseModel):
    passed: bool
    violations: list[BlockingViolation] = Field(default_factory=list)
```

### Gate Rules

`answer_key`:

- If an item has `options`, every keyed answer must normalize to one of those options unless `metadata.answer_mode` is explicitly `free_response`, `dictation`, or `teacher_checked`.
- For multiple-answer tasks, all keyed answers must be present among options.
- For matching tasks, both sides of every keyed pair must exist in the displayed choices.
- For fill-in tasks, the student-facing content must contain a blank or target slot, and the answer must plausibly fill it.

`instruction_option_answer`:

- If instructions specify a grapheme, pattern, or word property, keyed answers must satisfy that property.
- If the item says "circle words with i", keyed answers must contain the target `i` pattern after normalization, and non-key options should not all satisfy the same predicate.
- If options do not contain the keyed answer, block.
- If the predicate cannot be checked deterministically, mark the item `teacher_checked` during planning or block until the planner emits machine-checkable metadata.

`source_notation_artifact`:

- Student-facing text must not contain raw source notation such as `by*`, `my*`, trailing heart-word markers, OCR markup, extraction labels, worksheet headers accidentally copied as content, or bracketed source annotations.
- Ledger construction should strip or preserve these annotations only in metadata, never in display text.
- Asterisks and markup can appear only if the activity explicitly teaches notation and metadata marks them as intentional. That should be rare for K-3 student-facing output.

`capitalization`:

- Proper nouns known from the source or corpus must retain correct capitalization in student-facing text. For example, `June` should not become `june`.
- All-lowercase word-list display remains allowed when the source token is not a proper noun and the activity is isolated decoding.

Composition:

```text
if blocking_gates.passed is false:
    final_quality.approved = false
    final_quality.block_reason = blocking_gates.violations
    skip_or_mark_judge_as_not_applicable
else:
    run deterministic objective coverage
    run LLM judge against ledger
```

## Deterministic Coverage Validator Change

The current `validate/content_coverage.py` validator should stop measuring page-item coverage. Its replacement should read the same `ObjectiveLedger` as the judge.

Recommended implementation:

1. Add shared functions:
   - `build_objective_ledger(skill: LiteracySkillModel) -> ObjectiveLedger`
   - `build_adaptation_evidence_index(adapted: AdaptedActivityModel, ledger: ObjectiveLedger) -> AdaptationEvidenceIndex`
   - `evaluate_objective_sufficiency(ledger, evidence_index) -> ObjectiveCoverageResult`

2. Update `validate/content_coverage.py` to become a compatibility wrapper:

```python
def validate_content_coverage_for_package(package: WorksheetPackage) -> ValidationResult:
    ledger = build_objective_ledger(package.skill_model)
    evidence = build_adaptation_evidence_index(package.adapted_activity, ledger)
    result = evaluate_objective_sufficiency(ledger, evidence)
    return result.to_validation_result(
        validator="content_coverage",
        definition="objective_sufficiency_v1",
    )
```

3. Rename internally when convenient:
   - public scorecard column can remain `coverage` for continuity
   - details must say `definition: objective_sufficiency_v1`
   - do not require exact reproduction of every `word_list` or `roll_and_read` token

4. Failure conditions:
   - fail if an essential objective cell is below its deterministic minimum
   - fail if a required form is absent
   - fail if a pattern objective is satisfied mostly by `contrast_word`, `review_word`, or `irregular_word` roles
   - do not fail merely because a large fluency pool was sampled

This makes both coverage signals share one definition:

```text
ledger objective cells + required forms + role-aware sufficiency thresholds
```

The judge can add qualitative evidence about whether the practice is meaningful, but it cannot override the deterministic validator's required-form or role counts.

## Judge Input And Output Contract

The judge receives a complete ledger and deterministic evidence index. It must not extract objectives or classify source items.

### Input

```json
{
  "judge_contract_version": "objective_sufficiency_judge_v1",
  "objective_ledger": {
    "ledger_version": "objective_sufficiency_v1",
    "lesson_number": 95,
    "primary_pattern": "CVCe / long u",
    "objectives": [],
    "source_items": []
  },
  "blocking_gates": {
    "passed": true,
    "violations": []
  },
  "deterministic_coverage": {
    "definition": "objective_sufficiency_v1",
    "objective_results": [],
    "required_form_results": [],
    "role_counts": {}
  },
  "adapted_activity": {
    "activity_id": "activity_001",
    "title": "Readable title",
    "chunks": []
  },
  "evidence_index": {
    "activity_items": [
      {
        "activity_item_id": "chunk_1_item_2",
        "student_facing_text": "Circle the words with magic e.",
        "response_format": "multiple_choice",
        "options": ["cube", "cut", "duke"],
        "answer": "cube",
        "ledger_objective_ids": ["decode_target_pattern"],
        "matched_words_by_role": {
          "target_pattern": ["cube", "duke"],
          "contrast_word": ["cut"]
        }
      }
    ]
  }
}
```

### Judge Instructions

The judge may:

- score whether the adaptation evidence meaningfully practices each handed objective
- identify thin, confusing, or overly broad practice
- flag suspected ledger issues without changing the score basis
- explain whether ADHD chunking preserved enough repetitions without overload

The judge must not:

- create new objectives
- reclassify source items
- demand every word from a samplable pool
- count contrast, review, or irregular words toward a target-pattern objective unless the ledger says to
- approve a package that failed deterministic blockers

### Output

Use 0-1 scores to match current infrastructure. Do not switch to a 0-5 scale.

```python
class ObjectiveJudgeCellScore(BaseModel):
    objective_id: str
    score: float = Field(ge=0.0, le=1.0)
    form_score: float = Field(ge=0.0, le=1.0)
    sufficiency_score: float = Field(ge=0.0, le=1.0)
    clarity_score: float = Field(ge=0.0, le=1.0)
    evidence_item_ids: list[str]
    rationale: str

class ObjectiveJudgeVerdict(BaseModel):
    contract_version: Literal["objective_sufficiency_judge_v1"]
    objective_scores: list[ObjectiveJudgeCellScore]
    objective_sufficiency: float = Field(ge=0.0, le=1.0)
    skill_form_fidelity: float = Field(ge=0.0, le=1.0)
    structured_literacy_alignment: float = Field(ge=0.0, le=1.0)
    adhd_cognitive_load_fit: float = Field(ge=0.0, le=1.0)
    lesson_flow_and_usability: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    ledger_issue_suspected: bool = False
    ledger_issue_notes: list[str] = Field(default_factory=list)
    approval_recommendation: Literal["approve", "revise", "reject"]
    feedback: list[str] = Field(default_factory=list)
```

Compatibility with current `adapt/llm_judge.py`:

- Map old `content_coverage` to new `objective_sufficiency` during transition.
- Replace the old prompt text that says "ALL source words, word chains, sight words, and sentences" with "all essential objective cells in the supplied ledger."
- Keep median-of-N judging if still used, but aggregate by objective cell before computing the overall score.

## Rubric Criteria And Anchors

### Criterion Weights

| Criterion | Weight | Scored by | Notes |
|---|---:|---|---|
| Objective sufficiency | 0.35 | deterministic validator + judge | Ledger-based. No page-fidelity requirement. |
| Skill-form fidelity | 0.20 | deterministic required-form checks + judge | Word chains, passages, dictation, sorting forms must stay forms. |
| ADHD cognitive-load fit | 0.20 | judge + deterministic length/chunk checks | Short, predictable, not overstuffed. |
| Structured-literacy alignment | 0.15 | judge | Explicit, sequential, pattern-aligned; contrast words handled deliberately. |
| Lesson flow and usability | 0.10 | judge + print checks | Clear instructions, scannable layout. Answer-key and artifact issues are blockers, not soft points. |

### Anchors

Use behavioral 0-1 anchors:

- 1.00: all essential objectives are practiced in the required forms, with enough target examples and no overload.
- 0.80: all essential objectives are present; one objective is a little thin or could use clearer practice.
- 0.60: the main objective is present, but at least one supporting objective or form is under-practiced.
- 0.40: a major objective is missing, replaced by generic activity, or diluted by non-pattern words.
- 0.20: source page content appears, but the lesson objective is mostly lost.
- 0.00: no meaningful evidence for the objective.

Per-objective anchors should be attached to `ObjectiveCell.sufficiency_rule` so the judge and deterministic validator can produce comparable rationales.

### Approval Policy

> **SUPERSEDED (Session 50).** The binary "approve iff … no essential cell < 0.60" below is
> replaced by the **tri-state** policy in `plans/2026-06-13-objective-sufficiency-implementation-plan.md`
> (approve / abstain / reject; per-cell `>=0.65` pass, `0.50–0.65` abstain, `<0.50` reject;
> typed severe-defect veto via 2/3 reject, 1/3 abstain). A hard per-cell floor is fake
> precision on a noisy judge score — see the plan's design block. The lines below are kept for
> rationale only.

Approve only if all are true:

- deterministic blocking gates pass
- deterministic required-form checks pass for essential objectives
- deterministic objective coverage passes with `definition="objective_sufficiency_v1"`
- overall judge score >= 0.70
- no essential objective cell has judge score < 0.60  *(superseded — see banner)*
- no safety/ADHD criterion is < 0.50

Do not use a single hard floor on the old `content_coverage` field. It encourages page fidelity and false rejection of good ADHD-optimized adaptations. Instead, use per-objective essential floors plus deterministic blockers.

## Assessment-Theory Rationale For "Enough"

Backward design supports this shift because coverage is not exposure to every source item; it is evidence that learners practiced the intended result. A worksheet can drop many page tokens and still preserve the lesson if it retains the target objective, the required form, and enough opportunities to respond.

Bloom-style objective taxonomies matter because objectives differ by performance type:

- recognize or read a pattern
- produce or spell a pattern
- manipulate sounds or graphemes
- apply decoding in connected text
- read irregular words automatically

These are not interchangeable. A child reading six CVCe words has not necessarily practiced encoding. A child seeing a chain word in a list has not performed a chain transformation.

Mastery learning supports aligned practice plus corrective feedback rather than passive item coverage. For this product, "enough" means a short worksheet provides adequate opportunities to respond for the objective, within attention and cognitive-load constraints.

Curriculum-based measurement supports sampling because it estimates skill through repeated indicators. A roll-and-read page with 50 words is a fluency pool; a valid adaptation can sample the pool if the sample preserves the target pattern, difficulty range, and response form.

## Structured-Literacy Objective Decomposition

For a phonics pattern lesson such as CVCe/VCe, the ledger should represent at least these possible objective cells:

1. Decoding target pattern.
   - Evidence: reading words that instantiate the target grapheme-phoneme pattern.
   - Required form: isolated words or phrase/sentence reading.
   - Samplable from long lists.

2. Encoding or spelling target pattern.
   - Evidence: writing, spelling, dictation, fill-in, or choosing letters to encode target words.
   - Required form: production or near-production. Recognition-only practice is insufficient.

3. Phoneme/grapheme manipulation.
   - Evidence: word chain, chain script, build/change/delete/substitute task.
   - Required form: executable transformation sequence. A copied list does not satisfy it.

4. Connected-text fluency.
   - Evidence: decodable sentence or passage reading.
   - Required form: connected text. Isolated word cards do not satisfy it.

5. Irregular or sight-word reading.
   - Evidence: practice with lesson-introduced irregular words.
   - Required form: explicit irregular-word practice when present in source or corpus.

6. Contrast discrimination.
   - Evidence: sort, choose, compare, pattern/not-pattern task.
   - Required form: both positive and negative examples, with clear instructions.

## ADHD And Cognitive-Load Sufficiency Priors

Use short, bounded practice sets. The initial priors should be easy to tune:

| Objective | Initial minimum | Initial upper comfort band | Notes |
|---|---:|---:|---|
| Decode target pattern | 6 target words | 10-12 target words | More only when split across chunks or game turns. |
| Encode/spell target pattern | 3 production items | 5-6 production items | Production is slower and more effortful. |
| Word chain | 1 coherent chain, 4-8 steps | 8-10 steps | Can be split into two mini-chains. |
| Connected text | 1 short passage or 2-4 sentences | 1 page chunk | Avoid dense blocks. |
| Irregular words | 2-5 words | 5-7 words | Prioritize new lesson words. |
| Contrast sort | 1 compact sort/choose task | 6-10 options | Contrast should clarify, not swamp the target. |

These are implementation priors, not settled science. The calibration process below should tune them against expert ratings and child-output data when available.

## Calibration Against Human Raters

> **SUPERSEDED (Session 50).** The 15–20-sample plan below is replaced by the sequential
> design in the implementation plan (T11): freeze rubric → ~20 dev set (debug, tunable) →
> **40–60 blind holdout** (promotion gate, not tuned against) with abort rules. Three-bucket
> (approve/abstain/reject) tracking; band width + severe-defect enum calibrated there. The
> outline below is kept for the strata/metrics ideas only.

Cheap validation plan for 15-20 samples:

1. Create a stratified set:
   - 5 clearly good adaptations
   - 5 page-faithful but ADHD-overwhelming adaptations
   - 5 short but objective-thin adaptations
   - 5 mixed edge cases with contrast words, irregular words, and passages

2. Have 2-3 expert raters score:
   - per-objective sufficiency on 0-1
   - required-form preserved yes/no
   - answer-key/artifact blocker yes/no
   - final approve/revise/reject

3. Measure agreement:
   - binary approve/reject: Cohen's kappa for two raters, Fleiss' kappa for three or more
   - ordinal binned scores: weighted kappa after binning 0-1 into five bands
   - continuous 0-1 scores: intraclass correlation or mean absolute error
   - gate quality: confusion matrix for blockers and final approval

4. Tune thresholds:
   - set essential objective floors to match expert "revise/reject" boundaries
   - examine false approvals first, especially answer-key, artifact, and concept-dilution cases
   - only then adjust false rejections

5. Detect gaming:
   - high judge scores with low deterministic role counts indicate verbosity or rationale bias
   - high objective sufficiency with many non-pattern words indicates concept dilution
   - low scores caused by omitted long list items indicate page-fidelity relapse
   - disagreement concentrated in one objective type means the ledger threshold or classifier needs revision

## LLM Judge Construction Notes

The fast-moving LLM-as-judge literature supports caution, not extra authority for the judge. Recent work continues to report bias, sensitivity to rubric wording, and the need for explicit criteria and calibration. Therefore:

- Use analytic criteria, not a single holistic score.
- Hand the judge reference materials and deterministic evidence.
- Keep objective extraction out of the judge.
- Keep deterministic blockers outside the judge.
- Maintain 0-1 scoring for compatibility.
- Use median-of-N judging only as a variance reducer, not as a substitute for deterministic gates.
- Report per-objective scores so humans can debug failures.

Tooling worth buying versus building:

- Build the domain ledger, blockers, and coverage validator in-house. They depend on UFLI routines and your data contracts.
- Buy or use generic eval tooling only for experiment tracking, grader comparison, dataset management, and confusion-matrix reporting.
- Do not buy a generic judge framework expecting it to understand word chains, decodable passages, heart words, or ADHD chunking.

## Implementation Checklist

1. Add `ObjectiveLedger` schema and deterministic builder.
2. Add role-aware word classifier using UFLI corpus plus source metadata.
3. Update planner/adaptation prompt to receive the ledger and preserve required forms.
4. Add `BlockingGateResult` and deterministic blockers.
5. Replace `validate/content_coverage.py` internals with objective-sufficiency evaluation.
6. Update `adapt/llm_judge.py` prompt and schema, mapping old `content_coverage` to `objective_sufficiency` during transition.
7. Update battery scorecard details to display `definition="objective_sufficiency_v1"`.
8. Build 15-20 calibration fixtures and compare to expert human ratings.
9. Tune thresholds based on false approvals before optimizing false rejections.

## Evidence Gaps And Contested Areas

- There is no precise universal dosage threshold for phonics practice in ages 5-8 with ADHD. The proposed counts are conservative engineering priors grounded in instructional design and cognitive-load constraints.
- UFLI corpus metadata may not explicitly label every contrast/review word. The safe fallback is to undercount ambiguous words, not overcredit them.
- Deterministic answer-key checks require machine-readable task metadata. Where the planner cannot emit checkable metadata, the item should be teacher-checked or blocked.
- LLM-judge research is changing quickly. Claims about new judge frameworks, scales, and debiasing methods should be treated as provisional and rechecked before product commitments.

## Corrected And Verified Citation List

Citation validation note: for sources used in this document, I either fetched and read the landing page or source text, or marked the limitation below. I removed recommendations that depended on unverified CS citations. In particular, this plan does not recommend changing the infrastructure from 0-1 scoring to a 0-5 scale.

Education and literacy sources:

- Wiggins and McTighe, Understanding by Design professional development workbook, ASCD. Fetched and read PDF source used for backward-design framing. https://files.ascd.org/staticfiles/ascd/pdf/siteASCD/publications/UbD_WhitePaper0312.pdf
- Vanderbilt Center for Teaching, Bloom's Taxonomy. Fetched and read landing page used for objective-type distinctions. https://cft.vanderbilt.edu/guides-sub-pages/blooms-taxonomy/
- Guskey, "Lessons of Mastery Learning", Educational Leadership. Fetched and read PDF used for mastery-learning framing. https://tguskey.com/wp-content/uploads/Mastery-Learning-2-Lessons-of-Mastery-Learning.pdf
- Hosp, Hosp, and Dole, "Potential Bias in Predictive Validity of Universal Screening Measures Across Disaggregation Subgroups", discussion of CBM. Fetched and read open-access source for CBM sampling logic. https://pmc.ncbi.nlm.nih.gov/articles/PMC4557774/
- UFLI Foundations overview. Fetched and read landing page used for UFLI routine alignment. https://ufli.education.ufl.edu/foundations/
- UFLI Foundations printable resources. Fetched and read landing page used for typed worksheet/routine examples. https://ufli.education.ufl.edu/foundations/toolbox/printable-resources/
- UFLI Foundations Pocket Reference. Fetched and read PDF used for structured routine and lesson component mapping. https://ufli.education.ufl.edu/wp-content/uploads/2024/06/UFLI-Foundations-Pocket-Reference-2024.pdf
- International Dyslexia Association primary pages were not relied on because access was blocked in prior validation; University of Michigan DyslexiaHelp structured literacy page was used as an accessible structured-literacy reference. Fetched and read. https://dyslexiahelp.umich.edu/professionals/dyslexia-school/morphological-awareness/structured-literacy
- What Works Clearinghouse, Foundational Skills to Support Reading for Understanding in Kindergarten Through 3rd Grade. Fetched and read practice-guide page/PDF for explicit foundational-skill instruction. https://ies.ed.gov/ncee/wwc/PracticeGuide/21
- CDC, ADHD in the Classroom. Fetched and read for classroom supports, structure, and reducing distractions. https://www.cdc.gov/adhd/treatment/classroom.html
- Massachusetts DESE, Early Literacy Skills: Fluency and Automaticity. Fetched and read for automaticity framing. https://www.doe.mass.edu/massliteracy/skilled-reading/fluent-word-reading.html
- Tamm et al. / related open-access review on reading interventions for students with ADHD. Fetched and read open-access source for ADHD-reading intervention evidence. https://pmc.ncbi.nlm.nih.gov/articles/PMC7518569/
- UC Berkeley Center for Teaching and Learning, Rubrics. Fetched and read for analytic rubric construction. https://teaching.berkeley.edu/resources/improve/evaluate-course-level-learning/rubrics
- McHugh, "Interrater reliability: the kappa statistic", Biochemia Medica. Fetched and read open-access source for kappa interpretation. https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/

LLM-as-judge and evaluation sources:

- Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", arXiv:2306.05685. Fetched and read arXiv page; used for position, verbosity, and self-enhancement bias cautions. https://arxiv.org/abs/2306.05685
- "Grading Scale Impact on Large Language Model Performance As a Judge", arXiv:2601.03444. Fetched and read arXiv page; used only to support that scale choice can affect judge alignment. Not used to recommend changing this system away from 0-1 scores. https://arxiv.org/abs/2601.03444
- "Autorubric: Unifying Rubric-based LLM Evaluation", arXiv:2603.00077. Fetched and read arXiv page; used for analytic rubrics, ensemble/few-shot calibration, and psychometric reporting context. https://arxiv.org/abs/2603.00077
- "Judging the Judges: A Systematic Investigation of Position, Length, and Style Bias in Pairwise Comparative LLM-as-a-Judge", arXiv:2604.23178. Fetched and read arXiv page; used for current bias and debiasing caution. https://arxiv.org/abs/2604.23178
- Rao et al., "A Checklist for Assessing LLM-as-a-Judge Quality: From Pretesting to Report", arXiv:2606.00093. Fetched and read arXiv page; used for reporting calibration metrics and confusion-matrix style evaluation. https://arxiv.org/abs/2606.00093

Removed or not relied on:

- The earlier draft's unverified or inconsistently dated arXiv IDs were removed unless re-fetched and listed above.
- `Agent-as-a-Judge` was re-fetched as an arXiv page but is not necessary for this implementation spec, so no recommendation hinges on it.
- Any claim that "0-5 grading is best" was removed as a product recommendation. The judge remains 0-1 because the current infrastructure and calibration plan use 0-1 scoring.
