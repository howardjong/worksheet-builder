# Lesson-101 UAT fixes: manipulation-objective coverage for single suffixes

**Date:** 2026-07-16
**Status:** Draft v2 — pending owner review. v1's D49 design was overturned by
empirical verification (see "Root-cause verification"); this version targets
the layer that actually fails.
**Scope:** LLM-plan translation (`adapt/llm_adapt.py`), planner prompt + retry
feedback (`adapt/llm_planner.py`), manipulation-cell authoring
(`adapt/objective_ledger.py`), judge handed-facts rendering (`adapt/llm_judge.py`)
**Source:** owner UAT of lesson 101 (`-ly`, single non-comparative suffix), the
first live test since the session-61 lesson-100 (`-er/-est`, paired comparative
suffix) fix cycle. Run: `output/lesson101_uat/` (transform aborted pre-render,
no override). All findings verified by code-level repro and an offline
deterministic-engine coverage run, not just log inspection.

## Background

Lesson 100 validated the suffix-morphology taxonomy and chain-authoring fixes
(D13, D1, D11/D12 — `docs/superpowers/specs/2026-07-13-lesson100-uat-fixes-design.md`)
against `-er/-est`: a **paired comparative** suffix whose UFLI corpus supplies
genuine multi-hop chains (`slow → slower → slowest`). Lesson 101 (`-ly`) is the
first **single** suffix tested; its corpus chains are single-hop pairs only
(`quick → quickly` — confirmed in `output/lesson101_uat/artifacts/skill_model.json`).

The transform aborted with `UnapprovedPackageError`. One failing criterion
(`obj_connected_text`, `overwhelming_or_adhd_unsafe`) is the known, queued
passage-density blocker (`task_202def01`) — out of scope here. The second,
`obj_manipulation` (quality 0.26, defects `wrong_cognitive_task` +
`generic_activity_not_exercising_objective`), is new and traces to two
independent, code-verified root causes.

### Defect ledger

| # | Defect | Root cause | Location |
|---|--------|-----------|----------|
| D48 | LLM-planner-authored `word_chain` activities can never satisfy the manipulation objective's deterministic coverage check — for ANY lesson type, suffix or letter-chain — regardless of content quality. Both live planner attempts on lesson 101 failed coverage with "no authored build/change chain present" even though a direct repro of the same prompt shows GPT-5.4 authoring correct chain content (`"Make quick. Add -ly. Write the new word."` → `quickly`). | `_items_for_activity` prefers model-authored `activity.items` for `word_chain` (only `match`/`sound_box` are forced through the deterministic builders via `_MECHANICAL_FORMATS`). The preferred path, `_items_from_planned`, builds `ActivityItem`s with **no `metadata` stamp**. But the coverage evaluator's chain detector (`_CHAIN_DISPLAYS`) counts ONLY items stamped `metadata={"display": "chain_step"}` by the deterministic parsers — a *deliberate anti-gaming discriminator*: "a model cannot assert this stamp" (`validate/objective_coverage.py:341-346`). Net: the path meant to let the LLM author chains bypasses the only mechanism that makes chains count. The planner path fails this objective by construction; coverage-retry feedback can't fix it because no phrasing of authored items ever gets stamped. | `adapt/llm_adapt.py:374,384-393` (`_MECHANICAL_FORMATS`, `_items_for_activity`), `adapt/llm_adapt.py:396-429` (`_items_from_planned`, no stamp), `validate/objective_coverage.py:341-347` |
| D49 | The deterministic engine's own fallback package — correctly stamped, correctly rendered per the D1 design (`light + -ly → ______` items) — is rejected by the advisory judge: `wrong_cognitive_task` ("do not ask the child to build/change along a chain") + `generic_activity_not_exercising_objective`, quality 0.26, aborting the run. | **Not** the deterministic coverage layer — verified: the engine package PASSES `evaluate_objective_coverage` today, all four cells including `obj_manipulation` (`_chain_covers` accepts the stitched `light -> lightly -> deep -> deeply` sequence against the 2-word ledger chains). The failing layer is the **judge's handed facts**: the manipulation cell's `sufficiency_rule` — `"≥1 coherent build/change chain (count steps, not words)"` (`adapt/objective_ledger.py:791`) — is rendered verbatim into the judge prompt (`adapt/llm_judge.py:365-376`) and describes a multi-step chain that a single suffix structurally cannot form (no `quick → quicklier` exists). Judged against that rule, independent add-the-ending pairs ARE a wrong cognitive task. The judge also discounts the stitched chain unit as "a chain in metadata, not a usable student-facing manipulation activity" — correctly, since the stitched unit is evidence bookkeeping, not page content. This is the same rubric-blind-spot class as Q5's known er/est finding (obj_manipulation 0.46 there, but no severe-defect votes, so it passed; single-suffix lessons push the same gap over the veto line). | `adapt/objective_ledger.py:787-791` (cell authoring), `adapt/llm_judge.py:365-376` (handed-facts rendering), judge rubric text |

