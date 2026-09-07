# Refound branch exit review — merge criteria

Branch: `refound/skill-contracts-composed-render`, merged tip `7043db2ef87c8fd762a892c7edbb3abce936b882`.
Reviewer: Fable 5 exit review (plan Task 11), 2026-07-18. All evidence below was
re-verified independently on the merged tip, not copied from task reports.

Branch history (top to base):

```
7043db2 feat: A/B report — hybrid_shell candidate vs image_gen baseline
d3ddff4 feat: fail-closed compose-time checks (decoration budget, asset integrity)
7863653 feat: hybrid_shell is a real composed renderer — curated slots, zero render-time AI
2234209 feat: curated theme asset manifest with slot resolution (roblox_obby)
e2e9611 refactor: route objective-ledger manipulation fallback through contract constants
06e176d feat: suffix families -less/-ful and -ness as contract data only (H1a proof)
377f409 refactor: goal text and judge manipulation wording read from skill contracts
a83492c refactor: derive MORPHOLOGY_SUFFIXES from the skill contract registry
8bad239 feat: skill contract registry with current suffix families (no wiring)
c1a94f5 feat: baseline metrics extractor + captured pre-refound baseline
```

## H1 — Skill contracts

- [x] H1b byte-identity: full suite green at every migration commit (Tasks 3-4); exact-string
      tests pin goal text + judge wording; corpus sweep delta == {102, 124}.
  - `make test` on merged tip 7043db2: **904 passed, 0 failed** (re-run by this review).
  - Exact-string sentinels pass: `test_er_est_contract_carries_the_bespoke_goal_text`,
    `test_ly_contract_matches_current_generic_goal_text`,
    `test_all_contracts_carry_current_manipulation_wording` (`tests/test_skill_contract.py`,
    17/17 pass).
  - Corpus sweep RAN (not skipped — `data/ufli/normalized.jsonl` present locally):
    `test_corpus_classification_delta_is_exactly_lessons_102_and_124` PASSED, asserting
    reclassified == `{"102": "suffix_less_ful", "124": "suffix_ness"}` and nothing else (E17).
  - Task 4 Step 6 greps re-run by this review: `"I can add -er and -est"`,
    `"add-the-ending transformations"`, `"coherent build/change chain"` each hit
    **only `skill/contract.py`** across `adapt/ skill/ render/ validate/` (non-test).
- [x] H1a data-only extension: Task 5 commit diff touches only skill/contract.py + tests.
  - `git show --stat 06e176d`: `skill/contract.py | 4 +`,
    `tests/test_skill_contract.py | 174 ++...` — 2 files, no pipeline module.
  - Both downstream paths smoke-tested offline: `test_lesson_102_adapts_end_to_end_offline`
    (deterministic engine) and `test_planner_path_translates_a_less_ful_word_chain`
    (planner `_translate_plan`), both PASSED (E3).
- [ ] H1c (if Task 6 ran): lesson-100 confirm run, obj_manipulation zero severe defects,
      quality ≥ 0.42 baseline. If reverted, record the negative result honestly.
  - **NOT RUN.** Task 6 is entirely [LIVE — owner-gated] and was skipped per the
    no-live-API rule. The er/est multi-hop wording fix (chip `task_15a12b24`) has not shipped.
- [ ] Lesson-102 smoke (if run): classifies suffix_less_ful, correct goal banner,
      manipulation clean.
  - **NOT RUN.** Task 5 Step 8 is [LIVE — owner-gated]. Offline classification and
    both-path adaptation tests pass (above), but no live transform of lesson 102 exists.

## H2 — Composed renderer

- [x] Zero render-stage AI calls (test-enforced + composed_manifest).
  - Test: `tests/test_composed_render.py::test_hybrid_shell_makes_no_network_calls` —
    verified NON-vacuous by this review: it patches `GeminiImageProvider.generate`,
    `OpenAIImageProvider.generate`, and `resolve_provider_chain` in both defining and
    importing namespaces, *proves each patch bites* (direct calls raise), then renders
    successfully under the patches.
  - Runtime: all 3 offline candidate logs (`output/lesson{74,100,101}_hybrid.log`)
    contain **0 `HTTP Request` lines** and end with
    "Render mode hybrid_shell complete (3 worksheets)" — no silent pdf_classic
    degradation (E12). All **9** `composed_manifest_{1,2,3}.json` files carry
    `"render_api_calls": 0` and `"renderer": "hybrid_shell"` (re-counted: 9/9).
