# Muse / Grok: live validation handoff

Implementing branch: `codex/on-demand-composed-worksheets` in
`howardjong/worksheet-builder`; base `main` at `78b00d5`.
Fetch the branch, pin and report its exact SHA before testing. Read AGENTS.md,
`.claude/worksheet-project-context.md` and `docs/on-demand-rendering.md`. Do not
merge or change the production default based only on offline checks.

The owner authorized publication; the branch is now remote. Use its latest head,
not the earlier patch or main. Keep all changes off main until acceptance.

## Latest evidence and next trial

Muse tested `2cc5e9a` / tree `8222147`: 1,140 offline tests passed, approval
handshake worked, and the full lesson-100 run approved content at 0.89 but hit
the unchanged 180-second deadline during artwork (13 calls, $0.58). A single
worksheet replay completed in 54 seconds, then all three in 76 seconds. The
10-page package (4+4+2) had three live scenes passing the old vision gates;
artwork was 277ppi. This is successful render-only evidence, **not a completed
end-to-end run or a controlled serial/parallel comparison**. Session spend was
$1.15 reconciled; Muse reported **$3.85 remaining**. Reconcile before new calls.

Owner found repetitive, weakly instructional artwork. This was renderer behavior,
not fallback: the same scene was stamped on continuation pages and the action
selector applied the same comparison pose across worksheets. The new renderer
places a scene once, beside the declared section, and new prompts model that
section's reading, building, choosing or writing procedure. These are supplemental
procedure illustrations, not verified picture-matching assets. Human review of
actual educational usefulness remains a merge blocker.

New model defaults: `openai/gpt-6.1-sol`, `reasoning.effort=medium`, for text/vision
and `openai/gpt-6-luna-decisions` for composed artwork gates. No automatic
GPT-5.5 / Gemini 3.1 Pro / Sonnet 4.6 review fallback. Image generation chains
are separate and unchanged. Clear inherited stage overrides before paid trials.
Muse's shadow report found the old uniform 0.95 threshold rejected three earlier
accepted scenes. The text-free art's `no_answers` check was a confusing negative
question Luna scored near zero across all three. The new v4 question clearly asks
whether any completed answer is absent, defines blank materials as answer-free,
and treats uncertainty as failure. Answer-free must reach .95. Other provisional
cutoffs: identity .85, task relevance .35, action .35, outfit .85, child safety
.95, no text .95 and meaningful area .95. These let the
owner-approved new scene's rounded .90/.40/.42 values through while the tested
wrong-action/outfit controls at 0 remain rejected. This is a **tiny owner-labelled
pilot policy, not calibrated accuracy**. Repeat exact saved candidates to measure
score wobble; label every scene with the owner before drawing an accuracy claim.
No result bypasses missing/invalid checks or local geometry.

### Layout verification is done; begin calibration

Muse has already recomposed the genuine approved lesson-100 package without API
calls: the PDF is 8 pages (down from 10), the score/log defects are fixed, artwork
is not repeated, and saved PNGs are byte-identical. Muse reports no clipping or
caregiver-only pages. This is Muse's evidence, not independently reviewed here;
keep its private PDF and per-page previews. No need to repeat this paid or offline
layout pass if these artifacts still match the approved package and test branch.
The new code changes in this handoff concern gate calibration, not PDF layout.

### Then: bounded calibration and full end-to-end run