### Root-cause verification (empirical, not log inspection)

1. **Planner authors fine.** Called `_build_planner_prompt` + `_call_planner`
   directly for lesson 101: GPT-5.4 produced a valid `word_chain` activity
   with correct items (`"Make quick. Add -ly. Write the new word."` →
   `quickly`). Rules out "model skips the requirement" — the surface reading
   of the coverage-failure log line.
2. **Translation drops the stamp.** `_items_from_planned`
   (`adapt/llm_adapt.py:420-428`) constructs `ActivityItem`s with no
   `metadata=` argument; `_CHAIN_DISPLAYS`' design comment confirms the stamp
   is intentionally unforgeable by a model. Structural mismatch, not oversight.
3. **Deterministic coverage PASSES lesson 101 today.** Offline run of the
   deterministic engine (`WORKSHEET_LLM_ADAPT=0`) + `build_evidence_index` +
   `evaluate_objective_coverage`: `status=pass`, all four cells pass,
   `obj_manipulation` `required_forms_present=True`, stitched chain
   `light -> lightly -> deep -> deeply` tagged to the cell. **The v1 spec's
   claim that the sufficiency evaluator needs relaxing for single-hop suffixes
   was wrong; no evaluator change is needed or wanted.**
4. **The D48 GREEN path needs the suffix parser.**
   `_build_items_from_activity` invoked with
   `words=["quick → quickly", "light → lightly", "deep → deeply"]` produces
   **0 items** today — its `word_chain` branch only knows
   `_parse_chain_steps` (single-letter substitution; length-changing pairs
   yield nothing). The suffix-aware branch exists only in
   `adapt/engine.py:1061-1068`.
5. **Chain-shape detection is clean.** Lesson 100's corpus chains are all
   3-word (`slow → slower → slowest`); lesson 101's are all 2-word pairs.
   Shape is derivable at ledger-build time from the chain source items alone.
6. **Failure mechanics.** A criterion "fails" the run iff the judge votes
   `severe_defects` on the cell and recommends reject (`transform.py:849-866`);
   quality score alone doesn't abort (lesson 100's 0.46 shipped). The fix
   target is precisely: no severe-defect votes on the owner-approved form.

## Design

### WS1 — D48: route word_chain through the deterministic verifier

1. Add `"word_chain"` to `_MECHANICAL_FORMATS` in `adapt/llm_adapt.py` — same
   contract as `match`/`sound_box`: the model supplies inputs
   (`activity.words` as arrow strings), the deterministic parser verifies and
   stamps. Preserves the anti-gaming guarantee (LLM-claimed chains stay
   unverifiable by construction) while making LLM-planned chains able to count.
2. Extend `_build_items_from_activity`'s `word_chain` branch with the same
   `is_suffix_skill()` / `_parse_suffix_chain_steps()` branch
   `adapt/engine.py:1061-1068` already has (D1 parity — `engine.py:44-47`'s
   comment already documents the two call sites as symmetric; they are not).
   Verified load-bearing: without it, suffix-pair words parse to 0 items and
   the activity silently vanishes.
