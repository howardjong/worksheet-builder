# Muse / Grok: live validation handoff

> Latest owner-authorized full run: [expressive-reference-end-to-end.md](expressive-reference-end-to-end.md).
> Its one-run ordering supersedes the screen-first sequence below.

Next live trial: [approved reference consistency screen](approved-reference-consistency.md).
This supersedes earlier experiment ordering and spend snapshots.

> **Current experiment handoff (2026-10-09):** Follow
> [character-consistency-experiments.md](character-consistency-experiments.md)
> for experiment order, factorial design and current evidence. The trial sequence
> and remaining-dollar snapshots below are historical and superseded. Reconcile
> the same cumulative $5 cap after all later ablations; do not use an old remainder.
> This document remains the reference for existing commands, privacy and limits.

Implementing branch: `codex/on-demand-composed-worksheets` in
`howardjong/worksheet-builder`; base `main` at `78b00d5`.
Fetch the branch, pin and report its exact SHA before testing. Read AGENTS.md,
`.claude/worksheet-project-context.md` and `docs/on-demand-rendering.md`. Do not
merge or change the production default based only on offline checks.

The owner authorized publication; the branch is now remote. Use its latest head,
not the earlier patch or main. Keep all changes off main until acceptance.

## Latest evidence and next trial

Muse tested `2663a2b` / tree `d81645f2`: 1,169 tests passed. The fresh full
lesson-100 run failed at artwork after **190 seconds, no PDF**. Sol planning
made two requests (58s + 52s); the content judge approved at .86 in 21s.
All four artwork candidates were rejected. This is failure latency, not completed
end-to-end latency or first-pass success. Muse reports ~$1.57 cumulative spend,
**~$3.43 remaining** of the same $5 session cap. Reconcile before any new calls;
allocate at most $3.40 across comparison and full run, never reset the session cap.

The fourth version of our application rubric was called "Luna v4" in reports.
That was not a model version. The requested model remains
`openai/gpt-6-luna-decisions`, served as
`openai/gpt-6-luna-decisions-20261006`. An exact saved-image repeat returned
identical scores. Different generated images had different scores; that alone
does not establish randomness on identical input.

The owner accepts relevant, nonrepetitive art without demanding perfection.
Worksheet gate **v5** implements that standard:

- Choosing illustration: pencil hovers above blank cards, without circling or
  marking an answer. Artist and gate use the same declared action.
- Seven semantic checks remain mandatory: identity, task relevance, recognizable
  procedure/props, appropriate outfit, child safety, no text, no specific answer.
  Luna trial cutoffs remain .85/.35/.35/.85/.95/.95/.95, respectively; these are
  provisional from a tiny labelled sample, not validated accuracy estimates.
