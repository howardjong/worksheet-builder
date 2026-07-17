# Lesson-101 fix traceability (spec 2026-07-16, D48/D49)

| Defect | Fix commit(s) | Named test(s) | RED evidence | GREEN evidence |
|--------|---------------|---------------|--------------|----------------|
| **D48** — LLM-planner-authored `word_chain` activities bypassed the stamped deterministic parser (`metadata={"display":"chain_step"}`), so the coverage evaluator's anti-gaming chain discriminator (`validate/objective_coverage.py::_CHAIN_DISPLAYS`) could never count them; suffix-pair words parsed to 0 items; and the planner prompt still told the model to author `word_chain` as inline `items`. | Task 1 `45f9529` (code half) + Task 2 `e2e16b6` (prompt half) | `test_suffix_word_chain_uses_mechanical_builder_even_with_items`; `test_letter_word_chain_uses_mechanical_builder_even_with_items`; `test_suffix_word_chain_words_parse_to_items`; `test_translated_suffix_chain_passes_manipulation_coverage` (all `tests/test_llm_adapt.py`); `test_prompt_rule5_and_chain_example_use_words_format`; `test_coverage_feedback_names_word_chain_words_format` (both `tests/test_llm_planner.py`) | **Task 1 Step 2** — `.venv/bin/python -m pytest tests/test_llm_adapt.py -k "word_chain or manipulation_coverage" -v` → `4 failed, 10 deselected`. Key lines: `assert all(i.metadata.get("display") == "chain_step" for i in items)` → `assert False`; `AssertionError: suffix chain worksheet must survive translation / assert []`; `required_forms_present=False, missing_required_forms=['word_chain'], notes=['no authored build/change chain present → required-form fail']`. **Task 2 Step 2** — `.venv/bin/python -m pytest tests/test_llm_planner.py -k "words_format" -v` → `2 failed, 40 deselected`. Key lines: `assert '"match", "sound_box", and "word_chain"' in prompt` → `AssertionError` (prompt still said `5. For "match" and "sound_box" activities...`); `assert '"words"' in block` → `AssertionError` (retry feedback lacked the words-format hint). | **Task 1 Step 4** — same command → `4 passed, 10 deselected in 0.14s`. **Task 2 Step 4** — `.venv/bin/python -m pytest tests/test_llm_planner.py -v` → `42 passed in 0.28s` (both new D48 tests + updated D12 assertion `assert '"words": ["quick → quickly"' in block`). |
| **D49** — the manipulation cell handed the advisory judge a multi-hop `sufficiency_rule` (`≥1 coherent build/change chain`) that single-suffix lessons (e.g. `-ly`, single-hop pairs like `quick → quickly`) structurally cannot satisfy, so correct add-the-ending items drew `wrong_cognitive_task` severe-defect votes. | Task 3 `eb2d87e` | `test_single_hop_suffix_lesson_gets_pair_sufficiency_rule` (`tests/test_objective_ledger.py`); `test_wrong_cognitive_task_gloss_defers_to_sufficiency_rule` (`tests/test_llm_judge.py`). Born-green regression guards: `test_multi_hop_suffix_lesson_keeps_chain_rule_byte_identical`; `test_mixed_chain_suffix_lesson_counts_as_multi_hop`; `test_non_suffix_lesson_keeps_chain_rule_even_with_pair_chains`; `test_objective_prompt_carries_single_hop_manipulation_rule`. | **Task 3 Step 2** — `.venv/bin/python -m pytest tests/test_objective_ledger.py -k "sufficiency_rule or chain_rule or multi_hop" -v` → `1 failed, 3 passed`: `AssertionError: assert '≥1 coherent ...s, not words)' == '≥2 add-the-e...pulation form'` (single-hop lesson still got the multi-hop rule). And `.venv/bin/python -m pytest tests/test_llm_judge.py -k "single_hop or defers_to" -v` → `1 failed, 1 passed`: `assert 'Do NOT vote this defect when the package exercises the cognitive task' in '...<prompt without guard line>...'`. | **Task 3 Step 4** — `.venv/bin/python -m pytest tests/test_objective_ledger.py tests/test_llm_judge.py -v` → `110 passed in 0.30s`. |

## Live acceptance evidence

Runs performed once each (no `WORKSHEET_SHIP_UNAPPROVED`, `.env` keys, single-sample judge — no retry loop). Profile `profiles/ian.yaml`, theme `roblox_obby`.

### Lesson 101 (r2): PASS-ON-TARGET — aborts pre-render on the known connected-text blocker only; `obj_manipulation` clean.

`.venv/bin/python transform.py --lesson 101 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson101_uat_r2/`

- **Abort:** `UnapprovedPackageError` (overall=0.63, recommendation=reject). Failing criteria/defects: `["obj_connected_text (quality=0.34, defects=['overwhelming_or_adhd_unsafe'])"]`.
- **Failing-criteria set:** `{obj_connected_text}` — exactly the known, owner-accepted blocker (`overwhelming_or_adhd_unsafe`, task_202def01). No other objective carries severe defects.
- **`obj_manipulation`: quality 0.82, severe_defects=[], severe_defect_vote="none"** — ZERO severe-defect votes. PASS condition met. Judge rationale credits the D49 fix directly: *"The lesson appropriately uses base-plus-suffix transformations, which is the right manipulation form for this suffix lesson."* Evidence ids include `ws0_chunk1_stitched_chain` and `ws0_chunk1_item1/2_content` — confirming D48 stamped chain items flowed through.
- **Planner outcome** (`planner_attempts.json`): `outcome="objective_rejected_gate"`, `planner_version=2`, **`objective_coverage=true`** — an LLM plan (v2) passed deterministic coverage this run, which includes the manipulation/`word_chain` required form. This is the **D48 live signal**: LLM-planned chain activity now satisfies coverage instead of being silently discarded. (The plan was subsequently rejected at the gate stage for one unrelated capitalization blocker on `ws2_chunk2_item10` — "proper noun 'read' appears lowercased mid-sentence" — not a manipulation/coverage failure.)

### Lesson 74 (r3): PASS — failing-criteria set matches baseline.

`.venv/bin/python transform.py --lesson 74 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson74_uat_r3/`

- **Abort:** `UnapprovedPackageError` (overall=0.74, recommendation=reject). Failing criteria/defects: `["obj_connected_text (quality=0.69, defects=['overwhelming_or_adhd_unsafe'])"]`.
- **Failing-criteria set:** `{obj_connected_text}` — **identical to session-61 baseline** (`{obj_connected_text}`). `obj_manipulation` clean (quality 0.63, no defects). Planner: `outcome="objective_rejected_coverage"`, `objective_coverage=true`, 0 gate violations. No regression.

### Lesson 100 (r3): FAILED-ON-TARGET — NEW failing criterion `obj_manipulation` vs baseline. BLOCKING REGRESSION for owner.

`.venv/bin/python transform.py --lesson 100 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson100_uat_r3/`

- **Abort:** `UnapprovedPackageError` (overall=0.63, recommendation=reject). Failing criteria/defects: `["obj_manipulation (quality=0.28, defects=['wrong_cognitive_task', 'generic_activity_not_exercising_objective'])", "obj_connected_text (quality=0.51, defects=['overwhelming_or_adhd_unsafe'])"]`.
- **Failing-criteria set:** `{obj_manipulation, obj_connected_text}` — **session-61 baseline was `{obj_connected_text}` only**. `obj_manipulation` is a NEW failing criterion, and it is exactly the objective the brief flagged as the blocking-regression watch. Per the brief this is a blocking regression: recorded verbatim, not overridden, not re-run.
- **`obj_manipulation` verdict verbatim** (quality 0.28, severe_defect_vote="none"):
  - `wrong_cognitive_task` — *"ws0_chunk1_stitched_chain and ws0_chunk2_stitched_chain show an inferred chain in metadata, but the student-facing worksheet only presents add-the-ending writing tasks in ws0_chunk1_item1_content through ws0_chunk2_item7_content; the child is not actually asked to build and change words in a visible word-chain routine."*
  - `generic_activity_not_exercising_objective` — *"ws0_chunk1_item1_content through ws0_chunk2_item7_content are generic suffix-addition items, not an explicit build/change chain where the child manipulates one word into another step by step."*
- **Planner outcome:** `outcome="objective_rejected_judge"`, `planner_version=2`, `objective_coverage=true`, 0 gate violations. The LLM plan passed deterministic coverage; the advisory judge rejected it on manipulation.
- **Interpretation (for owner, not a fix):** Lesson 100 is `-er/-est` with 3-word chains → `multi_hop` per the offline snapshot, so the D49 fix deliberately left its sufficiency_rule as the byte-identical multi-hop `≥1 coherent build/change chain`. The judge complaint is a mismatch between that multi-hop rule and the actual rendered items, which this run presented as pair-style "add-the-ending" tasks rather than a visible multi-step chain. Whether this is (a) single-sample judge non-determinism on the same content that scored clean in session 61, or (b) a real interaction between the D48 routing change and lesson 100's multi-hop rendering, is an OWNER decision — the residual-risk fallbacks in the spec are owner-owned. NO production code was changed to chase it.

## Offline snapshot (Step 1, no network)

`WORKSHEET_LLM_ADAPT=0 WORKSHEET_PLANNER_V2=0 .venv/bin/python` over lessons 74, 100, 101, printing `obj_manipulation.sufficiency_rule`:

```
74 '≥1 coherent build/change chain (count steps, not words)'
100 '≥1 coherent build/change chain (count steps, not words)'
101 "≥2 add-the-ending transformations (base + suffix → new word); this suffix forms no multi-step chain, so independent pairs ARE this lesson's manipulation form"
```

Matches expected: lesson 101 gets the single-hop add-the-ending rule; lessons 74 and 100 keep the byte-identical multi-hop rule. Confirms `_chain_shape` classifies 101 as `single_hop` and 74/100 as `multi_hop` (D49).

### Lesson 100 (r4) — owner-directed confirm re-run (noise-hypothesis test)

r3's obj_manipulation veto (0.28, wrong_cognitive_task + generic_activity) did NOT
reproduce: r4 scored obj_manipulation 0.42 with ZERO severe defects. Failing set =
{obj_connected_text} (0.71, overwhelming_or_adhd_unsafe) — matches the session-61
baseline exactly. Overall 0.72 reject on the known blocker only. Planner outcome:
objective_rejected_gate. Adjudication: r3 was a single-sample judge swing; exit
criterion 4 satisfied on the r4 run. OPEN FOLLOW-UP (Q5-adjacent): er/est manipulation
quality sits in a weak 0.28-0.46 band across 3 runs because the multi-hop rule text
never matches the base-anchored add-the-ending form suffix lessons actually render —
extending the suffix-aware wording to multi-hop suffix lessons remains the
mechanism-backed hardening, deferred by owner choice 2026-07-16.