3. Planner prompt (`adapt/llm_planner.py`): extend rule 5 ("for match and
   sound_box, list the words in `words` and leave `items` empty") to include
   `word_chain`, and update the build/change-chain example to show the
   words-format for BOTH lesson types: suffix pairs
   (`"words": ["quick → quickly", "light → lightly"]`) and letter chains
   (`"words": ["cry → try → dry"]`). Without this, the model keeps authoring
   `items` that the fixed path discards; the salvage fallback
   (`llm_adapt.py:388-392` — words rebuilt from item *contents*) cannot
   recover arrow pairs from prose items, so the activity would vanish.
4. Coverage-retry feedback (`_coverage_feedback_block`): when
   `missing_required_forms` includes `word_chain`, the feedback line names the
   required format explicitly ("provide the chain in the activity's `words`
   as arrow strings, e.g. 'quick → quickly'"). Today's feedback states the
   miss but not the format, so a retry can repeat the same structural mistake.

### WS2 — D49: shape-aware manipulation facts for the judge (no evaluator change)

5. `adapt/objective_ledger.py::_make_manipulation_cell`: derive the lesson's
   chain shape at ledger-build time from the chain source items — all parse to
   single hops (2-word sequences) → single-hop; any 3+-word chain → multi-hop.
   Author the `sufficiency_rule` text per shape:
   - multi-hop (unchanged): `"≥1 coherent build/change chain (count steps,
     not words)"` — lesson 100 keeps byte-identical facts (regression bar).
   - single-hop (new): e.g. `"≥2 add-the-ending transformations
     (base + suffix → new word); this suffix forms no multi-step chain, so
     independent pairs ARE this lesson's manipulation form"`.
   The rule text is descriptive only — verified that
   `_evaluate_manipulation_cell` never parses it — so this cannot move the
   deterministic gate. Derive shape from the corpus data, not the skill name,
   so any future single suffix (`-ed`, `-es`) works without a per-suffix case.
6. Judge rubric guard (`adapt/llm_judge.py`): one line in the severe-defect
   guidance scoping `wrong_cognitive_task`: do not vote it when the package
   exercises the cell's stated `sufficiency_rule` form. The handed-facts
   channel already pipes the cell text through (`_render_objectives`) — no
   structural prompt change, just the corrected fact plus the guard.
7. **Explicitly rejected:** relaxing `_evaluate_manipulation_cell` (v1's
   WS2.5) — the evaluator already passes single-hop packages; synthesizing an
   artificial second hop — invents word relationships not in the UFLI source,
   violating skill preservation.

### Residual risk (named, not hidden)

The D49 fix is prompt-layer: the judge is a single-sample LLM with known score
noise (0.52-0.68 observed on identical content, session 61). Corrected handed
facts directly undercut both defect rationales, but approval is probabilistic.
If the live re-run still votes manipulation defects, the fallbacks are Q5's
2-of-3 sampling (already an open question queued with the passage-split work)
or owner adjudication of the criterion — a decision point, not silent retry.

## Exit criteria (goal contract)

1. **Per-defect red/green traceability** (same discipline as
   `.superpowers/sdd/uat-fix-traceability.md`). Deterministic tests assert the
   controllable layer; the judge's live behavior is criterion 3's job (same
   scope split as the lesson-100 spec's render-defect note).
   - D48 RED: an LLM-plan `word_chain` activity (items populated, words empty)
     produces zero stamped, evidence-eligible chain items after translation —
     asserted for BOTH a suffix skill and a letter-chain skill. GREEN: the
     same activities with arrow-format `words` produce stamped items that
     `evaluate_objective_coverage` accepts (suffix case additionally proves
     the WS1.2 parser branch: suffix pairs no longer yield 0 items).
   - D49 RED: lesson-101-shaped fixture's manipulation cell carries the
     multi-hop `sufficiency_rule` text (and the judge prompt therefore renders
     a rule the package cannot satisfy). GREEN: single-hop fixture gets the
     shape-aware rule text rendered into the judge prompt via
     `_render_objectives`; lesson-100-shaped fixture keeps the multi-hop text
     byte-identical.
2. `make test`, `make lint`, `make typecheck` green (mypy under CI's 3.11
   semantics, per G17).
3. Live acceptance re-run of lesson 101 (no override): ships judge-approved,
   OR fails pre-render with `obj_manipulation` NOT among the failing criteria
   (the known `obj_connected_text` blocker may still fail; that's
   task_202def01's scope). If manipulation still draws severe-defect votes,
   stop and surface — the residual-risk fallbacks above are an owner decision.
4. Live acceptance re-run of lessons 74 and 100 (no override): zero
   regression — same pass/fail criteria as the session-61 baselines, modulo
   judge score noise. Lesson 100's manipulation facts must be byte-identical
   (multi-hop path untouched); its planner path must not lose chain coverage
   it has today.
5. Photo path untouched and regression-free.

## Out of scope

The `obj_connected_text` / `overwhelming_or_adhd_unsafe` passage blocker
(`task_202def01`, queued); 2-of-3 judge sampling and broader judge visibility
(Q5 — the residual-risk fallback, decided separately); `--record-results`
ingestion; suffixes beyond `MORPHOLOGY_SUFFIXES`; robust salvage of
prose-authored chain items into arrow pairs (WS1.3's prompt fix makes the
model supply the right format; deterministic reconstruction from
`answer`-stripping is unsound for spelling-change suffixes like
`happy → happily` and is deliberately not attempted); gpt-5.4 →
gpt-5.6-terra swap (paused).
