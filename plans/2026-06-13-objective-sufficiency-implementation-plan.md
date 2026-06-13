# Objective-Sufficiency Coverage — Implementation Plan

> Branch: `feature/objective-sufficiency-coverage` (off `main` @ `a5c8d19`).
> Source spec: `plans/2026-06-13-objective-sufficiency-rubric-research.md` (revised).
> Backtest evidence + priority shift: context doc Sessions 49b/49c.
> Discipline: strict red-green TDD per task, one commit per task, exact paths only,
> no `Co-Authored-By` trailer, never touch `.claude/settings.json`, full
> `make lint && make typecheck && make test` (mypy strict, offline) before each commit.

## Why this exists (the reframe, in one line)

"Coverage" = did the adaptation give enough correct, low-overwhelm practice for each
**learning objective / concept / skill**, NOT did it reproduce every source page item.
S5 proved the old page-fidelity definition vetoes good ADHD adaptations (roll-and-read
reproduction); the backtest proved the dense rejections were *over-determined* — page
fidelity AND real defects (notation artifacts, incomplete chains, heading-as-item). So
the deterministic half (ledger + blocking gates + required-form) does the real
defect-catching and is variance-free; build it first.

## Goal & success criteria

"Done" (for the whole plan) =

1. A deterministic `ObjectiveLedger` is built from the frozen `LiteracySkillModel`
   (+ UFLI corpus) with NO LLM call; the judge only *scores against* it.
