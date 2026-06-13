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
       objectives (cells) + classified source items + word roles (+confidence/source)
  -> planner authors worksheets: list[AdaptedActivityModel]  (planner, ledger in prompt)
  -> run_blocking_gates(worksheets, ledger)    [deterministic hard block, Phase 1]
       fail -> not approved, judge skipped (but battery still records gate+coverage report)
  -> build_evidence_index(worksheets, ledger)  [deterministic, Phase 1; visibility/role-aware]
  -> evaluate_objective_coverage(ledger, evidence)  [deterministic validator, Phase 1]
       OWNS counts + required-form + distinctness; hard-fail only on HIGH-confidence shortfalls
  -> judge scores QUALITY against ledger        [Phase 2; judge cannot reclassify OR re-count]
  -> approval policy: gates pass AND required-forms present AND det-coverage pass
       AND overall>=0.70 AND every essential cell>=0.60 AND adhd/safety>=0.50
```

**Two-signal division of labour (no double-counting).** The deterministic validator is
*authoritative* for counts, required-form presence, distinctness, and blockers. The judge
scores **quality** per cell (clarity, developmental fit, coherence, "does this practice
genuinely exercise the objective") — it never re-derives counts in prose. Coverage is
evaluated at the **lesson package** level (the full `list[AdaptedActivityModel]`, since one
lesson splits into mini-worksheets via `worksheet_number/count`), never per single worksheet.

**Known residual judge variance (accepted, measure don't pre-solve — Session 50).** The
approval policy keeps "every essential cell ≥ 0.60," and 0.60 is a *quality* score, so a
borderline cell (≈0.58↔0.62) can still flip the gate run-to-run — the one place the judge can
re-inject instability despite scoring a fixed ledger. This is accepted for now: the variance
we actually proved (S48/S49b) was coverage-*count* variance (0.34↔0.76), now deterministic; a
quality wobble near 0.60 is a genuinely borderline lesson, and median-of-N damps it. **Do not
pre-build a band.** T10 measures whether residual quality-floor flipping survives; only if it
does, add an uncertainty band (0.55–0.65 → "revise", hard-reject below 0.55).

---

## Phase 1 — Deterministic core (variance-free; the real value)

### T1: ObjectiveLedger schema
**Files:** new `adapt/objective_ledger.py`; test `tests/test_objective_ledger.py`.
Port the Pydantic schema from the research spec: `ObjectiveType`, `SourceRole`,
`CoverageClass`, `RequiredForm`, `LedgerWord`, `ClassifiedSourceItem`, `ObjectiveCell`,
`BlockingGateSpec`, `ObjectiveLedger`. Pure models + Literals; no logic yet.
**Added per review:** `LedgerWord` carries `role_confidence: Literal["high","low"]` and
`role_source: Literal["corpus_exact","pattern_rule","source_context","unknown"]`. This is
what lets the validator (T6) hard-fail only on high-confidence classifications and treat
low-confidence ones as advisory — replacing the blanket "safe-undercount" that would have
manufactured a *new* class of false rejections (the exact thing this plan exists to remove).
- [ ] RED: construct a ledger from literals; assert serialization round-trips, the enums
  reject bad values, and `role_confidence`/`role_source` are required on `LedgerWord`.
- [ ] GREEN; commit: `feat: ObjectiveLedger schema for objective-sufficiency coverage`.

### T2: Deterministic role classifier (confidence-tagged)
**Files:** `adapt/objective_ledger.py`; `tests/test_objective_ledger.py`.
`classify_word_role(word, pattern_ctx) -> (SourceRole, role_confidence, role_source)`. Simple,
explicit phonics-pattern helpers first (reuse `skill/extractor.py` pattern utilities where
they exist). Rules from the spec §"Classify words by role": target_pattern / irregular_word
(corpus heart words) / review_word / contrast_word (only in deliberate contrast tasks) /
`ambiguous_review_word`.
**Changed per review (the load-bearing fix):** classification is *confidence-tagged*, not
blindly undercounted. `corpus_exact` (word found in the lesson's UFLI corpus list) →
`high`; a clean single-pattern rule match (e.g. C-V-C-e with the target vowel, no competing
team) → `high` `pattern_rule`; everything resolved only by surrounding task framing →
`low` `source_context`; unresolved → `low` `unknown`. Ambiguity (mixed-VCe, vowel teams,
y-as-vowel, schwa/multisyllable, visually-pattern-containing irregulars) yields `low`, which
T6 treats as advisory — it does **not** auto-reject. Only `high`-confidence target-pattern
words count toward (or against) a pattern cell's hard threshold.
- [ ] RED: u_e context — `cute/mute`→(target_pattern, high); `who/one`→(irregular, high via
  corpus); `mop`/`jazz` in an -oll lesson→(review/contrast, high) not target; `type`/`gym`
  (y-as-vowel) in a u_e lesson→(ambiguous, low); a corpus-miss word→(…, low).
- [ ] GREEN; commit: `feat: confidence-tagged deterministic word-role classifier`.

### T3: build_objective_ledger
**Files:** `adapt/objective_ledger.py`; `tests/test_objective_ledger.py`.
`build_objective_ledger(skill, corpus_lookup=lookup_lesson) -> ObjectiveLedger`. Implements
spec §"Deterministic Builder Rules" + §"Typed Source Item Mapping": resolve lesson context
(corpus by `lesson_number`, else fall back to skill fields; record `corpus_status`); create
objective cells (decode/encode/manipulation/connected-text/irregular/contrast); classify
each typed source item to a `CoverageClass`/`RequiredForm`; attach role-classified words and
sufficiency thresholds (priors table). Deterministic + stable.
**Graceful degrade per review:** `corpus_lookup` is a deterministic local dict lookup by
`lesson_number` (not retrieval/order-dependent). On a corpus miss / non-UFLI input, record
`corpus_status="miss"`, fall back to skill-model fields, and cap every word's
`role_confidence` at `low` — so the validator degrades to required-form/source-preservation
checks and never hard-fails a sufficiency count it can't confidently compute.
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
`run_blocking_gates(worksheets, ledger) -> BlockingGateResult`. Hard `blocker` severity.

**`answer_key` is a format ALLOWLIST, not "answer∈options with a `match` exception"**
(review Critical #1, confirmed: `sound_box`/`read_aloud`/`trace`/`write` all legitimately
have answer≠option or no answer). The check fires *only* on formats where answer-in-options
is unambiguously required:
  - `circle`, `fill_blank` **with non-empty `options`** → require answer ∈ options (this is
    the format that carried the backtest defect).
  - `match` → verify pair existence (answer≠option is the intended mechanic), not membership.
  - `sound_box`, `read_aloud`, `trace`, `write`, `verbal`, or any item with `options` empty
    → **not checked** (no false block). If such an item is the *sole* evidence for an
    essential objective cell and is unverifiable, mark `teacher_checked` (advisory), don't block.
  - Unknown/future `response_format` → `teacher_checked`, never a blocker.
Deferring the typed interaction contract (review's proposed `answer_mode`/`option_roles`
schema fields) — the allowlist gets the defect-catch without rippling into the planner,
renderer, and existing tests. Revisit only if T10 shows the allowlist too coarse (open decision 4).

Other gates: `instruction_option_answer` (checkable subset only; free-text predicate →
`teacher_checked`, not a block); `source_notation_artifact` (`by*`/`my*` etc. in
student-facing text); `capitalization` (proper nouns from source/corpus, e.g. `June` — but
**only** when the token is not sentence-initial, to avoid the obvious false positive).
**Two gates added per review #7** (backtest defects the original four missed):
  - `heading_as_item`: an item whose `content` matches a known source section heading /
    `chain_script` label rather than a practice item.
  - `worked_example_consistency` (narrow): the chunk's `worked_example` answer contradicts
    the modeled item, or contains a "No."/negation after a modeled answer, or its
    answer/options are themselves mismatched.
- [ ] RED: fill_blank w/ answer∉options→blocker; `match` answer≠option→PASS; `sound_box`
  phoneme-options + whole-word answer→PASS (no false positive); sentence-initial `June`→PASS,
  mid-sentence `june`→blocker; a source heading used as an item→blocker; a worked example
  whose answer contradicts its item→blocker; `by*` in content→blocker; clean packet→passed.
- [ ] GREEN; commit: `feat: deterministic blocking gates (format-allowlisted answer-key, heading + worked-example, artifact, capitalization)`.

### T6: Deterministic objective-coverage validator
**Files:** new `validate/objective_coverage.py`; test `tests/test_objective_coverage.py`.
`build_evidence_index(worksheets, ledger)` + `evaluate_objective_coverage(ledger, evidence)
-> ObjectiveCoverageResult`. Operates on the **whole package** (`list[AdaptedActivityModel]`)
so objectives split across mini-worksheets aggregate correctly (review missed-mode). This
module is the single canonical home for evidence + evaluation logic; `validate/` and the
judge-input builder both import it — no forked definitions (review minor #9).

**Visibility/role-aware evidence index (review missed-mode).** Only *student-facing
practice* counts. Derive visibility from `response_format` + field: `content` is practice;
`answer` is the key (never practice); the correct `option` is not itself practice; teacher
worked-example text isn't student production. So a target word appearing only as a throwaway
answer option or in an answer key does **not** satisfy a cell — this is the S4 "presence
≠ practice" failure made structural.

**Required-form is form- AND cognitive-skill-specific (review #3), from the
skill-preservation substitution table:** a manipulation/chain cell needs ordered
*transformation* steps (not the chain's words scattered across write items); a connected-text
cell needs an actual passage/connected text (not a title or a lone sentence); an *encode*
cell needs written production (not reading); a sentence-*writing* cell needs production (not
sentence reading).

**Counting rules:** a pattern cell's numerator counts only **distinct, high-confidence**
target-pattern practice in an acceptable form (distinctness defeats the "repeat one word to
hit the count" game, review missed-mode; high-confidence gate from T2 means classifier
uncertainty can't manufacture a rejection). Low-confidence shortfalls are recorded as
**advisory**, surfaced to the judge, and do not hard-fail. Samplable pools (roll-and-read,
word_list) satisfied at threshold, not exhausted.
**Self-introduced hole closed (Session 50):** an *essential* cell with **zero** distinct
high-confidence practice must NOT auto-pass on advisory low-confidence evidence alone — that
would let a genuinely thin objective (corpus-miss / all-ambiguous lesson) sail through with no
verified practice. Such a cell is marked `needs_verification` and routes to judge-quality +
`teacher_checked` rather than a silent deterministic PASS. (Distinct from a cell that meets its
threshold on high-confidence words and has a few extra low-confidence ones — that still passes.)
- [ ] RED: samples 7/18 roll-and-read but hits the distinct decode threshold → PASS (the S5
  false-rejection); a target word present only as an answer-key/option → does NOT count;
  incomplete chain (missing early transformation steps) → required-form FAIL; pattern cell
  satisfied only by contrast words → FAIL; threshold met only by a repeated word → FAIL
  (distinctness); a cell short only on low-confidence words but ABOVE threshold on
  high-confidence → PASS with advisory flag; an essential cell with ONLY low-confidence
  evidence (zero high-confidence) → `needs_verification`, not silent PASS; objective split
  across two worksheets in the package → aggregates to PASS.
- [ ] GREEN; commit: `feat: package-level role/visibility-aware objective-coverage validator`.

## Phase 2 — Judge rubric reframe (scores only)

### T7: Judge input contract + evidence index serialization
**Files:** `adapt/llm_judge.py`; `tests/test_llm_judge.py`.
Build the judge input (`objective_ledger` + `blocking_gates` + `deterministic_coverage` +
`adapted_activity` + `evidence_index`) per spec §"Judge Input And Output Contract". Judge
prompt instructs: score handed objectives only; never create objectives, reclassify items,
demand full pools, or count contrast/review/irregular toward target pattern; never approve
a blocked package. Keep **0–1** scoring.
**Sharpened per review #5 (no double-counting):** the judge scores **quality** of the
evidence (clarity, developmental fit, coherence, "does this practice genuinely exercise the
objective"). Counts, required-form presence, and distinctness are *already decided* by T6 and
handed in as facts — the prompt explicitly forbids the judge from re-deriving or overriding
them. The deterministic validator owns "enough?"; the judge owns "good?".
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
**Flag mutual-exclusion (review minor #8):** if both `WORKSHEET_OBJECTIVE_COVERAGE` and
`WORKSHEET_PLANNER_SLOT_CONTRACT` are set, fail fast with a clear error — never run both
coverage systems at once (results would be uninterpretable).
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
**Per review #4:** in battery/eval mode, always write the deterministic coverage result +
blocker report **even when a package is blocked** (production may skip the judge on a blocker,
but calibration must not lose the signal). **Per review missed-mode:** spot-check the
*rendered* output, not just the validated model — the renderer can alter match/display
semantics after validation.
**Measure the residual judge-quality-floor flip (Session 50):** across the `--runs 2`,
judge×3 cells, record per-essential-cell quality scores and check whether any cell crosses the
0.60 floor between runs on frozen input. If flipping persists, that's the trigger to add the
0.55–0.65 uncertainty band; if not, leave the hard 0.60 floor as-is.
- [ ] Not offline; owner env (sandbox off, `SSL_CERT_FILE`). Compare vs S5 baselines.

### T11: Human approve-precision calibration (sequential, anti-overfit)
Per spec §"Calibration Against Human Raters", but restructured per review #6 so we don't tune
the rubric until it passes its own examples. **Two disjoint sets, in order:**
1. **Freeze the rubric** (thresholds, floors, gate definitions) — written down before raters see anything.
2. **Dev set (~20, stratified:** good / page-faithful-overwhelming / objective-thin / mixed
   edge). Used only to *debug* the harness and surface obvious breakage. Tuning is allowed here.
3. **Blind holdout (40–60, fresh stratified, never inspected during dev), 2–3 expert raters.**
   This is the **promotion gate** and it is *not* tuned against. Metrics: false-approve /
   false-reject rates, quadratic-weighted kappa on per-cell quality scores, blocker confusion
   matrix.
**Abort rules:** any single *severe* false approval (a genuinely harmful/wrong package
approved), or ≥2 material false approvals in the first 20 holdout cases → stop, do not promote,
return to design. Fix false approvals (answer-key / artifact / dilution) before false rejections.

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
   words; **confidence-tag** ambiguous words (T2) so they degrade to advisory rather than
   forcing rejection. Defer a richer phonics engine unless T10 needs it.
4. **Typed interaction contract on `ActivityItem`** (review's headline fix — `answer_mode`,
   `option_roles`, `visible_to_student`, …). **Deferred.** T5's format-allowlist + T6's
   derived visibility get the defect-catch without a schema change that ripples into the
   planner, renderer, and every existing test. Promote to a real task only if T10 shows the
   allowlist mis-gates a legitimate format (e.g. a new activity type the allowlist can't classify).

## Review changes folded in (GPT-5.5, 2026-06-13)
Go-with-changes. Adopted: confidence-tagged classification replacing blanket safe-undercount
(T1/T2/T6); answer-key gate as a format allowlist + `heading_as_item` and
`worked_example_consistency` gates (T5); form/cognitive-specific required-form + distinctness
+ visibility-derived evidence + package-level aggregation (T6); judge scores quality, validator
owns counts (T7); sequential dev/blind-holdout calibration with abort rules (T11); flag
mutual-exclusion (T9); single canonical evidence module (T6); battery records coverage even
when blocked (T10). Pushed back on: typed interaction-contract schema change (open decision 4,
deferred in favour of the allowlist).
