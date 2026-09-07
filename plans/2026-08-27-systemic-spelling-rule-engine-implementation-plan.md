# Systemic Spelling-Rule Engine — Corpus Sweep and Implementation Plan

**Status:** Ready for implementation in a new session. No task in this plan has
been executed yet.

**Date:** 2026-08-27

**Plan of record:** This file supersedes ad hoc per-lesson spelling-rule fixes.
It extends the suffix-only contract work in
`docs/superpowers/plans/2026-07-17-skill-contracts-composed-render.md` without
rewriting that historical plan.

**Required skills for the implementation session:**

- `.agents/skills/skill-preservation/SKILL.md`
- `.agents/skills/data-contracts/SKILL.md` for Tasks 2 and 5
- `.agents/skills/pipeline-stage/SKILL.md` for Tasks 4–6 and 11
- `.agents/skills/adhd-design/SKILL.md` and
  `.agents/skills/print-quality/SKILL.md` for Task 14

## Goal

Replace lesson-specific and string-parsing spelling-rule behavior with one
typed, replayable word-transformation system shared by classification,
deterministic adaptation, LLM-plan translation, objective evidence, blocking
validation, and child-facing instructions.

The completed system must:

1. audit every word-chain source in the local 148-entry UFLI corpus;
2. classify every spelling-rule-labelled lesson into a reviewed contract or an
   explicit, fail-closed exemption;
3. prove mechanically that each generated transformation produces its expected
   answer;
4. use operation-accurate child instructions (substitute, insert, delete,
   prefix, suffix, double, Drop E, or Y to I);
5. never claim “change one letter” unless the exact operation has been verified;
6. preserve decoding, encoding, manipulation, and connected-text objectives;
7. make subsequent rule-family additions contract-data changes rather than new
   `if lesson == ...` or `if skill == ...` branches.

## Why this is systemic

Lesson 109 exposed the defect because `smile → smiled → smiling` fell through to
the ordinary word-chain path and was described as a one-letter change. A corpus
scan then reproduced the same defect class or an incomplete rule description in
neighboring lessons:

| Lesson | Source concept | Current classification / confirmed behavior |
|---|---|---|
| 99 | Suffixes; `-s/-es` | Generic slug; says `cloud → clouds` is a one-letter change |
| 103 | Prefix `un-` | Generic slug; prefixing is routed through a letter-chain fallback |
| 104 | Prefixes `pre-/re-` | Generic slug; base-anchored prefix chains are unsupported |
| 105 | Prefix `dis-` | Generic slug; prefixing is routed through a letter-chain fallback |
| 107 | Doubling `-ed/-ing` | Misclassified as `cvc_blending`; one-letter claim is false |
| 108 | Doubling `-er/-est` | Classified as suffix addition but omits consonant doubling |
| 109 | Drop E | Locally fixed with dedicated branches; not yet generalized |
| 110 | Y to I | Generic slug; generated `dries → dried (change s to d)` |
| 119–128 | Later affixes | Several collide with grapheme classifiers or generic slugs |

The existing skill-contract plan explicitly left Lessons 107–108 outside its
scope. This plan closes that boundary and audits the full corpus instead of
assuming the nearby lesson list is exhaustive.

## Non-negotiable invariants

### Skill preservation

- Phonics/morphology stays in the phonics domain.
- Written transformation tasks remain written production; a recognition task
  may not satisfy encoding.
- A worked example never replaces the only independent production item for an
  essential objective.
- Objective-sufficiency sampling remains allowed; the repair does **not** restore
  exhaustive page fidelity.
- A target word may count only when it is visible practice or expected student
  production, never merely an answer-key surface.

### Correctness and fail-closed behavior

- `replay(step.operations, step.from_word) == step.to_word` is mandatory before
  a transformation can be rendered as verified practice.
- Unsupported/ambiguous chains are explicit data with a reason. They render
  neutrally or block an essential manipulation objective; they never receive a
  fabricated operation explanation.
- “Change one letter” requires an equal-length pair with exactly one verified
  grapheme substitution. Insertions, deletions, prefixes, suffixes, and spelling
  rules get their own language.
- The deterministic path and LLM path must call the same compiler.
- Validators consume typed transformation data. Parsing child-facing prose is a
  compatibility fallback only, never the primary evidence path.

### Repository and corpus safety

- Do not commit raw UFLI passages, full word lists, or full source chains.
- Local corpus audit output belongs under `artifacts/spelling_rule_audit/`.
- CI fixtures use synthetic/minimal examples. A committed aggregate audit may
  contain lesson IDs, contract IDs, counts, and statuses, but not redistributed
  curriculum content.
- Preserve the unrelated untracked file
  `docs/superpowers/plans/2026-07-17-skill-contracts-composed-render.md` unless
  the owner separately authorizes staging it.

## Target architecture

```text
concept label + SourceItem(word_chain)
              |
              v
     SkillContract registry
     - classification patterns
     - chain anchoring policy
     - allowed affixes
     - operation recipe
     - learner goal / sufficiency facts
              |
              v
     Transformation analyzer
     -> verified TransformationStep[]
     -> or explicit UnsupportedTransformation
              |
       +------+------------------+
       |                         |
       v                         v
deterministic adapter       LLM plan translator
       |                         |
       +----------+--------------+
                  v
       shared transformation compiler
       -> ActivityItem(transformation=...)
                  |
       +----------+--------------------+
       |          |                    |
       v          v                    v
    renderer   objective evidence   blocking gates
```

