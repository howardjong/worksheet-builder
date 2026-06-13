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
5. On a live clean dense lesson (e.g. IMG_0004 lesson 59), the objective rubric APPROVES
   (det gates + coverage pass, overall ≥0.70, every essential cell ≥0.65, no severe defect,
   no required-form missing) — the one thing the free backtest could not prove.
6. Judge-approve precision validated against human raters (blind holdout) before any promotion;
   the approve/abstain/reject split and the uncertainty-band width are calibrated there.

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
  -> approval policy (TRI-STATE, see below): approve / abstain(uncertain) / reject
```

**Approval is tri-state, not binary (Session 50, per GPT-5.5 follow-up).** A hard
`essential cell >= 0.60` floor is the same fake precision we just moved out of coverage — a
noisy quality score landing at 0.58 must not masquerade as a deterministic product failure
(we *proved* hard thresholds on noisy LLM scores flip, S48). Per-cell judge scores are
**diagnostic confidence, not release-law**. Bands: essential cell `>=0.65` pass, `<0.50`
fail, `0.50–0.65` **uncertain** (abstain). The judge's hard veto is a typed severe defect
*with cited evidence* (enum, T8): `wrong_cognitive_task`, `misleading_or_wrong_instruction`,
`generic_activity_not_exercising_objective`, `child_cannot_reasonably_answer`,
`overwhelming_or_adhd_unsafe`. **Severe-defect voting (conservative for safety, per GPT-5.5):
2/3 samples → REJECT; 1/3 with evidence → ABSTAIN (manual review), never silently ignored;
0/3 → pass.** (Stricter than the median rule used for numeric scores — a single credible
safety flag must not be averaged away.)

```
APPROVE  = det blockers pass AND required-forms pass AND det objective-coverage pass
           AND det package ADHD upper-bounds pass
           AND overall_median >= 0.70 AND adhd/safety >= 0.50
           AND every essential cell quality >= 0.65
           AND no essential-cell severe defect in >=1/3 of samples
REJECT   = any det gate/required-form/coverage/package-bound fail  OR overall_median < 0.70
           OR adhd/safety < 0.50  OR any essential cell quality < 0.50
           OR any essential-cell severe defect in >=2/3 of samples
ABSTAIN  = otherwise (essential cell in 0.50–0.65, OR a 1/3 severe-defect flag, all else passing)
           -> "not auto-approved", route to existing fallback; NOT a clean
              objective-insufficiency reject; tracked separately in telemetry