- Luna's estimate of 55% painted semantic coverage is **advisory**. Its probability
  is confidence in that assertion, not measured area. It cannot block by itself.
  Resolution (800x450 minimum), foreground bounding extent (55% of image area)
  and printed extent (the design spec's minimum, currently 10% of page) still
  block tiny/blank art. White gaps inside the learning scene are allowed.
- Luna uses local nonwhite foreground bounds; Haiku can return semantic bounds.
  Local bounds can include coloured backgrounds or decorations. Inspect this
  limitation with tiny-subject/large-background controls; do not claim semantic
  coverage has been measured locally. Relevance/action and human review matter.
- Explicit vision gating supports `anthropic/claude-haiku-5.5`, one short structured
  reply with concrete blocking reasons, default **low** effort for that stage only.
  Sol planner/content judge remain medium. No automatic backend/model escalation.
  The trial default stays Luna until the saved-image comparison selects a model.
- Current prompt/policy/effort have a new cache key. Recomposition may verify
  genuine v2/v3/v4 receipts under their original contract, retaining provenance;
  those do not count as fresh v5 acceptance.
- CLI now rejects empty/missing PDF paths and failed validation with a nonzero
  status; prompt-only mode is exempt. Composed failures preserve run artifacts.
  Muse's original zero status was not independently reproduced; check the runner
  too. Capture the Python process status, not `tee`'s status (use `pipefail` or
  a subprocess's returncode).

Muse already completed no-API recomposition of the older approved package:
8 pages, no repeated continuation art, corrected numbering/logs, byte-identical
saved scenes and no reported clipping/caregiver-only pages. Do not repeat that
layout pass unless new evidence warrants it. Phone-photo and physical AirPrint
acceptance remain pending.

### First: inspect the slow planner retry ($0)

Read the latest private `planner_attempts.json`, coverage reports and timings.
Identify the actual reason for the second 52s planning request; do not infer it
from model scores. Return the specific failed objectives/constraints to Codex.
Keep Sol and the existing content policy unchanged during the artwork comparison.
This inspection should not trigger another planner request or an automatic retry.

### Second: compare gates on saved human-labelled scenes

Use `experiments.scene_gate_compare`, which calls the actual v5 gate wiring for
both Luna Decisions and Haiku vision, without creating any images or changing
planner/judge model environment. It is dry by default and live requires a vault
key plus shared USD/call/deadline limits and verified ceilings for both models.
The cumulative $5 cap applies. Allocate a small portion (aim <=$0.25 if current
conservative ceilings permit); reserve the rest for one full run.

Create a **private** JSON manifest with human labels assigned before inference:

```json
{
  "package": "/private/live-run/artifacts/frozen_render_package.json",
  "cases": [
    {
      "id": "owner-accepted-word-tiles",
      "image": "/private/saved/word-tiles.png",
      "worksheet": 1,
      "human_approved": true,
      "notes": "Relevant word-building action; owner accepted."
    },
    {
      "id": "wrong-action",
      "image": "/private/saved/wrong-action.png",
      "worksheet": 1,
      "human_approved": false,
      "expected_failed_checks": ["action_ok"]
    }
  ]
}
```

Each case must use the **actual corresponding frozen approved package and
worksheet index**, not guessed associations. Cases from another package override
`package` per case. The tool verifies frozen approval, hashes and reference,
then uses that worksheet's exact v5 action/outfit/rubric for each model. A
cross-spec control deliberately uses the mismatched worksheet and is labelled
rejected. Labels not yet reviewed by Howard must be described as provisional
Muse labels, not owner approval.

Include the owner-approved word-tile art, appropriate prior accepted scenes,
latest near-miss word-tile candidates, wrong-action/outfit and cross-spec controls.
Add clearly text-bearing/answer-bearing, blank/tiny and tiny-subject/large-background
controls if available. Locally derived negative controls are allowed if labelled
as synthetic controls; do not generate extra art. Some old circled-choice scenes
are now genuine negatives because they conflict with the new unmarked action.
Do not label all previously accepted artwork positive automatically.

```bash
# Set vault key surrogate and verified USD/call/deadline limits/ceilings first.
# Both requested IDs must have current conservative ceilings; no guessed prices.
export WORKSHEET_OPENROUTER_SCENE_JUDGE_REASONING_EFFORT=low
python -m experiments.scene_gate_compare --cases /private/scene-cases.json \
  --output /private/gate-comparison-dry
python -m experiments.scene_gate_compare --cases /private/scene-cases.json \
  --output /private/gate-comparison-live --live
```

Default is one request per model per case (HTTP retries can add attempts).
Preflight requires the allocation to cover the verified ceilings and one transport
retry per request; reduce the labelled set or reconcile more of the existing
remainder if it cannot fit. Do not understate ceilings.
Optional `--repeats 2` tests identical bytes/rubric only if it fits the remainder.
Keep `scene_gate_comparison.json`, inference calls, run limits and timings.
Compare false accepts, false rejects, invalid replies, concrete reasons,
`expected_check_misses`, geometry and latency. Report distinct cases separately
from repeated observations. Served model IDs are in `inference_calls.jsonl`;
requested model IDs alone are not proof of the provider/model actually served.
The two backends use different bounds estimators; compare semantic decisions
separately from geometry and inspect the reported `bounds_source`.

Select Haiku for the next run if it accepts owner-approved relevant art and
rejects the required negative controls for the right reasons, with no observed
hard safety/text/answer leaks. Apply the same bar to Luna. If neither qualifies,
stop and return failures; do not spend on a full art run or lower more cutoffs.
This small comparison is diagnostic, not proof of >=95% quality. It cannot write
worksheet approvals or overwrite original scene receipts. No production promotion.

### Third: one fresh full end-to-end run

If the comparison qualifies a gate, run lesson 100 once in an empty directory:
Sol 6.1 medium planner and content judge, fresh scenes in bounded parallelism,
the selected artwork gate, vector PDF and all validators. Use the 300s diagnostic
window and remaining reconciled session allocation. Keep PDF fallback disabled.
For Haiku set:

```bash
export WORKSHEET_SCENE_GATE_BACKEND=vision
export WORKSHEET_OPENROUTER_SCENE_JUDGE_MODELS=anthropic/claude-haiku-5.5
export WORKSHEET_OPENROUTER_SCENE_JUDGE_REASONING_EFFORT=low
```

For Luna set `WORKSHEET_SCENE_GATE_BACKEND=decisions` and
`WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL=openai/gpt-6-luna-decisions`.
Keep Sol stage overrides below unchanged. Price/ceiling lists must cover every
configured planner/judge/image/gate model. Report actual elapsed time through a
merged validated PDF, exit status, planner retries, gate rejections, provider
fallbacks, art acceptance, human page review and reconciled spend. No PDF means
failure, regardless of deadline or process status. No automatic whole-run retry.

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
output endpoint, Luna Decisions supports image inputs, and Haiku supports vision plus
structured output on the selected routes.
Use the batch format documented for the Decisions API and retain model IDs as
actually served. The small shadow batch in the section above uses saved candidate
images; it replaces the old separate one-image trial. Jev probing is optional and
should not displace the full run or consume funds needed for it.

## Full lesson-100 pipeline and latency run

Use lesson 100 because it is the committed fixture Howard approved. Do not claim
to have tested 106 unless the actual source exists. Use Sol 6.1 medium for planner/judge and the qualified comparison winner for scene checks;
retain every attempted and served model name.

```bash
export WORKSHEET_OPENROUTER_TEXT_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_VISION_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_PLANNER_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_JUDGE_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_REVIEW_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_EXTRACTION_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_REASONING_EFFORT=medium
# Choose the gate that met the saved-image acceptance bar; this example uses Haiku.
export WORKSHEET_SCENE_GATE_BACKEND=vision
export WORKSHEET_OPENROUTER_SCENE_JUDGE_MODELS=anthropic/claude-haiku-5.5
export WORKSHEET_OPENROUTER_SCENE_JUDGE_REASONING_EFFORT=low
# For Luna use backend=decisions plus the exact Luna alias instead.
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
Luna is wired into the composed scene gate on this test branch with v5 provisional,
per-criterion thresholds and advisory coverage described above. Validate them against saved human labels
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