### Typed intermediate representation

Task 2 will finalize field names, but the behavioral contract is:

```python
OperationKind = Literal[
    "substitute_grapheme",
    "insert_grapheme",
    "delete_grapheme",
    "prepend_affix",
    "append_affix",
    "drop_final_e",
    "double_final_consonant",
    "change_y_to_i",
]

class TransformationOperation(BaseModel):
    kind: OperationKind
    value: str | None = None
    index: int | None = None
    old: str | None = None
    new: str | None = None

class TransformationStep(BaseModel):
    rule_id: str
    source_chain: str
    step_index: int
    base_word: str
    from_word: str
    to_word: str
    ending: str | None = None
    operations: list[TransformationOperation]
    verification_status: Literal["verified", "unsupported"]
    verification_reason: str | None = None
```

`SourceItem` gains `transformations: list[TransformationStep] = []` and
`ActivityItem` gains `transformation: TransformationStep | None = None`.
Defaults preserve old JSON artifacts and photo-path compatibility.

## Contract scope

The inventory, not this preliminary list, is authoritative. The initial
registry must nevertheless account for:

- genuine grapheme substitution/insertion/deletion word chains;
- plain suffix addition, including existing `-er/-est`, `-ly`, `-less/-ful`,
  and `-ness` contracts;
- plural `-s/-es`;
- plain prefix addition (`un-`, `pre-`, `re-`, `dis-`, `bi-`, `tri-`, `uni-`);
- later suffixes/word parts (`-sion/-tion`, `-ture`, `-er/-or/-ist`, `-ish`,
  `-y`, `-ment`, `-able/-ible`);
- consonant doubling before suffixes;
- Drop E before suffixes;
- Y to I before eligible suffixes;
- mixed affix review lessons, where each step may resolve to a different
  registered contract;
- FLSZ and review/exception concepts as reviewed pattern contracts or explicit
  non-transformation exemptions.

## Red–green–refactor protocol

Every task below is one independently working block and one git checkpoint.

For every task:

1. Write the named test(s) first.
2. Run the focused command and capture the expected failure. The failure must be
   behavioral, not a syntax/import mistake unless the task creates a new module.
3. Implement the minimum production change.
4. Re-run the focused command until green.
5. Refactor only while the focused tests remain green.
6. Run `make lint`, `make typecheck`, and `make test` before committing. Run
   `make test-golden` whenever rendering or complete-pipeline behavior changes.
7. Commit only that block. Do not squash during implementation.
8. Record the commit hash and red/green evidence in
   `.claude/worksheet-project-context.md` before leaving the session.

If a task described as a contract-data-only addition requires changes to the
analyzer/compiler, stop. Add a failing general operation test to the earlier
abstraction, repair the abstraction in its own checkpoint, then resume. Do not
hide an abstraction gap inside a lesson contract.

## Git starting point and checkpoint policy

The planning session ended on:

- branch: `refound/skill-contracts-composed-render`
- HEAD: `a033d8b`
- `main`: `fdb1995`
- current branch already contains the suffix-contract registry required by this
  plan and is therefore the intended base;
- Lesson 109 fixes, this plan, and the handoff are uncommitted because the
  current environment cannot create `.git/index.lock`.

The implementation session must not start from `main` and silently lose the
contract work. Perform Task 0 exactly, then create:

```bash
git checkout -b feature/systemic-spelling-rule-engine
```

Checkpoint commits are mandatory. Suggested messages are included per task.
Do not merge or rebase onto `main` until the final owner review.

---

## Task 0 — Preserve the known-good Drop-E baseline and create the feature branch

**Purpose:** Begin from a reproducible green state without mixing the existing
Lesson 109 repair, planning documents, or the systemic implementation.

**Expected working-tree facts:**

- modified Drop-E/adaptation/validation files listed in the session handoff;
- new `tests/test_drop_e_rule.py`;
- this plan and the updated handoff;
- unrelated untracked historical plan left untouched.

### Red/baseline verification

This task does not add a new test. It verifies the already-captured baseline:

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
.venv/bin/pytest tests/test_drop_e_rule.py tests/test_story_format.py \
  tests/test_validate.py tests/test_render.py -q
make lint
make typecheck
make test
```

Expected: targeted tests green; full suite `917 passed` or higher; lint and mypy
green. If the count differs, diagnose the difference rather than editing the
plan to match it.

### Checkpoint A — existing Lesson 109 behavior

Stage only the Lesson 109 production/tests listed by `git diff --stat`; exclude
this plan, the handoff, generated PDFs, and the unrelated untracked plan.

```bash
git add adapt/ render/pdf.py skill/ tests/ validate/
git commit -m "fix: model Drop-E spelling transformations truthfully"
```

Review the staged diff before committing; do not accidentally stage unrelated
changes elsewhere in those directories.

### Checkpoint B — plan and handoff

```bash
git add plans/2026-08-27-systemic-spelling-rule-engine-implementation-plan.md \
  .claude/worksheet-project-context.md
