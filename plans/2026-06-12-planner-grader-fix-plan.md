# Planner Grader-Visibility Fix Plan

> Follow-up to `plans/2026-06-12-planner-simplification-plan.md` (Tasks 0–12 shipped; Task 12 A/B battery FAILED the gate). REQUIRED SUB-SKILL: strict red-green TDD per task.

**Goal:** Make the pedagogical judge SEE the ADHD supports that the planner output already carries, so it stops failing every plan on the `adhd_compliance` sub-score for supports that are actually present. Then re-run the A/B battery against the same promotion gate.

**Root cause (Session 45 diagnosis, confirmed by inspecting a translated planner package):** Every planner cell was rejected almost entirely on `adhd_compliance` (0.12–0.35) while concept/coverage/flow were strong (up to 0.90). But `_translate_plan` + `enforce_section_cap` already populate: per-chunk `time_estimate` ("About 2 minutes"), numbered instruction `Step`s, worksheet `break_prompt` ("Stand up and stretch!"), and final-worksheet `self_assessment`. `adapt/llm_judge.py:_build_judge_prompt()` renders only section/micro_goal, instruction TEXT (no numbers), worked example, and items — it omits time estimates, step numbers, brain breaks, and the self-check list. The judge scores ADHD compliance on information withheld from its prompt. This is a judge-visibility bug, not a planner-quality or threshold problem — so we fix visibility only and do NOT touch the 0.7 threshold or the adhd weighting.

---

### Task 12a: Judge prompt shows the ADHD supports (time estimates, numbered steps, brain breaks, self-check)

**Files:**
- Modify: `adapt/llm_judge.py` (`_build_judge_prompt`)
- Test: `tests/test_llm_judge.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_judge.py` a worksheet fixture that sets `time_estimate`, numbered `instructions`, `break_prompt`, and `self_assessment`, and a test asserting the rendered prompt surfaces all four. Concretely, reuse the existing `_worksheet()` (already has `time_estimate="About 2 minutes"` and `Step(number=1, text="Read it aloud.")`) but extend it / add a sibling fixture with `break_prompt="Stand up and stretch!"` and `self_assessment=["I can read CVCe words"]`, then:

```python
def test_judge_prompt_shows_adhd_supports() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet_with_supports()])

    assert "About 2 minutes" in prompt          # time estimate per section
    assert "1. Read it aloud." in prompt         # numbered instruction steps
    assert "Stand up and stretch!" in prompt     # brain break between worksheets
    assert "I can read CVCe words" in prompt     # self-check list
```

(Add `_worksheet_with_supports()` = the existing `_worksheet()` with `break_prompt` and `self_assessment` set.)

- [ ] **Step 2: Run the test — SEE it fail**

`.venv/bin/pytest tests/test_llm_judge.py::test_judge_prompt_shows_adhd_supports -v`
Expected: FAIL — the time estimate, step numbers, brain break, and self-check are not in the prompt today.

- [ ] **Step 3: Implement**

In `_build_judge_prompt()`'s worksheet-rendering loop:
- Render instructions WITH numbers: `" | ".join(f"{s.number}. {s.text}" for s in chunk.instructions)`.
- Add a per-chunk line for the time estimate when present: `f"      Time estimate: {chunk.time_estimate}"`.
- At the worksheet level, when set, add a `Brain break: {ws.break_prompt}` line and a `Self-check: {', '.join(ws.self_assessment)}` line.

Keep `JudgeVerdict` unchanged. Do not change the evaluation criteria text or any threshold.

- [ ] **Step 4: Run the test — SEE it pass**

`.venv/bin/pytest tests/test_llm_judge.py -v`
Expected: PASS (existing judge tests still green).

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_judge.py tests/test_llm_judge.py
git commit -m "fix: judge prompt surfaces time estimates, numbered steps, brain breaks, self-check"
```

---

### Task 12c: Planner prompt forces individual coverage (no bundling)

Owner-selected fix after the threshold research: coverage is the binding limiter (16/27 rejects), so push planner coverage rather than lower the 0.70 bar.

- [x] **Step 1 (RED):** `tests/test_llm_planner.py::test_prompt_demands_individual_coverage_not_bundling` — assert the prompt requires INDIVIDUAL practice, forbids bundling ("Do NOT bundle", "one item per word"), and requires chains as activities ("not only as a worked example"). Saw it fail.
- [x] **Step 2 (GREEN):** Rewrote CRITICAL RULE 1 in `_build_planner_prompt`: every source word/chain-step/sentence as its own worked item; no bundling / no giant-list options; chains as build activities; full sentences preserved; circle/fill_blank items target one answer with 2-4 single-word options. 605 green; lint + typecheck clean.
- [x] **Step 3:** Commit `fix: planner prompt forces individual source coverage (no bundling)`.

### Task 12b: Re-run the live A/B battery + re-evaluate the gate

- [ ] Re-run the battery on IMG_0003/4/5 (sandbox off, `SSL_CERT_FILE` = venv certifi, `WORKSHEET_LLM_ADAPT=1`).
- [ ] Evaluate the SAME gate: (a) ≥2/3 planner cells `planned_approved`/`planned_regen_approved`, zero error cells; (b) every planner worksheet ≤ grade cap; (c) planner coverage ≥ loop coverage.
- [ ] Record a dated handoff entry with the new scorecard numbers (old vs new).
- [ ] PASS → hand back to the owner to authorize Tasks 13–15. FAIL → diagnose again; still do NOT ship or tune the threshold.

> GATE unchanged: Tasks 13–15 of the parent plan stay blocked until this battery passes and the owner approves.
