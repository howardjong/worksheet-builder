# B′ — Gate Protocol Fix (make the A/B battery trustworthy)

> Step 2 of `plans/2026-06-12-next-move-fable5.md`. Follows Session 46 (Fix A + D-small).
> REQUIRED SUB-SKILL: strict red-green TDD per task. All changes are measurement-only
> and env/CLI-gated — production defaults (planner-v2 OFF, judge runs once) are unchanged.

**Why:** A single battery cell conflates non-deterministic vision extraction + planner
quality + judge sampling noise. IMG_0005 swung 0.91→0.61 on the same image because vision
put the worksheet header into the "concept" (now fixed at the source in Session 46). To make
a pass/fail mean something we also remove the two remaining noise sources and require
stability across runs.

**Defaults chosen:** N = 3 for median-of-N judging; "2 consecutive passing runs" = two
separate full battery invocations that both pass the gate.

---

### Task B1: Freeze vision extraction per image (cache the source model)

**Files:** `transform.py`; test `tests/test_extraction_cache.py` (new).

Non-determinism lives in `extract_with_vision`. Cache its output (the `SourceWorksheetModel`)
once per image so every battery cell — loop and planner, across runs — consumes identical
input. `extract_skill` is already deterministic given a source model.

- Factor the current vision-primary/OCR-fallback block into `_resolve_source_model(input_path,
  preprocessed_path, image_hash) -> SourceWorksheetModel` (pure move, no behavior change).
- Add `_source_model_with_cache(...)` gated by `WORKSHEET_EXTRACTION_CACHE=<dir>`: on cache hit
  load `<dir>/<image_hash>.source_model.json` and skip vision; on miss resolve then write it.
  When the env var is unset, behave exactly as today (no cache I/O).
- Wire `run_pipeline_collect_artifacts` to call `_source_model_with_cache`.
- RED test: monkeypatch `_resolve_source_model` with a call counter; with the cache dir set,
  two calls → resolver invoked once and both source models equal; without it → invoked twice.

### Task B2: Median-of-N judging (remove judge sampling noise)

**Files:** `adapt/llm_judge.py`, `adapt/llm_planner.py`; tests `tests/test_llm_judge.py`,
`tests/test_llm_planner.py`.

- `_aggregate_verdicts(verdicts) -> JudgeVerdict` (pure): a single verdict returns unchanged
  (zero production change); multiple verdicts → median of each numeric field, `approved`
  recomputed from the medians per the documented rule (overall ≥ 0.70 and no criterion < 0.50),
  prose (feedback/rationale) taken from the sample whose overall is closest to the median.
- `judge_adaptation_samples(skill, worksheets, samples)`: call `judge_adaptation` `samples`
  times, drop `None`s, aggregate; return `None` only if every call failed.
- `plan_lesson_llm` reads `WORKSHEET_JUDGE_SAMPLES` (default 1, clamp ≥ 1) and routes the
  judge through `judge_adaptation_samples`. Default 1 ⇒ byte-identical to today.
- RED tests: `_aggregate_verdicts` medians + approval recompute on synthetic verdicts; single
  verdict returned unchanged; `judge_adaptation_samples` calls the judge N times (monkeypatched).

### Task B3: Gate evaluation + two consecutive runs

**Files:** `adapt_battery.py`; test `tests/test_adapt_battery.py`.

- `evaluate_gate(rows) -> GateResult{passed, reasons}` (pure), encoding the documented gate:
  (a) ≥ 2 of 3 planner cells approved (`judge_approved` True, outcome in
  {planned_approved, planned_regen_approved}) and zero planner error cells;
  (b) every planner cell `adhd_compliance_passed` True (the section-cap hard error lives there);
  (c) planner content-coverage ≥ loop content-coverage.
- `gate_over_runs(results) -> bool`: True iff two consecutive runs both pass.
- `--runs N` (default 1): run the battery N times; print per-run gate + the consecutive verdict.
  Scorecard gains a "## Gate" section from `evaluate_gate`.
- RED tests: `evaluate_gate` PASS/FAIL on synthetic row sets; `gate_over_runs` consecutive logic.

### Task B4: Honest live re-run (owner environment)

Not offline. Run `--runs 2` with the extraction cache pre-warmed per image, `WORKSHEET_JUDGE_SAMPLES=3`,
sandbox off, `SSL_CERT_FILE` set, on IMG_0003/4/5. Record both scorecards + the consecutive
verdict in the context doc. Expected: IMG_0003+IMG_0005 pass → 2/3; IMG_0004 → safe fallback.
Do NOT touch parent-plan Tasks 13–15.