git commit -m "docs: plan systemic spelling-rule engine repair"
```

### Branch checkpoint

```bash
git checkout -b feature/systemic-spelling-rule-engine
git rev-parse --short HEAD
git status --short
```

Expected: clean tracked tree; only the explicitly preserved unrelated untracked
file may remain.

---

## Task 1 — Build an independent corpus transformation audit

**Purpose:** Characterize the whole defect surface before changing production
classification. The audit is an independent oracle; it must not call the new
production analyzer introduced later.

**Files:**

- Create `experiments/spelling_rule_audit.py`
- Create `tests/test_spelling_rule_audit.py`
- Create local output `artifacts/spelling_rule_audit/before.json` (not committed)

**Interfaces:**

- `split_arrow_chain(text: str) -> list[str]`
- `structural_pair_facts(left: str, right: str) -> PairFacts`
- `audit_skill(skill: LiteracySkillModel) -> LessonTransformationAudit`
- `audit_corpus(data_path: Path) -> CorpusTransformationAudit`
- CLI: `python -m experiments.spelling_rule_audit --data-dir data/ufli --output ...`

The independent audit records equal length, edit distance, common prefix/suffix,
prefix/suffix additions, and whether current learner-facing behavior would be
allowed to claim a single substitution. It need not infer every pedagogical
rule.

### RED

Write synthetic tests proving the current defect signatures are detectable:

- `cloud → clouds` is not a one-letter substitution;
- `skip → skipped` is not a one-letter substitution;
- `smile → smiling` includes removal/addition, not substitution;
- `dries → dried` is not evidence that the rule is “change s to d”;
- `cry → try` is a valid one-grapheme substitution;
- `pace → space` is a one-grapheme insertion, not substitution.

Run:

```bash
.venv/bin/pytest tests/test_spelling_rule_audit.py -v
```

Expected RED: missing module/interfaces.

### GREEN

Implement the audit models and CLI. Run the local corpus sweep:

```bash
.venv/bin/python -m experiments.spelling_rule_audit \
  --data-dir data/ufli \
  --output artifacts/spelling_rule_audit/before.json
```

The report must contain:

- total corpus records;
- lessons and source items containing arrow chains;
- total pairs;
- structurally valid substitutions/insertions/deletions/affix-like additions;
- pairs the current pipeline cannot truthfully describe;
- concept labels containing `rule`, `suffix`, `prefix`, `affix`, or explicit
  hyphenated word parts;
- lesson IDs requiring a reviewed contract/exemption.

Manually compare the report with known Lessons 99, 107, 108, 109, and 110. Do
not hardcode the totals into production code.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_spelling_rule_audit.py -v
make lint && make typecheck && make test
git add experiments/spelling_rule_audit.py tests/test_spelling_rule_audit.py
git commit -m "test: add corpus-wide word-transformation audit"
```

Do not commit `before.json`.

---

## Task 2 — Add the typed transformation data contract and replay engine

**Purpose:** Establish the semantic unit shared by all later paths before adding
any lesson contracts.

**Files:**

- Modify `skill/schema.py`
- Create `skill/transformation.py`
- Modify `adapt/schema.py`
- Create `tests/test_transformation_model.py`

**Required behavior:**

- Pydantic validates every operation and transformation step.
- `replay_operations(from_word, operations)` deterministically returns a word or
  a typed verification failure.
- `verify_step(step)` returns verified only when replay equals `to_word`.
- Unsupported steps carry a non-empty reason and no false verified flag.
- Old `SourceItem` and `ActivityItem` JSON without the new fields still parses.
- Model JSON round-trips byte-stably for the same input.

### RED

Add one test per operation kind:

- substitute: `cry → try`;
- insert: `pace → space`;
- delete: a synthetic one-grapheme deletion;
- prepend affix: `safe → unsafe`;
- append affix: `cloud → clouds`;
- Drop E + append: `smile → smiling`;
- double consonant + append: `skip → skipped`;
- Y to I + append: `happy → happier`.

Also add negative tests:

- wrong target fails verification;
- missing operation parameters fail schema validation;
- old schema payloads remain valid.

Run:

```bash
.venv/bin/pytest tests/test_transformation_model.py -v
```

Expected RED: missing models/module.

### GREEN

Implement only pure data/replay behavior. Do not touch taxonomy, adaptation, or
lesson behavior in this task.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_transformation_model.py -v
make lint && make typecheck && make test
git add skill/schema.py skill/transformation.py adapt/schema.py \
  tests/test_transformation_model.py