- [x] Decoration budget ≤ 15% fail-closed (test-enforced).
  - `validate/composed_checks.py` `DECORATION_BUDGET_CAP = 0.15`, raises on excess;
    `tests/test_composed_checks.py::test_budget_over_cap_fails` and
    `tests/test_composed_render.py::test_decoration_budget_within_cap` pass (12/12 in
    the two composed test files). Observed candidate budget sum: 0.06 (mascot only).
- [x] A/B report generated; hybrid attempts == pages, baseline attempts ≥ pages.
  - `docs/superpowers/baselines/2026-07-17-refound-ab-report.md` committed at 7043db2;
    baseline JSON `2026-07-17-refound-baseline.json` committed at c1a94f5.
  - Hybrid attempts == pages **by construction** (no retry loop; hybrid writes no
    `page_attempt_*.png` artifacts, so the report column reads 0 — see caveat below).
  - Baseline attempts ≥ pages holds where measurable: lesson101_uat_confirm shows
    3 attempts / 3 pages; baselines 74/100 predate the attempt-PNG artifact and read
    0/0 (vacuously ≥, not affirmative evidence).
  - **Caveat (honest scope):** candidate runs were offline (no planner, no judge), so
    candidate `overall_score` is None and `severe_defects` 0 means "no judge ran".
    The report itself states this; it verifies H2 render metrics only, NOT content parity.
- [ ] Owner visual review of the three hybrid PDFs vs image_gen pages: verdict + notes here.
  - **PENDING OWNER.** Offline hybrid PDFs exist under `output/lesson{74,100,101}_hybrid/`,
    but full-parity PDFs (Task 10 Step 6, [LIVE]) have not been generated. See the
    mascot-asset flag in the traceability audit — the owner should specifically
    re-examine the shipped `theme/themes/roblox_obby/curated/mascot.png`.

## Explicitly OUT of this branch

- Flipping the default renderer (D29 stands until the owner decides otherwise).
- The connected-text passage split (chip task_202def01).
- Contract-izing engine chain templates / evidence regexes (contract v2, future).

## Verdict

- [ ] MERGE / [ ] HOLD — reasons:
  - **Decision reserved for the owner.** All offline-verifiable H1/H2 evidence holds
    (H1a, H1b, H2a, H2b, A/B report). H1c and both live-verification lines are
    unchecked because their [LIVE] steps were owner-gated and not run.

### Pending [LIVE] owner-gated steps (must run or be waived before merge)

1. **Task 5 Step 8 — lesson-102 smoke run.**
   `.venv/bin/python transform.py --lesson 102 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson102_contract_smoke/`
   Expected: log `Skill: suffix_less_ful`, goal banner "I can add -less and -ful to words",
   `obj_manipulation` zero severe defects.
2. **Task 6 entirely — er/est multi-hop wording as contract data + lesson-100 confirm run**
   (chip `task_15a12b24`). One-line contract-data edit plus one live confirm run;
   zero `obj_manipulation` severe defects, quality ≥ 0.42; max 2 runs, owner adjudicates
   borderline (E14), revert path pre-written in the plan.
3. **Task 10 Step 6 — full-parity visual PDFs.** Re-run lessons 74/100/101 with real keys
   and `--render-mode hybrid_shell` (add `WORKSHEET_SHIP_UNAPPROVED=1` only where the sole
   judge blocker is the known connected-text veto); collect the 3 hybrid PDFs plus baseline
   image_gen pages for the owner visual review above.

## Traceability audit

Deviations from the plan, findings, and honesty notes — collected from track reports
and independently spot-checked where cited.