Restore the new model configuration below; legacy cache-verification settings must
not leak into live runs. Use the preserved images for one Luna v4 shadow batch:
three previously accepted scenes, the owner-approved new word-tile scene, and the
wrong-action and wrong-outfit controls. Include clear text/answer negative examples
if present. Ask the exact v4 `answer_free` question and the other checks. Repeat
once on the same images to measure wobble if the current account price and ceiling
allow it (Muse's earlier five probes cost about $0.002 total). Save raw scores and
human labels. Generate no artwork for this probe.

Then prioritize the full **lesson-100 end-to-end run** in a fresh output directory:
planner, Sol 6.1 medium judge, fresh generated scenes, Luna gates, PDF and validators.
Use the lesson fixture because no authorized phone photo is available. The owner
has asked to see actual wall time. Use the **300-second** diagnostic deadline
below, keeping the hard cumulative $5 session cap and spending at most **$3.80 of
the reported $3.83 remainder** across probes and the run. Reconcile spending and
verified model ceilings first; if they do not fit, stop before paid calls. Do not
set a per-process budget larger than the cumulative remainder. Record wall time from pipeline start
to merged validated PDF, each critical-path stage, all retries/fallbacks, first
attempt accept/reject and reconciled cost. A 300-second safety window is a test
limit, not the product target. Do not make optional serial/parallel trials if they
threaten the budget. A replay is not end-to-end evidence. Keep image/content gates;
report failure if any stage blocks. Full run is the best next evidence for both
first-pass quality and actual end-to-end latency.

Novel phone-photo acceptance and actual AirPrint remain pending; no authorized
new phone photo was supplied. The old approval handshake fix remains covered:
objective verdicts serialize derived `approval_decision`/`approved`, bound to the
exact finalized package. Never synthesize approval from a numeric score.

## Key and preflight

Use the existing OpenRouter key through your vault's opaque runtime surrogate as
`OPENROUTER_API_KEY`. Do not ask Howard to paste a key into chat. Never write the
key to an env file, command argument, artifact, commit, stdout or logs. Disable
shell tracing. If the vault key is unavailable, stop with a concise blocker.

Use an isolated worktree and a temporary non-sensitive learner profile. Install
requirements and run the offline suite first. Preserve all private run artifacts
before removing the worktree. Keep photos, names, profile and generated PDFs/art
out of git and public PR comments.

Budget: retain the previously authorized **$5 total across this testing session**,
including probes, failed runs, replays and retries. Check remaining credit and
establish an account/key cap before starting. The application now reserves each
HTTP attempt's declared maximum cost atomically across parallel workers; missing
cost reports retain their reservation. This is **not a provider billing guarantee**.
Running/timed-out requests can still be billed; keep the external cap.

Before each process, set `WORKSHEET_RUN_MAX_USD` to its allocation within the
**remaining** session budget, `WORKSHEET_RUN_MAX_CALLS` to a bounded attempt count,
and `WORKSHEET_RUN_DEADLINE_S=300` for the requested end-to-end measurement.
Limits reset per process, not across the session. The 300-second window is a safety bound for measuring actual wall time, not the
product target. Test smaller bounds after one
complete run.

Set `WORKSHEET_CALL_CEILINGS_JSON` to a JSON object mapping **every configured
model ID** to a verified conservative USD ceiling per HTTP attempt. Compute
ceilings from current endpoint pricing, input/reference tokens or pixels and
maximum output/reasoning tokens. There is no invented default price. Narrow
model chains to priced candidates. Do not understate ceilings to squeeze calls
under the cap. Excess cost blocks the run; reconcile `run_limits.json` with the
OpenRouter account before spending again. Unknown cost means unknown, not zero.
Do not launch additional runs if remaining budget cannot cover them; report
partial evidence instead. No new work starts after the deadline or cap, but
running HTTP/PDF work can finish later; this is not a hard 35-second guarantee.
No automatic whole-run retry after rejection and no `WORKSHEET_SHIP_UNAPPROVED`.

For real child material, crop out names/identifiers and use an anonymous trial
profile. Names are added locally to the composed PDF, not planner prompts.
Set `WORKSHEET_OPENROUTER_REQUIRE_ZDR=1` and verify account logging/privacy controls
and eligible endpoints. This sends both `provider.zdr=true` and
`provider.data_collection="deny"` for chat, images and Decisions. If unsupported
or no eligible endpoint exists, stop; never retry with weaker privacy routing.
Custom character descriptions and photographed text can still contain personal
information, so inspect those inputs too. Keep every private artifact out of git.

## Model routing preflight

Before any paid call, verify Sol 6.1 medium supports the routed chat/structured
output endpoint and Luna Decisions supports image inputs on the selected route.
Use the batch format documented for the Decisions API and retain model IDs as
actually served. The small shadow batch in the section above uses saved candidate
images; it replaces the old separate one-image trial. Jev probing is optional and
should not displace the full run or consume funds needed for it.

## Full lesson-100 pipeline and latency run

Use lesson 100 because it is the committed fixture Howard approved. Do not claim
to have tested 106 unless the actual source exists. Use Sol 6.1 medium for planner/judge and Luna Decisions for scene checks;
retain every attempted and served model name.

```bash
export WORKSHEET_OPENROUTER_TEXT_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_VISION_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_PLANNER_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_JUDGE_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_REVIEW_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_EXTRACTION_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_REASONING_EFFORT=medium
export WORKSHEET_SCENE_GATE_BACKEND=decisions
export WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL=openai/gpt-6-luna-decisions
export WORKSHEET_IMAGE_CONCURRENCY=3
export WORKSHEET_SCENE_MAX_CANDIDATES=2
export WORKSHEET_ALLOW_PDF_FALLBACK=0
export WORKSHEET_RUN_DEADLINE_S=300
# Set the per-process USD/call limits and verified model ceilings as described above.
export WORKSHEET_OPENROUTER_SCENE_TIMEOUT=90
export WORKSHEET_OPENROUTER_PLANNER_TIMEOUT=90
export WORKSHEET_OPENROUTER_JUDGE_TIMEOUT=60
export WORKSHEET_OPENROUTER_REVIEW_TIMEOUT=45
python transform.py --lesson 100 --profile /private/test-learner.yaml --theme space \
  --render-mode hybrid_shell --output /private/live-lesson-100
```

Inspect the PDF and actual gates even if the CLI returns successfully. A failed
scene must be reported as failure; no plain fallback counts as first-pass success.
Compare the package with Muse's prior lesson-100 package, especially -er/-est
practice, connected text, examples and duplicated copying. Record time from the
first transform call to the final merged, validated PDF, as well as stage spans.
Mark content/art first-pass pass only if no planner retry, gate rejection, provider
fallback or renderer degradation occurred; do not infer it from final PDF alone.

## Mandatory product test: a new phone photo

The product is photo-driven. A fixture-only test is insufficient. Use a newly
provided, authorized photo of real lesson content that is not a cached committed
fixture. If no photo is available, finish lesson 100 and report this test pending;
do not substitute synthetic input and call it live product acceptance.

Pause for source review **before** the full run. With the same extraction model
chain, private cache and verified limits, run the extraction-only command:

```bash
export WORKSHEET_EXTRACTION_CACHE=/private/photo-extraction-cache
python -m experiments.photo_intake --input /private/new-phone-photo.jpg \
  --output /private/photo-intake --live
```

Without `--live` this command only checks the input and emits a dry-run summary.
The live command does capture/transcription/skill mapping only: no planner, judge
or artwork. Its costs count toward $5. Compare every region, word, sentence,
passage and inferred skill to the actual photo; retain human review notes. Keep
the cache and extraction model list unchanged so the full run reuses this exact
transcription without another extraction call. Changing photo bytes or extraction
models intentionally invalidates that cache. Mixed visible story/word-work pages
use semantic mapping; any dropped practice region blocks the composed intake.

Verify the extracted source against the photo first. Preserve source/skill JSON
and the original image privately. Do not enable objective-sampling or a package
cap by accident on the strict photo path. Enable planner v2 explicitly for this
trial; retain full photographed-content coverage.

Inspect `validation_photo_intake.json` and `photo_coverage_ledger.json`: unknown
layouts are allowed, unknown skills/uncertain transcription are not. Every source
target, list/chain word, student sentence and full passage needs actual practice
evidence. Headings, worked examples and distractors do not count. Valid chain
production or filled-sentence answers can count; check those answers against the
photo. Teacher scripts are excluded. The 80% legacy validator is not the composed
photo acceptance bar. Lesson mode deliberately retains objective sampling.
Do not suppress extraction uncertainty or change a skill to get past these gates;
correct the source privately after checking the photo and report the correction.

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

Use the provided executable replay tool with the private
`frozen_render_package.json` written before artwork. It verifies affirmative
hash-bound approval, reruns the revised deterministic checks, and preserves the
original photo-full versus lesson-objective coverage policy even if shell settings
differ. It refuses contaminated artwork directories and live runs without limits
and model ceilings. It does not re-extract, plan or judge content.

```bash
python -m experiments.live_replay \
  --manifest /private/live-lesson-100/artifacts/frozen_render_package.json \
  --output /private/replay-dry
# A one-worksheet compatibility trial: fresh output directory, --worksheet 1 --live.
# Full comparison: concurrency 1 vs 3, separate empty directories, --live on each.
```

For a separate faster-art experiment, try one verified endpoint at a time with
`WORKSHEET_SCENE_MAX_CANDIDATES=1` and an explicit image model. Grok's candidates
`black-forest-labs/flux.2-klein-4b` and `google/gemini-3.1-flash-lite-image` are
options to check in the live catalog, not measured winners. Keep the reference,
approved content and scene gate fixed. Record every rejection and cost. Do not
change production defaults or bypass the scene gate based on advertised speed.

Set `WORKSHEET_IMAGE_CONCURRENCY=1` vs `3`. Keep model lists, candidates and
timeouts identical. Allocate each replay from the remaining session budget;
never give each trial a fresh $5 allowance. This comparison measures **rendering
only**, not full photo latency. Every action/outfit/safety gate remains mandatory;
there is no approved near-miss fallback.
If it would exceed $5, use the offline overlap test and report the live A/B pending.

## Faster feedback experiment (optional, budget permitting)

Model routing is configurable per extraction/planner/judge/review/scene gate. Verify model
availability and structured-output/vision support before selecting one; compare
one stage at a time to the same frozen inputs and human labels. A lower cost
model is acceptable only if it preserves quality. Do not disable gates to meet
a latency number.

The `live_decisions` CLI wraps `decide_yes_no()` to shadow-test `typesafe/jev-1.13` on clear instructions and
`openai/gpt-6-luna-decisions` on text-free learning scenes. Confirm the current
Decisions image-state wire format with the official API first. Batch narrow
questions about the same input. Save timing, probabilities and human outcomes;
measure false accepts/rejects, not agreement with one stochastic judge. These
models do not generate worksheet content. CLI probes and Jev remain shadow-only;
Luna is wired into the composed scene gate on this test branch with v4 provisional,
per-criterion thresholds described above. Validate them against saved human labels
before promotion.

## Report and acceptance

Return exact SHA, CLI/env configuration (never key), source lesson/photo,
PDF/page count, per-stage wall times, all attempted calls/models, first-pass
results, retries/fallbacks and reconciled cost. Preserve:

- `source_model.json`, `skill_model.json`, `adapted_model_*.json`, planner attempts;
- `judge_verdict.json`, `approval_contract.json`, `run_summary.json`, all validation reports;
- `frozen_render_package.json`, `photo_coverage_ledger.json`, photo intake report;
- `render_*/learning_scene.json`, **all** `candidate_*.png`, `layout_report.json`;
- `inference_calls.jsonl`, `timing_summary.json`, `run_limits.json`, final PDF and page previews.

Review every printed page: exact spelling and source-skill preservation, correct
examples/distractors, no visible answers leaked into art, child can complete every
task without nonexistent pictures, identity stable across pages, theme costume
appropriate, substantial task-specific learning action, one illustration placed
beside its declared section instead of repeated headers, readable type, enough writing space,
no clipped text, no caregiver-only pages, accurate score denominators. Confirm
`approval_contract.matches=true`, affirmative content approval, all validators
pass, and no degraded-art fallback.

Use the saved `action_contract` to label exact action and outfit acceptance, not
just "a character is present." Confirm child-facing fonts meet K>=16pt, grade 1>=14pt,
grades 2–3>=12pt; caregiver logs/footer can be smaller. Muse's layout recomposition
already reports 8 pages instead of 10; confirm the full run's page count and pacing. Record effective artwork PPI at its printed size; vector
text is crisp independently of artwork. A ~1K scene at this slot is below 300ppi;
do not claim 300ppi or silently shrink it into a thumbnail. Human printed-art
acceptance is required rather than a blanket speculative resolution target.

After a rejected run, inspect saved candidates and gates before another paid
attempt. Return the failure even if a provider, deadline or limit prevented a
PDF; a fast failure is not worksheet success. Reserve known source words and
patterns: don't add spelling rules (for example doubling/y-to-i) solely to improve
a rubric score if they are outside the photographed lesson.

One successful live run demonstrates feasibility; it does not establish a p95
latency or a ≥95% first-pass rate. Report actual latency rather than promising
three seconds. Provide defects/artifacts for Codex to fix. Promote the renderer
and merge only after live and human visual acceptance are recorded.