git commit -m "feat: add replayable word-transformation contract"
```

---

## Task 3 — Generalize the skill-contract registry

**Purpose:** Move rule identity, classification patterns, anchoring, operation
recipes, goals, and judge sufficiency facts into correctness-as-data.

**Files:**

- Modify `skill/contract.py`
- Modify `tests/test_skill_contract.py`
- Create `tests/test_transformation_contract.py`

**Contract fields:**

- stable `skill_id` / `rule_id`;
- concept patterns and priority;
- family (`letter_chain`, `prefix`, `suffix`, `orthographic_rule`, `review`,
  `pattern_only`);
- chain anchoring (`sequential`, `base_anchored`, `per_step_infer`);
- allowed prefixes/endings;
- ordered operation recipe or permitted recipes;
- child-facing goal and operation label;
- manipulation sufficiency wording;
- whether written production is essential;
- optional exception policy.

Keep `SuffixContract`, `SUFFIX_CONTRACTS`, `known_suffix_tokens()`, and
`contract_for_skill()` backward-compatible until all callers migrate. A
compatibility façade may delegate to the generalized registry.

### RED

Tests must require:

- unique rule IDs;
- no duplicate normalized concept pattern at equal priority;
- deterministic longest/priority matching;
- every operation named by a contract is supported by Task 2;
- every transformation contract has a goal and sufficiency rule;
- existing suffix goals and sufficiency strings remain byte-identical;
- unknown contracts return `None` rather than guessing.

Use synthetic contracts first. Do not register all corpus families yet.

### GREEN

Implement the generalized model/registry and compatibility façade. Migrate the
existing plain suffix contracts without behavior change.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_skill_contract.py \
  tests/test_transformation_contract.py -v
make lint && make typecheck && make test
git add skill/contract.py tests/test_skill_contract.py \
  tests/test_transformation_contract.py
git commit -m "refactor: generalize skill contracts for word transformations"
```

---

## Task 4 — Implement contract-driven chain analysis

**Purpose:** Convert arrow strings into verified typed steps without rendering
or objective logic.

**Files:**

- Modify `skill/transformation.py`
- Create `tests/test_transformation_analyzer.py`

**Interfaces:**

- `analyze_pair(left, right, contract, *, base_word) -> TransformationStep`
- `analyze_chain(text, contract) -> list[TransformationStep]`
- `analyze_chain_with_registry(text, skill_id) -> list[TransformationStep]`

**Required behavior:**

- sequential chains use each preceding word as `from_word`;
- base-anchored chains compare every derived form with the first word;
- review contracts may select a permitted recipe per pair;
- rule-specific analysis validates surface results; it never assumes the rule
  solely because the concept label says so;
- ambiguous or invalid pairs become unsupported steps with reasons;
- step ordering is stable and source text is preserved for provenance.

### RED

Parametrize synthetic chains for:

- substitution, insertion, and deletion;
- plain prefix and suffix;
- base-anchored multi-affix chains;
- doubling, Drop E, and Y to I;
- an invalid Drop-E pair;
- an affix-review chain with two different operations;
- duplicated source chains (analysis remains deterministic; deduplication is a
  later consumer decision).

### GREEN

Implement the analyzer solely against Task 2 operations and Task 3 contracts.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_transformation_model.py \
  tests/test_transformation_analyzer.py -v
make lint && make typecheck && make test
git add skill/transformation.py tests/test_transformation_analyzer.py
git commit -m "feat: analyze word chains into verified operations"
```

---

## Task 5 — Make classification and skill extraction contract-driven

**Purpose:** Give rule/affix concepts canonical IDs before adaptation, and attach
typed transformations to word-chain source items.

**Files:**

- Modify `skill/taxonomy.py`
- Modify `skill/lesson_loader.py`
- Modify `skill/extractor.py`
- Modify `skill/schema.py` if Task 2’s attachment point needs final adjustment
- Create `tests/test_spelling_rule_classification.py`
- Extend `tests/test_lesson_loader.py`
- Extend `tests/test_skill.py`

### RED

Synthetic tests must cover canonical classification for:

- `Suffixes; -s/-es`;
- `Prefixes; un-`, `pre-, re-`, and `dis-`;
- doubling with `-ed/-ing` and `-er/-est`;
- Drop E;
- Y to I;
- later affix concepts `-sion/-tion`, `-ture`, `-er/-or/-ist`, `-ish`, `-y`,
  `-ment`, `-able/-ible`, and `bi-/tri-/uni-`;
- affix review labels;
- r-controlled/vowel-team labels that contain short substrings such as `er` but
  must **not** become morphology.

Corpus-local tests (skip when `data/ufli/normalized.jsonl` is absent) must snapshot
the exact intended lesson-ID-to-skill-ID map for the affected range and fail on
any unexpected classification delta outside the reviewed set.

Add extraction tests requiring word-chain `SourceItem.transformations` to contain
verified steps or explicit unsupported steps.

### GREEN

Match generalized contracts before short grapheme patterns. Preserve the
existing longest/priority collision safeguards. Enrich both the lesson loader
and photo extraction path through one helper; do not duplicate classification
or chain analysis.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_spelling_rule_classification.py \
  tests/test_lesson_loader.py tests/test_skill.py -v
make lint && make typecheck && make test
git add skill/taxonomy.py skill/lesson_loader.py skill/extractor.py \
  skill/schema.py tests/test_spelling_rule_classification.py \
  tests/test_lesson_loader.py tests/test_skill.py
git commit -m "feat: classify and extract spelling-rule transformations"
```

Record the exact corpus classification delta in the handoff.

---

## Task 6 — Build the shared transformation activity compiler and safe fallback

**Purpose:** Render verified semantic operations into truthful child tasks once,
then reuse that compiler in every authoring path.

**Files:**

- Create `adapt/transformation_compiler.py`
- Modify `adapt/engine.py`
- Create `tests/test_transformation_compiler.py`
- Extend `tests/test_adapt.py`

**Interfaces:**