2. Both coverage signals (the judge's criterion and `validate/`) read the **same** ledger.
3. Answer-key/option mismatches and source-notation artifacts are **deterministic hard
   blocks**, not soft criteria (`match` activities special-cased).
4. Contrast / review / irregular words do **not** count toward target-pattern sufficiency.
5. On a live clean dense lesson (e.g. IMG_0004 lesson 59), the objective rubric reaches
   ≥0.70 with all essential objective cells ≥0.60 and no required-form missing — the one
   thing the free backtest could not prove.
6. Judge-approve precision validated against human raters (C-small, 15–20 plans) before
   any promotion.

Hard rules carried over: do NOT lower the 0.70 judge bar. Everything new is **default
OFF** (`WORKSHEET_OBJECTIVE_COVERAGE`, see below) so production (old loop) is
byte-identical until promotion is earned. Parent-plan Tasks 13–15 stay BLOCKED.

## Flagging & relationship to S0–S4

- New behavior gates behind **`WORKSHEET_OBJECTIVE_COVERAGE=1`** (default OFF).
- The S0–S4 contract (`adapt/coverage_ledger.py`, behind `WORKSHEET_PLANNER_SLOT_CONTRACT`)
  stays untouched and OFF; the objective ledger **supersedes** it. Once the new path is
  validated and promoted, S0–S4 + its flag are retired (a later cleanup task, not now).
- `validate/content_coverage.py` is **not mutated in place** during the build — a new
  objective-coverage validator is added alongside and used only when the flag is on. The
  research's "compatibility wrapper" is the END state, done at promotion, so the scorecard
  "coverage" column meaning doesn't change for unflagged/loop runs mid-flight.

## Design (data flow when flag is ON)

```
frozen LiteracySkillModel (+ lesson_number -> UFLI corpus)
  -> build_objective_ledger()                 [deterministic, Phase 1]
       objectives (cells) + classified source items + word roles
  -> planner authors AdaptedActivityModel      (existing planner, ledger in prompt)
  -> run_blocking_gates(adapted, ledger)       [deterministic hard block, Phase 1]
       fail -> not approved, judge skipped
  -> build_evidence_index(adapted, ledger)     [deterministic, Phase 1]
  -> evaluate_objective_coverage(ledger, evidence)  [deterministic validator, Phase 1]
  -> judge scores evidence against ledger      [Phase 2; judge cannot reclassify]
  -> approval policy: gates pass AND required-forms present AND det-coverage pass
       AND overall>=0.70 AND every essential cell>=0.60 AND adhd/safety>=0.50
```

---

## Phase 1 — Deterministic core (variance-free; the real value)

### T1: ObjectiveLedger schema
**Files:** new `adapt/objective_ledger.py`; test `tests/test_objective_ledger.py`.
Port the Pydantic schema from the research spec: `ObjectiveType`, `SourceRole`,
`CoverageClass`, `RequiredForm`, `LedgerWord`, `ClassifiedSourceItem`, `ObjectiveCell`,
`BlockingGateSpec`, `ObjectiveLedger`. Pure models + Literals; no logic yet.
- [ ] RED: construct a ledger from literals; assert serialization round-trips and the
  enums reject bad values.
- [ ] GREEN; commit: `feat: ObjectiveLedger schema for objective-sufficiency coverage`.

### T2: Deterministic role classifier
**Files:** `adapt/objective_ledger.py`; `tests/test_objective_ledger.py`.
`classify_word_role(word, pattern_ctx) -> SourceRole`. Simple, explicit phonics-pattern
helpers first (reuse `skill/extractor.py` pattern utilities where they exist). Rules from
the spec §"Classify words by role": target_pattern / irregular_word (corpus heart words) /
review_word / contrast_word (only in deliberate contrast tasks) / `ambiguous_review_word`
(safe-undercount default — never counts toward the primary pattern objective).
- [ ] RED: in a u_e context, `cute/mute`→target_pattern, `who/one`→irregular, `mop`/`jazz`
  in an -oll lesson→review/contrast not target, unknown→ambiguous_review_word.
- [ ] GREEN; commit: `feat: deterministic word-role classifier (safe-undercount default)`.

### T3: build_objective_ledger
**Files:** `adapt/objective_ledger.py`; `tests/test_objective_ledger.py`.
`build_objective_ledger(skill, corpus_lookup=lookup_lesson) -> ObjectiveLedger`. Implements
spec §"Deterministic Builder Rules" + §"Typed Source Item Mapping": resolve lesson context
(corpus by `lesson_number`, else fall back to skill fields; record `corpus_status`); create
objective cells (decode/encode/manipulation/connected-text/irregular/contrast); classify
each typed source item to a `CoverageClass`/`RequiredForm`; attach role-classified words and
sufficiency thresholds (priors table). Deterministic + stable.
- [ ] RED: feed the IMG_0004 (lesson 59) and IMG_0003 (lesson 58) skill models (fixtures
  from the S5 artifacts); assert chains→required_form manipulation cells, roll_and_read→
  samplable_pool, passage→required connected-text, sight_words→irregular cell, contrast
  words not in target counts, stable across calls.
- [ ] GREEN; commit: `feat: deterministic objective ledger builder from skill model + UFLI corpus`.

### T4: Extraction artifact-strip (upstream, Fix-A-style)
**Files:** `skill/extractor.py`; `tests/test_skill.py`.
Strip source-notation artifacts (`by*`, `my*`, trailing heart markers, bracketed
annotations) from student-facing text at the extraction boundary, preserving the marker in
metadata only. Mirrors the existing `_sanitize_concept_text` approach.
- [ ] RED: a sight-words source `"who, by*, my*, one"` yields clean `by`/`my` in
  student-facing fields, with the marker retained in metadata.
- [ ] GREEN; commit: `fix: strip source-notation artifacts at extraction (by*/my*)`.

### T5: Deterministic blocking gates
**Files:** new `validate/blocking_gates.py`; test `tests/test_blocking_gates.py`.
`run_blocking_gates(adapted, ledger) -> BlockingGateResult` per spec §"Gate Rules":
`answer_key` (answer∈options — **special-case `match`**: verify pair existence, not
answer-in-options — this was the false-positive the backtest caught),
`instruction_option_answer` (checkable subset only; defer free-text predicate parsing —
mark `teacher_checked` or block), `source_notation_artifact`, `capitalization` (proper
nouns from source/corpus, e.g. `June`). Hard `blocker` severity.
- [ ] RED: a fill_blank with answer∉options → blocker; a `match` item with answer≠option →
  PASS (no false positive); `by*` in content → blocker; lowercase `june` → blocker;
  a clean packet → passed.
- [ ] GREEN; commit: `feat: deterministic blocking gates (answer-key, artifact, capitalization; match-aware)`.

### T6: Deterministic objective-coverage validator
**Files:** new `validate/objective_coverage.py`; test `tests/test_objective_coverage.py`.
`build_evidence_index(adapted, ledger)` + `evaluate_objective_coverage(ledger, evidence)
-> ObjectiveCoverageResult`. Role-aware: a pattern cell's numerator counts only
target-pattern practice in acceptable forms; required-form presence checked (chain build
sequence complete; passage as connected text; etc.); samplable pools satisfied at threshold,
not exhausted. Failure conditions per spec §"Deterministic Coverage Validator Change" item 4.
- [ ] RED: a plan that samples 7/18 roll-and-read but hits the decode threshold → PASS
  (the S5 false-rejection); an incomplete chain (missing early steps) → required-form FAIL;
  a pattern cell satisfied only by contrast words → FAIL.
- [ ] GREEN; commit: `feat: deterministic role-aware objective-coverage validator`.

## Phase 2 — Judge rubric reframe (scores only)

### T7: Judge input contract + evidence index serialization
**Files:** `adapt/llm_judge.py`; `tests/test_llm_judge.py`.
Build the judge input (`objective_ledger` + `blocking_gates` + `deterministic_coverage` +
`adapted_activity` + `evidence_index`) per spec §"Judge Input And Output Contract". Judge
prompt instructs: score handed objectives only; never create objectives, reclassify items,
demand full pools, or count contrast/review/irregular toward target pattern; never approve
a blocked package. Keep **0–1** scoring.
- [ ] RED: prompt contains the ledger objective ids + the "do not require every source
  word / Roll and Read item" instruction; omits any "reproduce all source" language.
- [ ] GREEN; commit: `feat: objective-sufficiency judge input contract (judge scores handed ledger)`.

### T8: Judge output schema + aggregation
**Files:** `adapt/llm_judge.py`; `tests/test_llm_judge.py`.
`ObjectiveJudgeVerdict` (per-cell scores + 5 criteria + overall + approval_recommendation).
Map old `content_coverage` → `objective_sufficiency` for transition. Keep median-of-N
(`judge_adaptation_samples`) but aggregate **per objective cell** before the overall.
- [ ] RED: median-of-N aggregation computes per-cell medians then overall; approval recomputed.
- [ ] GREEN; commit: `feat: objective-sufficiency judge verdict schema + per-cell median aggregation`.

### T9: Wire the objective path into plan_lesson_llm (flagged)
**Files:** `adapt/llm_planner.py`; `tests/test_llm_planner.py`.
When `WORKSHEET_OBJECTIVE_COVERAGE=1`: build ledger → planner authors (ledger in prompt) →
`run_blocking_gates` (block→reject, skip judge) → `evaluate_objective_coverage` (det fail→
reject) → judge against ledger → approval policy (gates + required-form + det-coverage +
overall≥0.70 + every essential cell≥0.60 + adhd/safety≥0.50). Flag OFF ⇒ byte-identical.
- [ ] RED: flag on, a stubbed plan with answer∉options → rejected by gate (judge not called);
  a clean plan sampling roll-and-read → approved. Flag off ⇒ unchanged path.
- [ ] GREEN; commit: `feat: objective-sufficiency coverage path in plan_lesson_llm (flagged)`.

## Phase 3 — Live verification + calibration (owner env)

### T10: Live clean-dense-lesson verification
Re-run the frozen-cache battery with `WORKSHEET_OBJECTIVE_COVERAGE=1` on IMG_0003/4/5,
`--runs 2`, judge×3. **Success:** the roll-and-read false-rejections are gone; real defects
(if any) are caught by the deterministic gates (not the fuzzy judge); a clean dense lesson
reaches ≥0.70 with essential cells ≥0.60. Record scorecards in the context doc. This is the
proof the free backtest could not provide (no clean dense plan was persisted).
- [ ] Not offline; owner env (sandbox off, `SSL_CERT_FILE`). Compare vs S5 baselines.

### T11: C-small human approve-precision calibration
15–20 stratified plans (5 good, 5 page-faithful-overwhelming, 5 objective-thin, 5 mixed
edge), 2–3 expert raters, blind, per spec §"Calibration Against Human Raters". Metrics:
false-approve/false-reject, quadratic-weighted kappa on per-cell scores, blocker confusion
matrix. Tune essential-cell floors to the human revise/reject boundary; fix false approvals
(answer-key/artifact/dilution) before false rejections. **This is the promotion gate.**

## Conditional / deferred
- Full SlotPack (author per slot by `allowed_practice_forms`) only if T10 shows residual
  pedagogical-form variance the ledger+required-form checks don't remove.
- Retire `adapt/coverage_ledger.py` + `WORKSHEET_PLANNER_SLOT_CONTRACT` and fold
  `validate/content_coverage.py` into the objective validator (the research's wrapper) —
  AFTER promotion, as cleanup.
- Parent-plan Tasks 13–15 stay BLOCKED until promotion + telemetry.

## Sequencing
Phase 1 (T1–T6) is fully offline and TDD-able now and delivers the variance-free
defect-catching on its own. Phase 2 (T7–T9) needs Phase 1. Phase 3 needs the owner env.
Do not flip any default; do not lower the 0.70 bar.

## Open decisions for the owner (flagging before coding)
1. **New flag name** `WORKSHEET_OBJECTIVE_COVERAGE` (vs reusing `WORKSHEET_PLANNER_SLOT_CONTRACT`).
   Recommend new flag so the two coverage systems can be A/B'd and S0–S4 retired cleanly.
2. **Additive validator vs in-place wrapper.** Recommend additive new validator during the
   build; fold into `validate/content_coverage.py` only at promotion (keeps the scorecard
   meaning stable for loop/unflagged runs mid-flight).
3. **Role classifier depth.** Start with simple explicit pattern helpers + corpus heart
   words; safe-undercount ambiguous words. Defer a richer phonics engine unless T10 needs it.
