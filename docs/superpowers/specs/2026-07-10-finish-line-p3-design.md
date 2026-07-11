# Finish line: P3 objective-sufficiency alignment + trim guard + housekeeping

**Date:** 2026-07-10
**Status:** Approved direction (session 60); owner decisions embedded below
**Scope:** lesson-mode validators/judge/planner policy; package trim; print-check false positive; parked minors

## Background

After sessions 59-60b the lesson pipeline is clean except one semantic split:
the LLM planner path measures **objective sufficiency** (deterministic
tri-state over an objective ledger; sampling pools is explicitly fine), while
the post-hoc package validator (`validate/content_coverage.py`) and the
advisory judge (OLD rubric in `adapt/llm_judge.py:114`: "ALL source words …
Nothing should be dropped") still measure **exhaustive coverage** — so every
deliberately-capped lesson package logs coverage ERRORs and a ~0.5 advisory
score by design (Q4). Separately: lesson 74's latest planner rejection was
LEGITIMATE (the plan authored no word-chain activity despite prompt guidance),
the fallback trimmer is objective-blind (dropped Story Time before the dosage
fix raised the cap), and print checks warn "text overlaps image at (0,0)" on
every full-bleed image page.

Owner decisions driving this spec:
- **Cost-first failure policy:** the deterministic fallback still spends real
  money AFTER the adapt stage (legacy ai_review LLM loop, advisory judge, and
  above all image generation). A low advisory verdict should therefore FAIL
  the run BEFORE rendering (circuit-breaker), not ship-and-warn.
- Judge unavailable (no key / API error) → ship with a loud warning (infra
  must not cost the child a worksheet; deterministic baseline is proven
  decent).
- Override: `WORKSHEET_SHIP_UNAPPROVED=1` renders anyway on a low score.
- Models for execution: Sonnet 5 implements and task-reviews; Fable 5 runs
  the final whole-branch review and must explicitly audit red/green TDD
  evidence per task (exit criterion).

## Design

### 1. P3a — package validator speaks objective-sufficiency in lesson mode

New `validate_objective_package(skill_model, worksheets) ->
ObjectiveCoverageResult` (thin wrapper: `build_objective_ledger` →
`build_evidence_index` → `evaluate_objective_coverage`, all existing). In
`transform.py` (call site ~:953), when objective coverage is enabled (the
lesson-mode flag `WORKSHEET_OBJECTIVE_COVERAGE`), run it INSTEAD of
`_validate_package_content_coverage`; write
`artifacts/validation_objective_coverage.json`; `status == "fail"` →
`validation_results["content_coverage_passed"] = False`; `"pass"` and
`"needs_verification"` → True (needs_verification logs an advisory note, not
an ERROR). Photo path (flag off) keeps the exhaustive validator byte-identical.
Result: zero "covers 11/36 words" ERRORs on capped lesson packages; real form
gaps still fail.

### 2. P3b — advisory verdict = objective judge, fallback-only, fail-before-render

- New `judge_package_objective(skill_model, worksheets) ->
  ObjectiveJudgeVerdict | None` in `adapt/llm_judge.py`, reusing the existing
  objective-judge machinery (ledger + evidence + deterministic coverage facts
  + `_build_objective_judge_prompt`); None on any API/infra failure.
- `transform.py` Stage 5c (~:769-809): when `judge_verdict.json` exists
  (planner approved) — unchanged readback. Otherwise, in objective mode call
  `judge_package_objective` instead of the OLD `judge_adaptation`; photo path
  keeps `judge_adaptation` unchanged.
- **Policy (owner decision):** in objective mode, if the advisory verdict is
  `approved=False` and `WORKSHEET_SHIP_UNAPPROVED` is unset → abort the run
  BEFORE any rendering with a clear, actionable error naming the failing
  criteria and both remedies (re-run; or set the override). Verdict None
  (judge unavailable) → ship with a loud warning. Planner-approved packages
  never hit this branch.
- The OLD exhaustive rubric never runs in lesson mode again.

### 3. P3c — coverage-rejected plans get ONE retry with targeted feedback

The prompt already mandates authoring required forms
(`_objective_authoring_block`); lesson 74's plan ignored it. Mirror the D31
judge pattern on the coverage path in `adapt/llm_planner.py` (~:606-639):
on `coverage.status == "fail"`, ONE regeneration whose prompt appends a
feedback block naming each failing cell and its missing forms ("REJECTED:
obj_manipulation missing required form word_chain — your revised plan MUST
contain a word-chain activity …"), then gates + coverage re-evaluate on the
retry. Second fail → existing fallback, with both attempts recorded in
`planner_attempts.json`. Cost bound: at most +1 planner call per run, only
on coverage rejection.

### 4. Objective-aware package trim (chip task_46163d0f)

`adapt/section_cap.py::enforce_package_cap`: before the family round-robin,
seed the selection with one sheet per essential required form that would
otherwise be uncovered (e.g. the only sheet carrying the decodable passage),
then fill remaining slots round-robin as today. Cap stays hard; policy
"finishable beats exhaustive" unchanged. Needs the ledger's essential
required forms — pass them in from the caller (adapt/engine
`_finalize_lesson_package` already holds `skill`).

### 5. Print-check overlap false positive

Diagnose `validate/print_checks.py` overlap detection against an image_gen
page: the invisible searchable text layer (render_mode=3, fontsize 2, drawn
at page origin) over the full-bleed image is the suspected trigger for
"text overlaps image at (0, 0)". If confirmed: ignore invisible-text spans
(render mode 3) in overlap detection — legibility of invisible text is
meaningless. If the warning is real, fix the real cause. TDD against a
synthetic PDF fixture built with PyMuPDF in the test.

### 6. Minors sweep

- `render/design_spec.py::_required_text`: also append
  `feedback.parent_log_title` ("Grown-up quick log") so the page gate
  verifies the box renders. The DECISION_HINT stays gate-unverified —
  deliberate: demanding a ~150-char string from the OCR gate trades real
  flakiness for marginal value (documented in code comment).
- `adapt/direct_compiler.py` (experimental flag path): attach
  `build_feedback_panel(...)` to parsed worksheets so the path stops emitting
  panel-less packages.
- `tests/test_blocking_gates.py`: add the heuristic-2 isolation test — a word
  capitalized mid-sentence in a BODY line that also appears lowercase
  elsewhere is exonerated by lowercase corroboration alone.

## Execution model (owner directive)

Sonnet 5: every implementer and every task reviewer. Fable 5: final
whole-branch review, which MUST audit each task report's red/green TDD
evidence (RED command+output before implementation, GREEN after) and treat
missing evidence as a blocking finding.

## Exit criteria (goal contract)

1. Every implementation task's report contains RED and GREEN TDD evidence;
   Fable's final review verdict is READY TO MERGE with an explicit per-task
   TDD-evidence audit line.
2. `make test`, `make lint`, `make typecheck` all green.
3. Live lesson 74 acceptance run: ZERO exhaustive-coverage ERRORs; and either
   (a) smart planner ships (`judge_verdict.json` approved, `objective_*`
   outcome approved) and 3 pages render, or (b) the planner is rejected and
   the run FAILS BEFORE RENDERING with the actionable policy error (unless
   `WORKSHEET_SHIP_UNAPPROVED=1`). Both are correct behavior; (a) is the
   expected outcome given P3c.
4. Photo path regression-free: exhaustive validator + old advisory judge
   still run there (flag-gated), existing photo tests untouched and green.

## Out of scope

`--record-results` ingestion; jurisdiction→curriculum-standards mapping;
unifying the four concept-pattern implementations (known debt); photo-path
Roll-and-Read pattern filter.