- `instruction_steps_for(step) -> list[Step]`
- `worked_example_for(step) -> Example`
- `activity_item_for(step, item_id) -> ActivityItem`
- `compile_transformation_chunk(steps, rules, ...) -> ActivityChunk | None`
- `neutral_chain_item(chain, reason, ...) -> ActivityItem` for nonessential or
  explicitly reviewed unsupported chains.

**Required child language:**

- substitution names the actual old/new grapheme;
- insertion says add the grapheme at the verified location;
- deletion says remove it;
- prefix/suffix says add the named word part;
- doubling says double the final consonant, then add the ending;
- Drop E says drop final e, then add the ending;
- Y to I says change final y to i, then add the eligible ending.

Items remain written production and hide the expected answer. The typed
transformation is attached to the `ActivityItem`.

### RED

Tests must assert exact instructions, hidden answers, replay-valid answers, and
metadata/typed-step preservation for every operation family. Add the invariant:

```python
if "change one letter" in rendered_text.lower():
    assert exactly_one_equal_length_substitution(step)
```

Add a test proving an unsupported essential chain does not become a fabricated
write task.

### GREEN

Route the deterministic engine’s word-chain construction through the compiler.
Keep compatibility wrappers temporarily if unrelated tests import the old
private parsers; mark them for removal in Task 9.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_transformation_compiler.py tests/test_adapt.py -v
make lint && make typecheck && make test && make test-golden
git add adapt/transformation_compiler.py adapt/engine.py \
  tests/test_transformation_compiler.py tests/test_adapt.py
git commit -m "feat: compile verified transformations into child activities"
```

---

## Task 7 — Register plain prefix, suffix, and mixed-affix families as data

**Purpose:** Prove the abstraction covers the broad morphology surface without
new engine branches.

**Files:**

- Modify `skill/contract.py`
- Extend `tests/test_transformation_contract.py`
- Create `tests/test_affix_lesson_matrix.py`

**Scope:** Lessons/families represented by 99–106 and 119–128, excluding the
orthographic rules handled in Tasks 8–10.

### RED

Matrix tests require correct goals, anchoring, operations, and truthful prompts
for synthetic equivalents of:

- suffix `-s/-es`;
- prefixes `un-`, `pre-/re-`, `dis-`, `bi-/tri-/uni-`;
- existing suffixes `-er/-est`, `-ly`, `-less/-ful`, `-ness`;
- later word parts `-sion/-tion`, `-ture`, `-er/-or/-ist`, `-ish`, `-y`,
  `-ment`, `-able/-ible`;
- mixed affix review.

Each test must assert that the produced item remains written production and that
replaying its typed operations yields the hidden answer.

### GREEN

Add contracts and fixtures only. If production analyzer/compiler code must
change, stop and follow the abstraction-gap rule above.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_transformation_contract.py \
  tests/test_affix_lesson_matrix.py -v
make lint && make typecheck && make test
git diff --stat HEAD -- skill/ adapt/
```

Expected production diff: contract data only (plus tests). Commit:

```bash
git add skill/contract.py tests/test_transformation_contract.py \
  tests/test_affix_lesson_matrix.py
git commit -m "feat: register prefix suffix and affix-review contracts"
```

---

## Task 8 — Register consonant-doubling rules as data

**Purpose:** Fix Lessons 107–108 without adding another special-case engine.

**Files:**

- Modify `skill/contract.py`
- Create `tests/test_doubling_rule.py`

### RED

Require:

- `skip → skipped` = double `p`, append `ed`;
- `skip → skipping` = double `p`, append `ing`;
- `flat → flatter` = double `t`, append `er`;
- `flat → flattest` = double `t`, append `est`;
- worked examples and independent items explicitly say to double;
- no item calls the operation a one-letter substitution;
- ineligible/mismatched targets become unsupported rather than “verified.”

Corpus-local assertions cover Lessons 107 and 108 end to end.

### GREEN

Register `doubling_ed_ing` and `doubling_er_est` contract data. No analyzer or
compiler branch is allowed in this task.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_doubling_rule.py -v
make lint && make typecheck && make test
git diff --stat HEAD -- skill/ adapt/
git add skill/contract.py tests/test_doubling_rule.py
git commit -m "feat: add consonant-doubling rule contracts"
```

---

## Task 9 — Migrate Drop E from special branches into the general engine

**Purpose:** Preserve the accepted Lesson 109 output while deleting the need for
Drop-E-specific adaptation and validation branches.

**Files:**

- Modify `skill/contract.py`
- Modify `adapt/engine.py`
- Modify `adapt/llm_adapt.py`
- Modify `adapt/objective_ledger.py`
- Modify `validate/objective_coverage.py`
- Extend `tests/test_drop_e_rule.py`
- Extend `tests/test_transformation_compiler.py`

### RED

Before deleting anything, strengthen the Lesson 109 tests to snapshot semantic
behavior rather than private helper names:

- canonical `drop_e_rule` classification;
- verified base-anchored steps;
- suffix coverage across `ed`, `ing`, `er`, `est`;
- truthful instructions and worked example;
- hidden written answers;
- manipulation and encoding coverage pass;
- compact two-worksheet package behavior remains unchanged;
- no generic discovery/copy family is reintroduced.

Run tests once while old branches still exist; they should pass. Then add a
registry assertion that initially fails because Drop E is not yet represented by
the generalized contract.

### GREEN/refactor

Register Drop E in the general registry. Route all callers through the analyzer
and compiler. Remove or reduce:

- `_parse_drop_e_chain_steps`;
- `_drop_e_step_item`;
- Drop-E-only planner translation branches;
- validator special cases that typed transformation evidence replaces.

Keep lesson-level dosage decisions separate from transformation semantics; a
small Drop-E package may remain a skill policy if its objective evidence still
supports that decision.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_drop_e_rule.py \
  tests/test_transformation_compiler.py tests/test_objective_coverage.py -v
make lint && make typecheck && make test && make test-golden
rg -n "_parse_drop_e_chain_steps|_drop_e_step_item" adapt validate skill
```

