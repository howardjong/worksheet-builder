# Muse / Grok: live validation handoff

Implementing branch: `codex/on-demand-composed-worksheets` in
`howardjong/worksheet-builder`; base `main` at `78b00d5`.
Fetch the branch, pin and report its exact SHA before testing. Read AGENTS.md,
`.claude/worksheet-project-context.md` and `docs/on-demand-rendering.md`. Do not
merge or change the production default based only on offline checks.

## Key and preflight

Use the existing OpenRouter key through your vault's opaque runtime surrogate as
`OPENROUTER_API_KEY`. Do not ask Howard to paste a key into chat. Never write the
key to an env file, command argument, artifact, commit, stdout or logs. Disable
shell tracing. If the vault key is unavailable, stop with a concise blocker.

Use an isolated worktree and a temporary non-sensitive learner profile. Install
requirements and run the offline suite first. Preserve all private run artifacts
before removing the worktree. Keep photos, names, profile and generated PDFs/art
out of git and public PR comments.

Budget: retain the previously authorized **$5 total** ceiling. Check remaining
credit and establish an account/gateway cap plus reserve for up to three calls
already in flight before starting. This branch does not enforce a dollar cap.
Transport retries/fallbacks may consume budget. Do not launch additional full
runs if remaining budget cannot cover them; report partial evidence instead.
No automatic whole-run retry after rejection and no `WORKSHEET_SHIP_UNAPPROVED`.

## First live run: lesson 100 regression

Use lesson 100 because it is the committed fixture Howard approved. Do not claim
to have tested 106 unless the actual source exists. Keep planner/judge models at
existing defaults for this first comparison; retain every attempted model name.

```bash
export WORKSHEET_IMAGE_CONCURRENCY=3
export WORKSHEET_SCENE_MAX_CANDIDATES=2
export WORKSHEET_ALLOW_PDF_FALLBACK=0
export WORKSHEET_OPENROUTER_SCENE_TIMEOUT=90
export WORKSHEET_OPENROUTER_PLANNER_TIMEOUT=90
export WORKSHEET_OPENROUTER_JUDGE_TIMEOUT=60
export WORKSHEET_OPENROUTER_REVIEW_TIMEOUT=45
python transform.py --lesson 100 --profile /private/test-learner.yaml --theme space \
  --render-mode hybrid_shell --output /private/live-lesson-100
```

Inspect the PDF and actual gates even if the CLI returns successfully. A failed
scene must be reported as failure; do not silently count a plain fallback as
first-pass success. A content rejection should stop before paid artwork begins.
Compare content to Muse's prior lesson 100 package, especially -er/-est practice,
connected text, worked examples and duplicate copying sections.

## Mandatory product test: a new phone photo

The product is photo-driven. A fixture-only test is insufficient. Use a newly
provided, authorized photo of real lesson content that is not a cached committed
fixture. If no photo is available, finish lesson 100 and report this test pending;
do not substitute synthetic input and call it live product acceptance.

Verify the extracted source against the photo first. Preserve source/skill JSON
and the original image privately. Do not enable objective-sampling or a package
cap by accident on the strict photo path. Enable planner v2 explicitly for this
trial; retain full photographed-content coverage.

```bash
export WORKSHEET_PLANNER_V2=1
export WORKSHEET_LLM_ADAPT=1
unset WORKSHEET_OBJECTIVE_COVERAGE WORKSHEET_PLANNER_SLOT_CONTRACT WORKSHEET_MAX_WORKSHEETS
python transform.py --input /private/new-phone-photo.jpg --profile /private/test-learner.yaml \
  --theme space --render-mode hybrid_shell --output /private/live-photo
```

Record wall time from starting the transform to final merged PDF and separately
phone upload/download/print times when available. Native AirPrint needs manual
verification on the target phone/printer. Check size, margins and readability on
paper, not only in a PDF viewer.

## Controlled serial vs parallel comparison (only within remaining budget)

Reuse **the exact same approved adapted package**, theme and identity for both
render-only trials. Freeze extraction/content: do not run the planner twice and
attribute different outputs to concurrency. Copy `adapted_model_*.json`, profile,
identity and matching judge verdict privately. Verify `package_hash()` matches
the approved verdict before reusing it.

Use a small replay script that loads those activity JSONs, compiles each design
spec, creates separate `RenderContext`s, runs
`ordered_parallel_map(generate_scene, contexts)`, then renders the PDFs serially
with `extra_artifacts={"scene_prepared":"1","learning_scene":scene_path}` and
merges. Wrap the replay with `traced_pipeline` and an `artifacts_dir` parameter.
Set `WORKSHEET_IMAGE_CONCURRENCY=1` vs `3`. Use distinct empty artifact directories
so neither run is an artwork cache hit. Keep model lists, candidates and timeouts
identical. This comparison measures **rendering only**, not full photo latency.
If it would exceed $5, use the offline overlap test and report the live A/B pending.

## Faster feedback experiment (optional, budget permitting)

Model routing is configurable per planner/judge/review/scene gate. Verify model
availability and structured-output/vision support before selecting one; compare
one stage at a time to the same frozen inputs and human labels. A lower cost
model is acceptable only if it preserves quality. Do not disable gates to meet
a latency number.

`decide_yes_no()` can shadow-test `typesafe/jev-1.13` on clear instructions and
`openai/gpt-6-luna-decisions` on text-free learning scenes. Confirm the current
Decisions image-state wire format with the official API first. Batch narrow
questions about the same input. Save timing, probabilities and human outcomes;
measure false accepts/rejects, not agreement with one stochastic judge. These
models do not generate worksheet content and are not wired into approval.

## Report and acceptance

Return exact SHA, CLI/env configuration (never key), source lesson/photo,
PDF/page count, per-stage wall times, all attempted calls/models, first-pass
results, retries/fallbacks and reconciled cost. Preserve:

- `source_model.json`, `skill_model.json`, `adapted_model_*.json`, planner attempts;
- `judge_verdict.json`, `approval_contract.json`, `run_summary.json`, all validation reports;
- `render_*/learning_scene.json`, accepted/candidate art where available;
- `inference_calls.jsonl`, `timing_summary.json`, final PDF and page previews.

Review every printed page: exact spelling and source-skill preservation, correct
examples/distractors, no visible answers leaked into art, child can complete every
task without nonexistent pictures, identity stable across pages, theme costume
appropriate, substantial learning action, readable type, enough writing space,
no clipped text, no caregiver-only pages, accurate score denominators. Confirm
`approval_contract.matches=true`, affirmative content approval, all validators
pass, and no degraded-art fallback.

One successful live run demonstrates feasibility; it does not establish a p95
latency or a ≥95% first-pass rate. Report actual latency rather than promising
three seconds. Provide defects/artifacts for Codex to fix. Promote the renderer
and merge only after live and human visual acceptance are recorded.
