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
Luna batches eight mandatory checks; each must reach a **provisional** 0.95
threshold, with valid local geometry. This is not calibrated accuracy. Missing or
uncertain results fail closed; no old-model escalation. Evaluate human-labelled
accepted **and rejected** scenes before relying on this policy for promotion.

### First: fix the delivered layout without another paid call

Archive private evidence read-only; fetch the latest test branch into the clean
detached worktree and run offline checks. Recompose Muse's genuine hash-bound
frozen package using the successful three-worksheet replay's saved `render_1`,
`render_2`, `render_3` directories. The source below is that **replay root**, not
the full transform's differently named renderer directories. Use fresh output.

For legacy v2 receipts, temporarily restore the exact original image and scene
vision model chains from the saved run configuration solely to verify their old
cache keys. Unset the API key for this recomposition; **there are no inference
calls**, even if a key is present. Do not hand-edit a receipt or approval. This
preserves old gate provenance; it does not retroactively claim Luna approval.

```bash
python -m experiments.live_replay \
  --manifest /private/live-lesson-100/artifacts/frozen_render_package.json \
  --reuse-scenes /private/successful-three-worksheet-replay \
  --output /private/recomposed-layout
```

Inspect every page and `layout_report.json`: WS1 must show the five-word reading
score separately from other tasks; WS2 must visibly number its five writing
items 1–5, while original item IDs remain unchanged; WS3 passage feedback must
have no blank denominator. Verify the same content/package/image hashes, one
art placement per worksheet at its declared section, no repetition on continuation
pages, no clipped text or orphan logs, and report the new physical page count.
If a reported error is embedded in approved practice text, preserve that JSON
and return the actual evidence rather than silently rewriting approved content.
Codex has not received the private live PDF/JSON and cannot certify their layout.

### Then: bounded model and artwork trials

Restore the new model configuration below; the legacy cache-verification settings
must not leak into live runs. Shadow-probe Luna on existing human-labelled scenes
first (no new artwork needed), including rejected candidates and deliberately
wrong task/identity/text examples. Record per-check probabilities, latency and
false accepts/rejects against humans, not agreement with one old judge. Keep
probes within the **$3.85 reported remainder** and count all HTTP retries.

Next use `--worksheet 1 --live` on the real frozen package in a fresh directory
for a small task-specific artwork + Luna gate trial. The new scene prompt/cache
version means fresh live trials cannot reuse old approval. Inspect procedure
relevance before spending on all three worksheets. A full lesson-100 rerun uses
Sol 6.1 medium for planning/judging; keep the 180-second deadline unless Howard
authorizes a different limit. A timeout is not end-to-end acceptance. Never
relax gates, enlarge the session budget or merge on a replay alone.

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
and `WORKSHEET_RUN_DEADLINE_S` to a diagnostic limit. These reset per process,
not across the session. Start full diagnostic runs with a 180-second deadline;
that is a safety limit, not an accepted product latency target. A smaller deadline
can be tested on frozen render-only trials after actual timings are known.

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

## Minimal compatibility probes before another full image pipeline

Use current public model/endpoint metadata to verify availability, image input,
reference-image support and structured output before paid calls. Model-level
capabilities can be a union across providers; check the routed endpoint too.
Verify Sol 6.1 medium chat/structured-output support and Luna image Decisions
support on the routed endpoints. These defaults are owner-requested test-branch
changes; live quality and speed remain to be measured.

1. If an unchanged approved frozen package from this branch is available, dry-run the replay command
   below, then use `--worksheet 1 --live` in a fresh directory for one artwork
   and gate trial. Do not disable checks or count a synthetic approval as real.
   Older artifacts must pass the revised deterministic rubric; if they do not,
   run lesson 100 once to create an approved frozen package instead. Never
   hand-author an affirmative verdict or synthetic approval for a live replay.
2. Optionally shadow-probe Jev with one clear synthetic instruction. Create
   private `state.txt` and `questions.json` (for example
   `{"clear":"Is the instruction a clear action for a seven-year-old?"}`).
   The CLI is dry-run by default and requires explicit `--live` plus limits:

```bash
python -m experiments.live_decisions --state /private/state.txt \
  --questions /private/questions.json --model typesafe/jev-1.13 \
  --output /private/jev-probe
# Add --live only after checking the key, ceilings, remaining budget and limits.
```

For Luna, use `--model openai/gpt-6-luna-decisions` and repeated `--image` arguments
(canonical reference first, candidate scene last). State the exact action and
costume from `learning_scene.json` in the private state file; batch identity,
action, outfit, text/answer absence and safety questions. The documented wire
format was checked on 2026-10-08: plain strings and image_url parts directly in
the state array. Live endpoint behavior is still unverified. Save human labels
for accepted **and rejected** candidates. The CLI probes remain shadow-only. The test branch separately uses all eight
mandatory probabilities plus geometry for scene approval; content approval
still belongs to Sol and the exact package hash. Label threshold failures honestly.

## First live run: lesson 100 regression

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
export WORKSHEET_RUN_DEADLINE_S=180
# Set the per-process USD/call limits and verified model ceilings as described above.
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
Luna is wired into the composed scene gate on this test branch with a provisional
threshold, requiring human calibration before promotion.

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
just "a character is present." Confirm layout report fonts: child-facing goal,
name, instructions and practice meet K>=16pt, grade 1>=14pt, grades 2–3>=12pt.
Caregiver logs/footer can be smaller. Record physical page count and pacing;
the previous live lesson-100 replay needed 10 pages, so low page count is
not yet demonstrated. Record effective artwork PPI at its printed size; vector
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