Expected final `rg`: no production caller; delete dead helpers when safe.

```bash
git add skill/contract.py adapt/engine.py adapt/llm_adapt.py \
  adapt/objective_ledger.py validate/objective_coverage.py \
  tests/test_drop_e_rule.py tests/test_transformation_compiler.py
git commit -m "refactor: migrate Drop-E to the transformation engine"
```

---

## Task 10 — Register Y-to-I as data

**Purpose:** Fix Lesson 110 and prove another spelling-change family can be
added without engine code.

**Files:**

- Modify `skill/contract.py`
- Create `tests/test_y_to_i_rule.py`

### RED

Require:

- `dry → dries` = change final y to i, append `es`;
- `dry → dried` = change final y to i, append `ed`;
- `happy → happier/happiest` = change y to i, append `er/est`;
- `lady → ladies` = change y to i, append `es`;
- the old `dries → dried (change s to d)` explanation is impossible;
- unsupported suffix contexts (notably cases where y should remain before
  `-ing`) do not apply this contract blindly.

Corpus-local tests cover Lesson 110 end to end.

### GREEN

Add contract data only.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_y_to_i_rule.py -v
make lint && make typecheck && make test
git diff --stat HEAD -- skill/ adapt/
git add skill/contract.py tests/test_y_to_i_rule.py
git commit -m "feat: add Y-to-I spelling-rule contract"
```

---

## Task 11 — Route LLM planning and plan translation through the same contracts

**Purpose:** Prevent the default AI path from bypassing the deterministic repair.

**Files:**

- Modify `adapt/llm_planner.py`
- Modify `adapt/llm_adapt.py`
- Extend `tests/test_llm_planner.py`
- Extend `tests/test_llm_adapt.py`

### RED

Tests require:

- planner guidance is rendered from the objective’s resolved contract;
- hardcoded Drop-E/suffix/letter-chain examples are replaced by contract-derived
  operation guidance or a small generic structural example;
- model-authored `word_chain` items remain ignored; arrow words are analyzed by
  the shared analyzer;
- planned doubling, Drop-E, Y-to-I, prefix, and suffix chains compile to the same
  typed steps/items as deterministic adaptation;
- an unsupported planned chain is rejected/falls back rather than converted to
  free-form prose;
- coverage-retry feedback names the missing verified form, not a generic chain.

### GREEN

Use the contract registry and `adapt/transformation_compiler.py` in both plan
translation and retry guidance. Do not implement a second operation parser in
the LLM module.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_llm_planner.py tests/test_llm_adapt.py -v
make lint && make typecheck && make test
git add adapt/llm_planner.py adapt/llm_adapt.py \
  tests/test_llm_planner.py tests/test_llm_adapt.py
git commit -m "fix: enforce transformation contracts in the LLM path"
```

---

## Task 12 — Make objective evidence and blocking gates semantic

**Purpose:** Validate the same typed facts used to generate the worksheet instead
of reverse-engineering correctness from display strings.

**Files:**

- Modify `adapt/objective_ledger.py`
- Modify `validate/objective_coverage.py`
- Modify `validate/blocking_gates.py`
- Extend `tests/test_objective_ledger.py`
- Extend `tests/test_objective_coverage.py`
- Extend `tests/test_blocking_gates.py`

### RED

Add tests requiring:

- manipulation sufficiency wording comes from the resolved contract;
- typed verified steps satisfy manipulation in their contract-defined form;
- unsupported/unverified steps never satisfy manipulation;
- expected written output satisfies encoding without turning arbitrary answer
  keys into student practice;
- blocking gate rejects a transformation when replay does not equal its answer;
- blocking gate rejects a child-facing operation claim inconsistent with the
  typed operation;
- base-anchored chains preserve correct sequence evidence;
- old artifacts without typed transformations retain the conservative legacy
  compatibility path.

### GREEN

Prefer `ActivityItem.transformation`. Keep string stitching only for legacy
artifacts and mark it clearly. Do not loosen required-form thresholds to make
new packages pass.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_objective_ledger.py \
  tests/test_objective_coverage.py tests/test_blocking_gates.py -v
make lint && make typecheck && make test
git add adapt/objective_ledger.py validate/objective_coverage.py \
  validate/blocking_gates.py tests/test_objective_ledger.py \
  tests/test_objective_coverage.py tests/test_blocking_gates.py