```
**Abstain safety definition (per GPT-5.5).** Abstain means *the objective path did not
auto-approve* — it never ships the abstained objective-path plan through a relaxed gate. It
routes to the **existing fallback** (the old loop), whose output must still independently pass
its own deterministic blockers, print checks, ADHD clamps, and current validators before
shipping. This changes labels + telemetry, not infra. Band width (0.50–0.65) is a starting
prior, **calibrated on the T11 holdout**, not asserted.

**Two-signal division of labour (no double-counting).** The deterministic validator is
*authoritative* for counts, required-form presence, distinctness, and blockers. The judge
scores **quality** per cell (clarity, developmental fit, coherence, "does this practice
genuinely exercise the objective") — it never re-derives counts in prose. Coverage is
evaluated at the **lesson package** level (the full `list[AdaptedActivityModel]`, since one
lesson splits into mini-worksheets via `worksheet_number/count`), never per single worksheet.

**Residual judge variance is designed out, not deferred (Session 50, GPT-5.5 follow-up).**
The naive "every essential cell ≥ 0.60" hard floor would let a noisy 0.58 flip the gate
run-to-run — the one place the judge re-injects instability despite a fixed ledger. We do
*not* keep it and "measure later"; we already proved (S48) hard thresholds on noisy LLM
scores flip, so the abstention zone is built in from the start (see the tri-state policy
above) and its width is what T11 calibrates. Per-cell scores are diagnostic confidence; only
`<0.50` or a typed severe defect blocks an essential cell.

---

## Phase 1 — Deterministic core (variance-free; the real value)

**T0 (do this first, caution):** before writing any ledger-builder logic, create and commit the
minimal `tests/fixtures/objective_ledger/` skill-model fixtures (lesson 59 / 58 / an oll case,
see T3). The fixtures are load-bearing for every Phase-1 RED test and `samples/output/**` is
gitignored — don't start a clever builder against artifacts that aren't in the repo.

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
**Idempotency (per GPT-5.5 #6):** the ledger carries `corpus_version: str` (a hash/version of
the UFLI corpus metadata used) and `corpus_status`. Same photo/profile/theme + same
`corpus_version` ⇒ byte-identical ledger; a corpus change is visible, not silent — this is
what makes the frozen-cache battery (T10) reproducible.
**Typed `EvidenceItem` (per GPT-5.5 #4 — the cheap half of the deferred interaction contract):**
add an `EvidenceItem` model (`visible_text`, `practice_role`, `answer_key_text`,
`response_format`, `is_student_production: bool`, `objective_ids: list[str]`). T6 adapts each
`ActivityItem` into `EvidenceItem`s, giving the validator + judge a clean typed surface
*without* changing `ActivityItem`/planner/renderer schema.
- [ ] RED: construct a ledger from literals; assert serialization round-trips, the enums
  reject bad values, `role_confidence`/`role_source` required on `LedgerWord`, `corpus_version`
  required on the ledger, and `EvidenceItem` round-trips.
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
checks and never hard-fails a sufficiency count it can't confidently compute. Stamp
`corpus_version` on every ledger.
**Fixtures (per GPT-5.5 #8 — `samples/output/**` is gitignored, so offline tests cannot read
the live artifacts).** Copy minimal frozen `LiteracySkillModel` JSON into committed
`tests/fixtures/objective_ledger/` (lesson 59 / lesson 58 / an oll case), distilled from
`samples/output/lesson59_multi/artifacts/skill_model.json`,
`samples/output/lesson58/artifacts/skill_model.json`, and the IMG_0004
`frozen/artifacts/skill_model.json`. Follow the existing `tests/fixtures/quality_cases/`
convention.
- [ ] RED: load the committed lesson-59 / lesson-58 fixtures; assert chains→required_form
  manipulation cells, roll_and_read→samplable_pool, passage→required connected-text,
  sight_words→irregular cell, contrast words not in target counts, `corpus_version` stamped,
  stable across calls.
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
    → **not checked** (no false block).
  - Unknown/future `response_format` → `teacher_checked`, never a blocker.
**Scope (caution): T5 owns concrete answer-key/artifact blockers only.** It may flag an item
`teacher_checked` at the *item* level, but it does NOT reason about objectives — "is this the
sole evidence for an essential cell?" and the `teacher_checked`/`needs_verification`
*objective* semantics live in T6 (it owns `EvidenceItem` + objective-evidence logic). Keep the
gate dumb and local.
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
`build_evidence_index(worksheets, ledger) -> list[EvidenceItem]` +
`evaluate_objective_coverage(ledger, evidence) -> ObjectiveCoverageResult`. Operates on the
**whole, post-`section_cap` package** (`list[AdaptedActivityModel]` *after* the splitter
paginates — that's the final child-facing artifact) so objectives split across mini-worksheets
aggregate correctly (review missed-mode). This module is the single canonical home for evidence
+ evaluation logic; `validate/` and the judge-input builder both import it — no forked
definitions (review minor #9).

**Typed `EvidenceItem` adapter (GPT-5.5 #4).** `build_evidence_index` converts each
`ActivityItem` into one or more `EvidenceItem`s (the T1 model: `visible_text`, `practice_role`,
`answer_key_text`, `response_format`, `is_student_production`, `objective_ids`). Visibility is
derived once, here, from `response_format` + field: `content`→student practice; `answer`→key
(`is_student_production=False`, never counts); the correct `option`→not itself practice;
teacher worked-example text→not student production. A target word appearing only as a throwaway
answer option or in a key does **not** satisfy a cell — the S4 "presence ≠ practice" failure
made structural, now on a typed surface the judge also consumes.

**Package-level ADHD upper bounds (GPT-5.5 #7).** Aggregating sufficiency across worksheets
can *pass* by spreading too much total work across the package. Add deterministic package
upper-bound checks: total estimated minutes, total item count, max dense-text blocks, max
objectives per worksheet. Breach → fail (feeds the REJECT path / adhd-safety). Per-worksheet
`section_cap` guards each page; this guards the package total.

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
  across two worksheets in the package → aggregates to PASS; a package that meets every cell
  but exceeds total-minutes/total-items → package-upper-bound FAIL.
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
**Typed severe-defect veto (Session 50).** Per essential cell the prompt asks the judge to
emit, *with cited evidence*, zero or more typed severe defects from a fixed enum:
`wrong_cognitive_task`, `misleading_or_wrong_instruction`,
`generic_activity_not_exercising_objective`, `child_cannot_reasonably_answer`,
`overwhelming_or_adhd_unsafe`. These — not a fuzzy numeric floor — are the judge's hard veto
on an essential cell. A bare low score with no cited defect is diagnostic, not a block.
- [ ] RED additions: prompt enumerates the severe-defect enum + "cite evidence"; instructs
  per-cell quality scores are advisory confidence, not pass/fail thresholds.
- [ ] RED: prompt contains the ledger objective ids + the "do not require every source
  word / Roll and Read item" instruction; omits any "reproduce all source" language.
- [ ] GREEN; commit: `feat: objective-sufficiency judge input contract (judge scores handed ledger)`.

### T8: Judge output schema + aggregation
**Files:** `adapt/llm_judge.py`; `tests/test_llm_judge.py`.
`ObjectiveJudgeVerdict`: per-cell `quality` score (0–1) + per-cell `severe_defects:
list[SevereDefect]` (typed enum + evidence string) + 5 criteria + overall +
`approval_recommendation` ∈ {approve, abstain, reject}. Map old `content_coverage` →
`objective_sufficiency` for transition. Keep median-of-N (`judge_adaptation_samples`) but
aggregate **per objective cell** before the overall. Numeric quality uses the median of the N
samples. **Severe defects use the conservative vote (not median):** a typed defect in **2/3**
samples → REJECT that cell; in **1/3** with cited evidence → ABSTAIN (manual review), never
ignored; 0/3 → pass. Derive the tri-state per the approval policy.
- [ ] RED: per-cell median quality computed; a severe defect in 2/3 → reject, in 1/3 →
  abstain (NOT ignored); an essential cell at 0.58 with no defect → `abstain`; at 0.45 →
  reject; clean ≥0.65 everywhere + gates pass + no defect → approve.
- [ ] GREEN; commit: `feat: tri-state objective-sufficiency judge verdict (per-cell quality + typed severe-defect veto)`.

### T8.5: Planner authoring prompt — author IN the required forms (the generation-side fix)
**Files:** `adapt/llm_planner.py` (prompt builder); `tests/test_llm_planner.py`.
**Why this exists (the blindspot caught Session 50):** we hardened the deterministic validator
AND the judge to demand correct pedagogical *form*, but nothing tells the *planner* to produce
it. S5 proved the planner name-drops tokens instead of authoring build-chains; the old S3
deterministic repair (which can't synthesize a good chain anyway) is retired with S0–S4. So
without a planner-side change, dense lessons hit required-form FAIL → abstain → fallback to the
old page-faithful loop, and **success criterion #5 (a clean dense lesson APPROVES) is
unreachable.** Research spec step (line 604) calls for exactly this.
Under `WORKSHEET_OBJECTIVE_COVERAGE`, the planner prompt receives the ledger's **objective
cells + required forms** (not just a word list) and is instructed to: author each
`required_form` objective *in* its form (word_chain/chain_script → an executable
transformation sequence; passage → connected text; encode → written production; sentence-write
→ production); **sample** `samplable_pool` items to the cell threshold, not exhaustively; and
**not** dilute target-pattern cells with contrast/review/irregular words. Flag OFF ⇒ prompt
byte-identical (assert no drift, as with S1).
- [ ] RED: flag on, the prompt for a chain objective instructs an ordered build/transformation
  (contains the step language), instructs sampling roll-and-read to threshold (not "include
  all"), and forbids padding the pattern cell with contrast words; flag off ⇒ prompt unchanged.
- [ ] GREEN; commit: `feat: planner authors in required forms under objective-coverage flag`.

### T9: Wire the objective path into plan_lesson_llm (flagged)
**Files:** `adapt/llm_planner.py`; `tests/test_llm_planner.py`.
When `WORKSHEET_OBJECTIVE_COVERAGE=1`: build ledger → planner authors (ledger in prompt) →
`run_blocking_gates` (block→reject, skip judge) → `evaluate_objective_coverage` (det fail→
reject) → judge against ledger → **tri-state** approval policy (APPROVE / ABSTAIN / REJECT
per the design block). ABSTAIN routes to the existing fallback (same code path as a
non-approved package today) and is logged distinctly from a clean reject. Flag OFF ⇒
byte-identical.
**Flag mutual-exclusion (review minor #8):** if both `WORKSHEET_OBJECTIVE_COVERAGE` and
`WORKSHEET_PLANNER_SLOT_CONTRACT` are set, fail fast with a clear error — never run both
coverage systems at once (results would be uninterpretable).
- [ ] RED: flag on, a stubbed plan with answer∉options → rejected by gate (judge not called);
  a clean plan sampling roll-and-read → approved; a plan with an essential cell at 0.58 and no
  severe defect → ABSTAIN→fallback (not a clean reject); flag off ⇒ unchanged path.
- [ ] GREEN; commit: `feat: objective-sufficiency coverage path in plan_lesson_llm (flagged)`.

## Phase 3 — Live verification + calibration (owner env)

### T10: Live clean-dense-lesson verification
Re-run the frozen-cache battery with `WORKSHEET_OBJECTIVE_COVERAGE=1` on IMG_0003/4/5,
`--runs 2`, judge×3. **Success:** the roll-and-read false-rejections are gone; real defects
(if any) are caught by the deterministic gates (not the fuzzy judge); a clean dense lesson
APPROVES (overall ≥0.70, every essential cell ≥0.65, no severe defect). Record scorecards in
the context doc. This is the proof the free backtest could not provide (no clean dense plan was
persisted).
**Per review #4:** in battery/eval mode, always write the deterministic coverage result +
blocker report **even when a package is blocked** (production may skip the judge on a blocker,
but calibration must not lose the signal). **Per review missed-mode:** spot-check the
*rendered* output, not just the validated model — the renderer can alter match/display
semantics after validation.
**Characterize the abstention zone (Session 50):** across the `--runs 2`, judge×3 cells,
record per-essential-cell quality scores and the approve/abstain/reject label per run. Report
the **abstain rate** and whether the *final* label (not the raw 0.50–0.65 score) is stable
run-to-run on frozen input — the tri-state should convert former gate-flips into stable
ABSTAINs. Two distinct signals: unstable approve↔reject (excluding abstain) → re-tune band
width (calibrated for real in T11). A **high abstain rate on dense lessons** is NOT a band
problem — it means the planner isn't authoring the required forms, i.e. **fix T8.5**, not the
threshold. (If most dense lessons abstain, the feature ships nothing new — that's a redesign
signal, not a tuning knob.)
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
   matrix. **Three-bucket** (approve / abstain / reject), not binary: abstain is tracked
   separately and is NOT counted as a false reject. Promotion requires a **low abstain rate**
   AND zero severe false approvals on the holdout.
**Band calibration:** the 0.50–0.65 uncertainty width is fit here against the human
revise/reject boundary (where do raters actually disagree?), not asserted. The typed
severe-defect veto is validated against rater-labeled defects (do humans agree those cells are
genuinely broken?).
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
defect-catching on its own. Phase 2 (T7, T8, **T8.5**, T9) needs Phase 1; T8.5 (planner authors
in-form) is the generation-side fix without which dense lessons abstain rather than approve.
Phase 3 (T10–T11) needs the owner env. Do not flip any default; do not lower the 0.70 bar.

## Open decisions for the owner (flagging before coding)
> 1–3 are **decided** (the recommendations stand — proceed unless the owner overrides). 4 is
> resolved via the `EvidenceItem` middle path. None block Phase 1.

1. **New flag name** `WORKSHEET_OBJECTIVE_COVERAGE` (vs reusing `WORKSHEET_PLANNER_SLOT_CONTRACT`).
   Recommend new flag so the two coverage systems can be A/B'd and S0–S4 retired cleanly.
2. **Additive validator vs in-place wrapper.** Recommend additive new validator during the
   build; fold into `validate/content_coverage.py` only at promotion (keeps the scorecard
   meaning stable for loop/unflagged runs mid-flight).
3. **Role classifier depth.** Start with simple explicit pattern helpers + corpus heart
   words; **confidence-tag** ambiguous words (T2) so they degrade to advisory rather than
   forcing rejection. Defer a richer phonics engine unless T10 needs it.
4. **Typed interaction contract on `ActivityItem`** (review's headline fix — `answer_mode`,
   `option_roles`, `visible_to_student`, …). **Resolved via middle path:** keep `ActivityItem`
   unchanged (no ripple into planner/renderer/tests), but add a canonical typed `EvidenceItem`
   (T1) that T6 derives from each item — the cheap half of the contract (GPT-5.5 #4). T5's
   format-allowlist handles gating. Promote a full `ActivityItem` contract only if T10 shows
   the allowlist mis-gates a legitimate format.

## Scope of the auto-approval promise (GPT-5.5 #5)
The objective path's auto-approve targets **UFLI-matched lessons** (corpus hit). On
corpus-miss / non-UFLI input, confidence caps to `low`, essential cells become
`needs_verification` → **abstain → fallback**; these are explicitly *not* part of the initial
promotion promise. Promotion (T11) is measured on matched UFLI lessons only.

## Review changes folded in (GPT-5.5, 2026-06-13)
Go-with-changes. Adopted: confidence-tagged classification replacing blanket safe-undercount
(T1/T2/T6); answer-key gate as a format allowlist + `heading_as_item` and
`worked_example_consistency` gates (T5); form/cognitive-specific required-form + distinctness
+ visibility-derived evidence + package-level aggregation (T6); judge scores quality, validator
owns counts (T7); sequential dev/blind-holdout calibration with abort rules (T11); flag
mutual-exclusion (T9); single canonical evidence module (T6); battery records coverage even
when blocked (T10). Pushed back on: typed interaction-contract schema change (open decision 4,
deferred in favour of the allowlist).

**Round 2 (GPT-5.5 follow-up + own sweep, 2026-06-13).** Tri-state approval replaces the hard
per-cell 0.60 floor (design block, T7–T11). Then: **T8.5 added** — planner authors *in* the
required forms (the generation-side fix; without it dense lessons abstain→fallback and
criterion #5 is unreachable — caught in the own-sweep, confirmed by spec line 604). Severe-defect
voting tightened to 2/3 reject / 1/3 abstain / 0 pass (T8, design block). Abstain given a
**safety definition** (objective path doesn't auto-approve; fallback output still passes its own
blockers/print/ADHD/validators). Canonical typed **`EvidenceItem`** added (T1/T6) as the cheap
half of the interaction contract (open decision 4 resolved). `corpus_version` hash for ledger
idempotency (T1/T3). **Package-level ADHD upper bounds** so aggregation can't pass by spreading
overload (T6). Coverage pinned to the **post-`section_cap`** package (T6). Committed
`tests/fixtures/objective_ledger/` skill-model fixtures (T3 — `samples/output/**` is gitignored).
UFLI-first auto-approval scope stated. Research spec's superseded sections (0.60 floor, 15–20
calibration) banner-marked.
