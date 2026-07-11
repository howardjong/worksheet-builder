# Finish Line (P3 + Trim Guard + Housekeeping) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lesson-mode validators/judge/planner all speak objective-sufficiency; low-quality fallbacks fail before spending render money; the trimmer can't drop essential forms; print-check false positive silenced; parked minors closed.

**Architecture:** P3a/P3b are convergence wrappers over the already-shipped objective machinery (`adapt/objective_ledger.py`, `validate/objective_coverage.py`, the objective judge in `adapt/llm_judge.py:315-904`) wired into `transform.py`'s existing call sites behind the existing lesson-mode flag. P3c mirrors the D31 one-retry-with-feedback pattern onto the planner's coverage-reject branch. Everything is flag-gated so the photo path is byte-identical.

**Tech Stack:** Python 3.13 (CI mypy 3.11), Pydantic v2, PyMuPDF (test fixtures), pytest.

**Spec:** `docs/superpowers/specs/2026-07-10-finish-line-p3-design.md`

## Global Constraints

- Work in `/Users/hjong/Documents/Projects/worksheet-builder` on branch `claude/review-recent-refactoring-rma786`; venv `.venv/bin/python`; gates `make test` / `make lint` / `make typecheck`.
- **Models (owner directive):** implementers and task reviewers run on **Sonnet 5**; the final whole-branch review runs on **Fable 5** and must audit every task report's red/green TDD evidence — a task without RED (command + failing output, pre-implementation) and GREEN (command + passing output) evidence is a blocking finding.
- Commits: NO Co-Authored-By trailer; `env -u PIP_UPLOADED_PRIOR_TO git commit ...` if hooks need installing; ruff-format abort → `git add -u`, retry.
- TDD is the exit criterion, not a style preference: failing test first for every behavior change, evidence in the task report.
- Flag semantics (verbatim): objective mode = `WORKSHEET_OBJECTIVE_COVERAGE` set (lesson-mode default; photo path unset). New flag `WORKSHEET_SHIP_UNAPPROVED` — set → render despite a not-approved advisory verdict. Judge unavailable (verdict `None`) → ship with loud warning, never abort.
- Photo path byte-identical: exhaustive `validate_content_coverage*` and OLD `judge_adaptation` keep running when the flag is unset; no photo-path test may need modification (if one does, stop and report — that's a design breach).
- LLM-touching tests mock at the `_call_openai`/provider boundary exactly like the existing tests in `tests/test_llm_planner.py` / `tests/test_llm_judge.py` — never call real APIs in tests.

---

### Task 1: P3a — objective-sufficiency package validator (lesson mode)

**Files:**
- Create: `validate/objective_package.py`
- Modify: `transform.py` (call site ~line 953 `_validate_package_content_coverage(...)` and the helper at ~line 1246)
- Test: `tests/test_objective_package.py` (new), `tests/test_transform_lesson.py`

**Interfaces:**
- Produces: `validate.objective_package.validate_objective_package(skill_model: LiteracySkillModel, worksheets: list[AdaptedActivityModel]) -> ObjectiveCoverageResult` (re-exports the existing result type); transform writes `artifacts/validation_objective_coverage.json` and sets `validation_results["content_coverage_passed"]` (True for status `pass`/`needs_verification`, False for `fail`).

- [ ] **Step 1: Failing tests** — `tests/test_objective_package.py`:

```python
"""Post-hoc objective-sufficiency package validation (spec 2026-07-10 P3a)."""

from validate.objective_package import validate_objective_package


def test_package_with_all_essential_forms_passes() -> None:
    skill = _skill_with_essentials()      # word_list + word_chain + passage sources;
    worksheets = _worksheets_covering(skill)   # build via adapt.engine.adapt_lesson(...)
    result = validate_objective_package(skill, worksheets)
    assert result.status in ("pass", "needs_verification")


def test_package_missing_required_form_fails() -> None:
    skill = _skill_with_essentials()
    worksheets = _worksheets_covering(skill)
    # Strip every chunk whose response format / content is the word chain.
    gutted = [_remove_chain_chunks(ws) for ws in worksheets]
    result = validate_objective_package(skill, gutted)
    assert result.status == "fail"
    failing = [c for c in result.objective_results if c.status == "fail"]
    assert any("word_chain" in c.missing_required_forms for c in failing)
```

Build `_skill_with_essentials` by copying the fixture from `tests/test_workload.py` (added in the dosage plan — it yields obj_decode/encode/manipulation/connected_text). `_worksheets_covering` = run `adapt.engine.adapt_lesson` (deterministic, no LLM) on that skill with a plain profile; `_remove_chain_chunks` drops chunks whose items came from chain sources (filter on chunk content containing the chain step language, or simplest: drop the chunk whose response_format the engine uses for chains — read `_build_builder_chunks` usage to pick the right discriminator and document it in the test).

Add to `tests/test_transform_lesson.py` (reuse `_stub_lesson_pipeline`): assert that with objective mode enabled the artifacts dir contains `validation_objective_coverage.json` and NOT a package-coverage ERROR log, and that `validation_results["content_coverage_passed"]` is True for the stub package.

Run: `.venv/bin/python -m pytest tests/test_objective_package.py -v` → FAIL (module missing).

- [ ] **Step 2: Implement `validate/objective_package.py`**

```python
"""Post-hoc objective-sufficiency validation for a finished lesson package.

Thin composition of the machinery the LLM planner already uses, so the
package validator and the planner can never disagree about what "covered"
means (Q4/P3a). Photo path keeps validate/content_coverage.py.
"""

from __future__ import annotations

from adapt.objective_ledger import build_objective_ledger
from adapt.schema import AdaptedActivityModel
from skill.schema import LiteracySkillModel
from validate.objective_coverage import (
    ObjectiveCoverageResult,
    build_evidence_index,
    evaluate_objective_coverage,
)

__all__ = ["validate_objective_package", "ObjectiveCoverageResult"]


def validate_objective_package(
    skill_model: LiteracySkillModel,
    worksheets: list[AdaptedActivityModel],
) -> ObjectiveCoverageResult:
    ledger = build_objective_ledger(skill_model)
    evidence = build_evidence_index(worksheets, ledger)
    return evaluate_objective_coverage(ledger, evidence, worksheets=worksheets)
```

- [ ] **Step 3: Wire transform.py**

At the package-validation call site (~:953): when objective mode is on (read the same env flag the lesson defaults set — `os.environ.get("WORKSHEET_OBJECTIVE_COVERAGE")`), call the new validator, `json.dump` its `model_dump(mode="json")` to `artifacts/validation_objective_coverage.json`, log `status`/failing cells at INFO (`needs_verification` gets an advisory INFO note, NOT an ERROR), and set `content_coverage_passed = result.status != "fail"`. Flag off → existing `_validate_package_content_coverage` exactly as today. Keep the downstream `all_validators_passed` aggregation untouched.

- [ ] **Step 4: GREEN + commit**

Run: `.venv/bin/python -m pytest tests/test_objective_package.py tests/test_transform_lesson.py -v` → PASS.

```bash
git add validate/objective_package.py transform.py tests/
git commit -m "feat: lesson packages validated by objective sufficiency, not word exhaustion (P3a)"
```

---

### Task 2: P3b — advisory objective judge + fail-before-render policy

**Files:**
- Modify: `adapt/llm_judge.py` (new public wrapper near the objective-judge section, lines 315-904)
- Modify: `transform.py` Stage 5c (~:769-811) and the render entry (~:813-830)
- Test: `tests/test_llm_judge.py`, `tests/test_transform_quality_gates.py`

**Interfaces:**
- Consumes: `validate_objective_package` inputs pattern (ledger/evidence building) — reuse internals already present in the objective-judge path.
- Produces: `adapt.llm_judge.judge_package_objective(skill_model: LiteracySkillModel, worksheets: list[AdaptedActivityModel]) -> ObjectiveJudgeVerdict | None` (None on ANY infra/API failure — never raises); transform behavior per policy matrix below.

Policy matrix (objective mode only; photo path untouched):

| Situation | Behavior |
|---|---|
| `judge_verdict.json` exists (planner approved) | unchanged readback, render |
| advisory verdict approved | render |
| advisory verdict NOT approved, `WORKSHEET_SHIP_UNAPPROVED` unset | **abort before any rendering**: raise `UnapprovedPackageError` (new, in transform.py) whose message names the failing criteria/defects and both remedies ("re-run" / "set WORKSHEET_SHIP_UNAPPROVED=1"); CLI exits non-zero; artifacts (incl. the verdict json) remain on disk |
| advisory NOT approved, flag set | render + loud warning |
| verdict None (judge unavailable) | render + loud warning ("advisory judge unavailable — shipping unjudged deterministic package") |

- [ ] **Step 1: Failing tests**

`tests/test_llm_judge.py`: `test_judge_package_objective_returns_verdict` — monkeypatch the module's OpenAI call boundary (same fixture style as the existing objective-judge tests in this file) to return a canned approving JSON; assert an `ObjectiveJudgeVerdict` with `approved is True`. `test_judge_package_objective_none_on_api_failure` — boundary raises → returns None.

`tests/test_transform_quality_gates.py` (reuse its `_stub_lesson_pipeline`-style harness and `fake_adapt_lesson` seam): three tests — not-approved verdict + flag unset → pipeline raises `UnapprovedPackageError` AND no render artifacts/PDF are produced; same + `monkeypatch.setenv("WORKSHEET_SHIP_UNAPPROVED", "1")` → PDF produced + warning logged; judge returning None → PDF produced + "unavailable" warning. Stub `judge_package_objective` itself at the transform import site for these three (the judge's own behavior is covered in test_llm_judge.py).

Run both files → new tests FAIL.

- [ ] **Step 2: Implement**

`adapt/llm_judge.py`: `judge_package_objective` composes exactly what the planner-path objective judging does — build ledger, `build_evidence_index`, `evaluate_objective_coverage` for the FINAL FACTS block, then the existing `_build_objective_judge_prompt` + provider call + verdict parse/aggregation helpers (reuse the existing private functions; do NOT duplicate prompt text). Wrap the whole body in try/except → `logger.warning(...); return None`.

`transform.py`: define near the top:

```python
class UnapprovedPackageError(RuntimeError):
    """Fallback package failed the advisory objective judge (spec 2026-07-10 P3b).

    Raised BEFORE rendering so a low-quality package never spends image-
    generation budget. Override: WORKSHEET_SHIP_UNAPPROVED=1.
    """
```

Stage 5c else-branch: objective mode → `judge_package_objective`; write verdict (or `{"enabled": False, "unavailable": True}`) to `judge_verdict.json` as today; apply the policy matrix BEFORE the render loop starts (the abort goes right after Stage 5c, before `pdf_paths` work begins). Photo path: `judge_adaptation` branch preserved verbatim.

- [ ] **Step 3: GREEN + commit**

Run: `.venv/bin/python -m pytest tests/test_llm_judge.py tests/test_transform_quality_gates.py -v` → PASS.

```bash
git add adapt/llm_judge.py transform.py tests/
git commit -m "feat: advisory verdict = objective judge; low score fails before render spend (P3b)"
```

---

### Task 3: P3c — one coverage-retry with targeted feedback

**Files:**
- Modify: `adapt/llm_planner.py` (coverage-reject branch ~:606-639; prompt assembly)
- Test: `tests/test_llm_planner.py`

**Interfaces:**
- Produces: on first `coverage.status == "fail"`, planner issues exactly ONE regeneration whose prompt ends with a feedback block; `planner_attempts.json` gains `coverage_retry: {"attempted": true, "first_failure": {...}, "second_outcome": "..."}`. Outcomes after retry: pass/needs_verification → continue to judge as normal; fail again → existing `_objective_fallback(..., "objective_rejected_coverage", ...)` with BOTH failures in details.

- [ ] **Step 1: Failing tests** — extend `tests/test_llm_planner.py` using its existing mocked-provider pattern:

```python
def test_coverage_fail_triggers_single_retry_with_feedback() -> None:
    # Provider returns plan A (no chain activity) then plan B (with chain).
    # Coverage evaluator: fail for A, pass for B (monkeypatch evaluate_objective_coverage
    # sequence, or author fixture plans that genuinely differ).
    # Assert: provider called exactly twice; second prompt contains
    # "REJECTED" and "obj_manipulation" and "word_chain"; final outcome proceeds
    # to judge (not fallback); planner_attempts.json has coverage_retry.attempted True.


def test_coverage_fail_twice_falls_back_with_both_attempts() -> None:
    # Both plans fail coverage. Assert: exactly two provider calls (no third),
    # outcome objective_rejected_coverage, attempts file records first_failure
    # AND second failure details.
```

(Write them as real tests with the file's existing helpers — the assertions above are binding; flesh out arrange/act with the same monkeypatch seams the file already uses for gates/judge.)

Run → FAIL (single-shot today).

- [ ] **Step 2: Implement**

Feedback block builder (module-level, near the fallback helpers):

```python
def _coverage_feedback_block(coverage: ObjectiveCoverageResult) -> str:
    lines = [
        "## REVISION REQUIRED — previous plan rejected by deterministic coverage",
        "Fix EVERY item below; keep everything else that was working.",
    ]
    for cell in coverage.objective_results:
        if cell.status != "fail":
            continue
        missing = ", ".join(cell.missing_required_forms) or "insufficient distinct practice"
        lines.append(
            f"- {cell.objective_id}: REJECTED — missing/insufficient: {missing}. "
            f"Your revised plan MUST satisfy this objective IN its required form."
        )
    for breach in coverage.package_bounds.breaches:
        lines.append(f"- PACKAGE BOUND BREACH: {breach}")
    return "\n".join(lines)
```

In the coverage-reject branch: first failure → log, rebuild the prompt as `original_prompt + "\n\n" + _coverage_feedback_block(coverage)`, re-call the provider chain once, re-run blocking gates AND coverage on the retry plan (gates fail on retry → existing gate fallback path). Record `coverage_retry` in the attempts payload in all outcomes. Guard: retry only once (a plain local flag, no loops).

- [ ] **Step 3: GREEN + commit**

Run: `.venv/bin/python -m pytest tests/test_llm_planner.py -v` → PASS.

```bash
git add adapt/llm_planner.py tests/test_llm_planner.py
git commit -m "feat: coverage-rejected plans get one retry with per-cell feedback (P3c)"
```

---

### Task 4: Objective-aware package trim

**Files:**
- Modify: `adapt/section_cap.py` (`enforce_package_cap`), `adapt/engine.py` (`_finalize_lesson_package` ~:110-129 passes required-form info)
- Test: `tests/test_section_cap.py`

**Interfaces:**
- Produces: `enforce_package_cap(worksheets, max_worksheets, fallback_feedback=None, essential_forms: dict[str, list[int]] | None = None)` where `essential_forms` maps required-form name → indices of worksheets (pre-trim order) carrying that form. Engine computes it from the ledger + worksheet contents (helper `_essential_form_carriers(skill, worksheets) -> dict[str, list[int]]` in `adapt/engine.py`, matching form to sheets via the same discriminators `build_evidence_index` uses — read it and reuse its classification, do not invent a parallel one).

- [ ] **Step 1: Failing test** — `tests/test_section_cap.py`:

```python
def test_package_cap_never_drops_sole_carrier_of_essential_form() -> None:
    # 5 sheets; only sheet index 4 ("Story Time") carries decodable_passage.
    # Cap 2 with essential_forms={"decodable_passage": [4]}.
    capped = enforce_package_cap(sheets, 2, essential_forms={"decodable_passage": [4]})
    titles = [ws.worksheet_title for ws in capped]
    assert "Story Time" in titles          # seeded survivor
    assert len(capped) == 2                # cap still hard
```

Plus: seeding never EXCEEDS the cap (essential forms > cap → keep the first `cap` seeds, log loudly); no `essential_forms` → byte-identical round-robin behavior (existing tests must pass unchanged).

Run → FAIL (Story Time dropped today).

- [ ] **Step 2: Implement** — in `enforce_package_cap`, before the round-robin: `seeds = []`; for each form, if none of its carrier indices would survive the plain round-robin selection, append its first carrier worksheet to `seeds` (dedup). Selection = seeds first, then round-robin fill skipping already-selected, stopping at `max_worksheets`. Renumber/hint logic unchanged. In `adapt/engine.py::_finalize_lesson_package`, compute and pass `essential_forms=_essential_form_carriers(skill, capped)` (only when a cap is engaged).

- [ ] **Step 3: GREEN + commit**

Run: `.venv/bin/python -m pytest tests/test_section_cap.py tests/test_adapt.py -v` → PASS.

```bash
git add adapt/section_cap.py adapt/engine.py tests/
git commit -m "feat: package trim never drops the sole carrier of an essential form"
```

---

### Task 5: Print-check overlap false positive

**Files:**
- Modify: `validate/print_checks.py` (overlap detection)
- Test: `tests/test_print_checks.py` (or wherever that validator's tests live — `grep -rln print_checks tests/`)

- [ ] **Step 1: Reproduce in a failing test** — build a synthetic one-page PDF in the test exactly like `render/image_gen.py::_write_page_pdf` does (full-page image via `page.insert_image`, then `insert_textbox(..., render_mode=3, fontsize=2)` invisible text), run the overlap check, and assert NO overlap warning. Expected today: FAIL (warning fires) — this is the RED that proves the diagnosis. If it does NOT fire, the hypothesis is wrong: STOP, investigate what does trigger "(0, 0)" on real artifacts (`output/lesson74_dosage/`), and report findings before coding.

- [ ] **Step 2: Fix** — in the overlap detector, skip text spans rendered invisibly (PyMuPDF exposes span flags/render mode via `page.get_text("rawdict")`; filter spans whose font size < 3pt AND that sit under the image z-order, or — cleaner if available — spans with render_mode 3). Keep genuine visible-text-over-image detection intact: add a companion test where VISIBLE text overlaps the image and the warning still fires.

- [ ] **Step 3: GREEN + commit**

```bash
git add validate/print_checks.py tests/
git commit -m "fix: overlap check ignores the invisible searchable text layer on image pages"
```

---

### Task 6: Minors sweep

**Files:**
- Modify: `render/design_spec.py` (`_required_text`), `adapt/direct_compiler.py`, `tests/test_blocking_gates.py`
- Test: `tests/test_worksheet_design_spec.py`, `tests/test_direct_compiler.py` (check name via `grep -rln direct_compiler tests/`)

- [ ] **Step 1: TDD each (three small red/green cycles, one commit):**

1. `_required_text` appends `adapted.feedback.parent_log_title` when feedback present (test: `"Grown-up quick log" in spec.required_text`). Add the code comment: `# DECISION_HINT stays gate-unverified: demanding a ~150-char string from the OCR gate trades real flakiness for marginal value (spec 2026-07-10 §6).`
2. `adapt/direct_compiler.py`: parsed worksheets get `feedback=build_feedback_panel(skill.domain, skill.specific_skill)` when the field is absent (test with the file's existing parse fixture).
3. `tests/test_blocking_gates.py::test_lowercase_corroboration_alone_exonerates`: source item body line `"We saw Bumpy roads today. The bumpy road was long."` — "Bumpy" capitalized mid-sentence in a NON-title segment (so heuristic 1 can't help) but lowercase elsewhere → no violation for item content `"Read bumpy aloud."`.

- [ ] **Step 2: Commit**

```bash
git add render/design_spec.py adapt/direct_compiler.py tests/
git commit -m "chore: gate-verify parent log title; direct-compiler feedback; gate heuristic-2 test"
```

---

### Task 7: Full gates + live acceptance + Fable final review (controller-run)

- [ ] **Step 1:** `make test && make lint && make typecheck` — all green.
- [ ] **Step 2:** Live run: `.venv/bin/python transform.py --lesson 74 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson74_finish/`. Acceptance per spec exit criteria: ZERO exhaustive-coverage ERRORs; either `objective_approved` + 3 rendered pages, or a pre-render `UnapprovedPackageError` with the actionable message. Inspect `planner_attempts.json` for the coverage_retry record if a retry fired.
- [ ] **Step 3:** Final whole-branch review on **Fable 5** with the review package for the full plan range; its dispatch must instruct a per-task TDD-evidence audit (RED + GREEN in each task report) with missing evidence = blocking finding, plus the standard cross-task seam review and ledger-Minor triage.
- [ ] **Step 4:** Only after READY TO MERGE: update `.claude/worksheet-project-context.md` (Q4 → RESOLVED, chip task_46163d0f → dismiss, session entry) — then stop for owner review/push decision.