git commit -m "fix: validate manipulation from typed transformations"
```

---

## Task 13 — Add the corpus completeness gate and before/after report

**Purpose:** Prove the systemic surface is covered and prevent a future rule
family from silently falling back.

**Files:**

- Extend `experiments/spelling_rule_audit.py`
- Extend `tests/test_spelling_rule_audit.py`
- Create `tests/fixtures/spelling_rules/synthetic_rule_matrix.json`
- Create `docs/research/2026-08-27-spelling-rule-corpus-audit-summary.md`
- Create local `artifacts/spelling_rule_audit/after.json` (not committed)

### RED

Add a test that fails while any synthetic rule-labelled concept lacks a
contract. Add a corpus-local test with these assertions:

- every rule/affix-labelled lesson is contract-resolved or listed in a reviewed
  exemption table with a reason;
- every arrow-chain pair has a verified operation or explicit unsupported
  status;
- zero item is eligible for a “one-letter” claim without an exact equal-length
  substitution;
- all expected affected lesson IDs use the intended canonical skill ID;
- unexpected new/unclassified concept labels fail with their IDs in the error.

### GREEN

Run:

```bash
.venv/bin/python -m experiments.spelling_rule_audit \
  --data-dir data/ufli \
  --output artifacts/spelling_rule_audit/after.json \
  --compare artifacts/spelling_rule_audit/before.json
```

Write a committed summary containing aggregate counts, contract IDs, reviewed
lesson IDs, explicit exemptions, and remaining unsupported counts. Do not copy
full source chains or passages into the summary/fixture.

The desired result is zero false claims and 100% rule-label disposition. It is
acceptable for a genuinely ambiguous chain to remain unsupported only when it
is explicit, cannot satisfy an essential objective, and is documented for human
review.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_spelling_rule_audit.py -v
make lint && make typecheck && make test
git add experiments/spelling_rule_audit.py tests/test_spelling_rule_audit.py \
  tests/fixtures/spelling_rules/synthetic_rule_matrix.json \
  docs/research/2026-08-27-spelling-rule-corpus-audit-summary.md
git commit -m "test: enforce corpus-wide transformation completeness"
```

---

## Task 14 — End-to-end package and print regressions

**Purpose:** Verify that semantic correctness survives adaptation, dosage,
theming, review, and PDF rendering.

**Files:**

- Create `tests/test_spelling_rule_e2e.py`
- Extend `tests/test_render.py` only if a renderer regression is found
- No production change without a new focused RED test

### RED

Create CI-safe synthetic `LiteracySkillModel` fixtures for:

- genuine letter substitution;
- prefix and suffix addition;
- consonant doubling;
- Drop E;
- Y to I;
- mixed affix review;
- unsupported essential transformation.

For each supported fixture, assert:

- skill/domain parity;
- required written-production format;
- objective coverage pass;
- blocking gates pass;
- ADHD section/item/time bounds pass;
- PDF renders with searchable text and no missing-glyph box;
- hidden expected answers do not appear as visible answer-key text.

For the unsupported fixture, assert fail-closed behavior before rendering or a
neutral non-manipulation task that cannot satisfy the essential manipulation
cell.

Add corpus-local end-to-end tests (skip in CI without corpus) for representative
Lessons 99, 103, 107, 108, 109, 110, 121, 127, and 128.

### GREEN

Fix only defects exposed by these cross-layer tests, one RED regression at a
time. If more than one production concern appears, make separate commits rather
than hiding them in the test checkpoint.

### Gates and checkpoint

```bash
.venv/bin/pytest tests/test_spelling_rule_e2e.py -v
make lint
make typecheck
make test
make test-golden
git diff --check
git add tests/test_spelling_rule_e2e.py tests/test_render.py
git commit -m "test: cover spelling-rule packages end to end"
```

If production fixes were needed, commit each fix immediately before the final
test-only checkpoint with a precise `fix:` message and its focused regression.

---

## Task 15 — Owner-gated live acceptance matrix

**Purpose:** Exercise the default planner/reviewer path without conflating
spelling-rule correctness with image-generation variance.

**Cost/network:** Live API calls. Confirm credentials and owner authorization at
the start of this task. Use `pdf_classic` first so adaptation is isolated from
image rendering.

**Output root:** `output/systemic_spelling_rule_acceptance/` (not committed).

### Matrix

Run at least Lessons 99, 103, 107, 108, 109, 110, 121, 127, and 128 with
`profiles/ian.yaml`, one calm theme, and `--render-mode pdf_classic`. Do **not**
set `WORKSHEET_LLM_ADAPT=0`; this task must test the normal lesson planner path.

Example command per lesson:

```bash
.venv/bin/python transform.py \
  --lesson 107 \
  --profile profiles/ian.yaml \
  --theme geometry_dash \
  --output output/systemic_spelling_rule_acceptance/lesson107 \
  --render-mode pdf_classic
```

### Acceptance per lesson

- canonical skill/contract ID in `artifacts/skill_model.json`;
- all transformation steps replay verified;
- blocking gates pass;
- objective manipulation and encoding cells pass;
- AI review does not rewrite operation semantics;
- objective judge reports no severe manipulation/answer-correctness defect;
- learner-facing examples and independent items name the correct operation;
- rendered text contains no false “one letter” claim.

An overall judge rejection caused only by an unrelated connected-text/density
criterion does not falsify this repair, but it must be recorded honestly and may
not hide a manipulation defect.