**Plan-vs-reality deviations (all resolved within the plan's own escape hatches):**

- **Task 4 / Step 6 conflict (material, resolved in e2e9611).** The plan's own Step 4
  code left the two default manipulation-rule strings inline in
  `adapt/objective_ledger.py`, contradicting Step 6's "literals in exactly one place"
  bar. Resolved by taking Step 6's explicit "route it through the contract too" option:
  contract constants `DEFAULT_SINGLE_HOP_RULE` / `DEFAULT_MULTI_HOP_RULE` promoted to
  public and imported by the ledger fallback. Behavior byte-identical (same strings).
  Kept as a separate refactor commit so the H1a data-only commit (06e176d) stayed pure —
  re-verified by this review via `git show --stat`.
- **Task 7 / E9 mascot substitution (FLAG for owner visual review).** Neither cached
  avatar met the plan's own bars: `avatar_68204d7dc854.png` (64x64, plan's literal `cp`
  source) fails identity fidelity and the ~400px floor; `avatar_e7d64ba9db8a.png`
  (150x150) is the right identity but fails the floor. Shipped substitute:
  `assets/characters/rainbow_roblox.png` — re-verified by this review as **1408x768 RGB**
  (not RGBA). Correct character, but standing pose (not pointing), no backpack overlay,
  flat near-white background rather than a transparent cutout. **No asset in the repo is
  simultaneously correct-identity, ≥400px, backpack, pointing pose, and alpha-transparent.**
  A proper cutout needs fresh curation/production.
- **Task 7 / header_banner slot omitted** per the plan's explicit contingency — no
  banner-shaped asset exists for roblox_obby (`assets/themes/roblox_obby/` does not
  exist). Manifest carries only the mascot slot. Sourcing theme art is future owner work.
- **Task 1 baseline data.** The plan's illustrative prose said 2 severe defects on
  lesson101 `obj_connected_text`; the on-disk `judge_verdict.json` has 1. The extractor's
  faithful read of the real artifact was kept per the plan's own "nulls are honest data"
  rule. Minor lint fixes to the plan's verbatim test snippet (unused import, line length);
  no assertion changes.
- **Task 2 count typo.** Plan text says "Expected: 6 PASS" for a code block containing
  7 tests; 7 passed. Stale count in plan prose, not a code defect.
- **Task 8 test replacements (strengthening, not weakening).** The plan's sketched
  network test (a `dir()` loop) was vacuous; the shipped test patches the real call
  surfaces in both namespaces and proves the patches bite before rendering — verified
  non-vacuous by this review.
  `test_hybrid_shell_strategy_is_experimental_pdf_renderer` was rewritten (not deleted)
  to assert composed behavior. `ThemeConfig.theme_id` and `tests/test_render_strategies.py`
  additions were pre-authorized scope extensions recorded in the Task 8 report.
- **Tasks 8/9/7 mypy-strict accommodations.** `# type: ignore[list-item]` on
  deliberately dict-literal Pydantic test inputs (matches existing repo idiom in
  `tests/test_llm_judge.py`), a top-level `pathlib.Path` import, and one removed
  unused-ignore. No runtime behavior changes.
- **Task 10 / E1 spend gate held.** `load_dotenv()` override=False + empty-string keys
  + no `.env` file; offline proof is the 0-`HTTP Request` logs re-verified above.

**E4-class findings (Track A):** none. `_parse_suffix_chain_steps` handled lesson-102
real corpus content without a parser fix; no red engine test was needed, so the H1a
commit required no pipeline changes — consistent with the clean `git show --stat`.

**Weakened or vacuous tests:** none found. The one place the plan's sketch was vacuous
(Task 8 network test) shipped stronger than specified.

**Scope creep:** none beyond the pre-authorized Task 8 items above. e2e9611 is within
Task 4 Step 6's explicit option. No new dependencies (E19 held).

**Known open flags for the owner:**

1. Mascot asset (above) — re-examine at visual review; likely needs fresh art.
2. header_banner slot empty for roblox_obby.
3. A/B baseline rows for lessons 74/100 have no attempt artifacts (0/0) — the
   "baseline attempts ≥ pages" clause rests on lesson101 alone.
4. Candidate A/B rows carry no judge data (offline) — content parity is unproven until
   Task 10 Step 6 runs.
5. Branch refs `refound/track-a` / `refound/track-b` still exist (worktrees removed);
   delete at owner's discretion.
6. The plan file `docs/superpowers/plans/2026-07-17-skill-contracts-composed-render.md`
   is untracked in the repo (present on disk only).