After the `pdf_classic` matrix passes, run the default `image_gen` renderer for
one simple-affix lesson and one spelling-change lesson to prove renderer parity.
Visually inspect every page. Do not promote a renderer default in this plan.

### Report and checkpoint

Create `docs/research/2026-08-27-spelling-rule-live-acceptance.md` with commands,
artifact paths, per-lesson outcomes, judge fields, and any unrelated blockers.
Do not commit generated PDFs or raw proprietary content.

```bash
git add docs/research/2026-08-27-spelling-rule-live-acceptance.md
git commit -m "docs: record spelling-rule live acceptance matrix"
```

If a live defect appears, first add a focused RED test to the owning earlier
task, make a separate fix checkpoint, rerun that lesson, then update the report.

---

## Task 16 — Final audit, handoff, and merge-readiness checkpoint

**Purpose:** Close the feature with reproducible evidence and no hidden working
tree changes.

### Full gates

```bash
make format
make lint
make typecheck
make test
make test-golden
git diff --check
git status --short
```

Run the audit comparison again and ensure it matches the committed summary.

### Structural exit checks

```bash
rg -n "one letter changes each time|Change the letter shown" adapt skill validate
rg -n "_parse_drop_e_chain_steps|_drop_e_step_item" adapt skill validate
rg -n "lesson_number\s*==\s*(99|10[3-9]|110|12[1-8])" adapt skill validate
```

Expected:

- any one-letter language is guarded by a verified substitution;
- no active Drop-E-only parser/compiler remains;
- no lesson-number conditional implements pedagogy;
- family additions reside in contract data;
- deterministic and LLM paths import the same analyzer/compiler.

### Final review checklist

- Review `git diff <branch-base>...HEAD` for contract/engine duplication.
- Confirm old JSON artifacts still parse.
- Confirm photo workflow remains compatible.
- Confirm no raw UFLI content was committed.
- Confirm all local-only/skipped corpus tests were actually run in the owner
  environment.
- Confirm each task has a distinct green commit.
- Update `.claude/worksheet-project-context.md` with the commit table, audit
  totals, live matrix, unresolved exemptions, and exact next action.

### Final checkpoint

```bash
git add .claude/worksheet-project-context.md
git commit -m "docs: hand off systemic spelling-rule engine"
git log --oneline --decorate --max-count=25
git status --short
```

Do not merge to `main` without owner review. The current branch depends on the
unmerged `refound/skill-contracts-composed-render` work, so the merge strategy
must account for that ancestry explicitly.

## Exit criteria

The feature is ready for owner review only when all are true:

- [ ] All corpus word chains were audited locally.
- [ ] Every spelling-rule/affix-labelled lesson has a contract or reviewed
      fail-closed exemption.
- [ ] Every rendered transformation replays to its expected answer.
- [ ] No false one-letter/substitution claims remain.
- [ ] Lessons 99, 107, 108, 109, and 110 have focused red/green regressions.
- [ ] Prefix, later suffix, and mixed-review families have matrix coverage.
- [ ] Deterministic and LLM paths share the compiler.
- [ ] Objective evidence and blocking gates use typed steps.
- [ ] Skill-preservation invariants pass for decoding, encoding, manipulation,
      and connected text.
- [ ] Full pytest, Ruff, mypy, golden tests, and print checks pass.
- [ ] Owner-gated live matrix has no manipulation or answer-correctness severe
      defects.
- [ ] Before/after audit and live acceptance summaries are committed without raw
      curriculum content.
- [ ] Every working block is a separate green git checkpoint.

## Stop conditions

Stop and ask the owner rather than silently broadening scope if:

- corpus audit reveals a transformation family not expressible by the operation
  model;
- classification changes outside the reviewed lesson set;
- a supposedly data-only contract needs engine branching;
- preserving a source objective conflicts with the learner workload budget;
- a contract would require committing proprietary curriculum content;
- live planner behavior disagrees with deterministic behavior after both call
  the shared compiler;
- the feature cannot be based safely on the current unmerged refound branch.

## Expected checkpoint sequence

1. `fix: model Drop-E spelling transformations truthfully` (existing baseline)
2. `docs: plan systemic spelling-rule engine repair`
3. `test: add corpus-wide word-transformation audit`
4. `feat: add replayable word-transformation contract`
5. `refactor: generalize skill contracts for word transformations`
6. `feat: analyze word chains into verified operations`
7. `feat: classify and extract spelling-rule transformations`
8. `feat: compile verified transformations into child activities`
9. `feat: register prefix suffix and affix-review contracts`
10. `feat: add consonant-doubling rule contracts`
11. `refactor: migrate Drop-E to the transformation engine`
12. `feat: add Y-to-I spelling-rule contract`
13. `fix: enforce transformation contracts in the LLM path`
14. `fix: validate manipulation from typed transformations`
15. `test: enforce corpus-wide transformation completeness`
16. `test: cover spelling-rule packages end to end`
17. `docs: record spelling-rule live acceptance matrix`
18. `docs: hand off systemic spelling-rule engine`

This sequence is a guide, not permission to combine red/green blocks. Additional
fix commits are acceptable when a later corpus/live gate exposes a distinct bug,
but every such fix begins with its own focused RED regression.
