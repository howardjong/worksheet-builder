# On-demand photo → personalized worksheet PDF

`hybrid_shell` now generates fresh instructional artwork on demand, then
composes the approved activities as visible, selectable PDF text. It does not
require a curriculum content pack or a library of pregenerated images. A new
photo can supply the lesson. The existing `image_gen` production default is
retained pending live acceptance; select the new mode explicitly:

```bash
python transform.py --input /private/new-photo.jpg --profile /private/learner.yaml \
  --theme space --render-mode hybrid_shell --output /private/run-output
```

The parent/teacher capture UI and native AirPrint integration are outside this
Python change. The output is a standard Letter PDF for the existing phone
sharing/printing flow. Test that flow on an actual phone and printer.

Latest fresh end-to-end trial: [expressive-reference handoff](handoffs/expressive-reference-end-to-end.md).
The composed scene prompt preserves reference anatomy/style, allows natural expressions,
models only its declared action and avoids passing raw worksheet text to the artist.
New prompt/reference hashes invalidate older artwork caches; gate v5 is unchanged.

## Request path

1. Capture and extract the original photo with a validated transcription schema,
   independently routed extraction model, semantic regions for non-UFLI layouts,
   and real uncertainty flags. Uncertain transcription or an unidentified skill
   blocks the composed photo trial before planning. Optional extraction caching
   is keyed by original photo bytes, transcription contract and model chain;
   old confidence-free cached extractions are not reused.
2. Adapt within the learner's grade, workload and format constraints. In composed
   mode, instructional pictures are not guaranteed: avoid picture-dependent
   matching and choose asset-independent tasks before judging.
3. Finalize splitting, caps and instruction clarity **before** the pedagogical
   judge sees the package. An approved package is not edited by AI review later.
   A live composed run requires `approved: true` bound to the exact package hash
   before artwork. Objective planner artifacts also save `approval_decision` from
   the deterministic tri-state derivation; the model's diagnostic
   `approval_recommendation` cannot substitute for this contract. The finalized
   activity JSON is retained privately even if approval or artwork later fails.
   Deterministic answer-key, coverage, skill, grade, ADHD and workload checks also
   stop failed content before any illustration calls.
   Photo coverage requires every target/list/chain word, student sentence and
   full passage to have practice evidence in `photo_coverage_ledger.json`.
   Titles, goals, examples and distractors do not count. Valid production answers
   can count; lesson mode intentionally retains objective sampling. Instruction
   limits, skill drift and response compatibility are blocking in this pilot.
   A worked example starts the package; continuation omissions remain advisory.
4. Generate a text-free learning scene for each mini-worksheet, with bounded
   overlap across independent worksheets. One batched Luna Decisions request checks stable
   character identity against its reference, the declared dominant action, theme
   outfit, child-safe calm imagery and no text/answers. Measured foreground/printed
   extent prevents tiny scenes; model-estimated painted coverage is advisory.
   `scene_action()` selects a specific section and models its reading, word-building,
   segmentation, choosing or writing procedure with concrete text-free actions/props.
   A comparison skill no longer overrides a reading/writing procedure. The same contract feeds the artist
   and judge and is saved with every candidate. Missing reference cannot pass
   actual identity judging. Provider fallback remains sequential for each
   scene. The illustration is placed once next to its declared section; continuation
   pages use the space for practice instead of repeating the same artwork.
5. Compose serially with ReportLab: measured headings, real practice text, dotted
   tracing, choices, sound boxes and writing areas. Short written items in grades
   2–3 can use numbered pairs; longer text and younger learners stay full-width.
   Check actual drawn instructions, examples, options and item text. Keep the
   final practice with its caregiver log; reject pages without child practice.
   Visible item numbers restart at 1 within each section without changing source IDs
   or approved content. Caregiver logs count tasks/words per section; passages receive
   qualitative reading feedback rather than an invented denominator.
   Child-facing goal/name/break text uses the grade's body type; caregiver logs
   and footers use smaller type. `layout_report.json` records actual physical
   pages and effective raster PPI; 300ppi and compact packages are not assumed.
6. Validate the actual delivered activities and PDF, then merge. Hashes in
   `approval_contract.json` detect any change between judging and delivery.

Picture matching backed by verified, task-specific art is deferred. Learning
scenes are supplemental; they must not contain information needed to solve an
activity. The prompts allow theme costumes while retaining face/hair/proportions,
so a spacesuit does not contradict an ordinary-clothes identity reference.

## Controls

| Variable | Default | Effect |
|---|---|---|
| `WORKSHEET_IMAGE_CONCURRENCY` | `3` | Independent scene jobs; clamped to 1–4. `1` gives a serial comparison. |
| `WORKSHEET_SCENE_REFERENCE_LIBRARY` | Unset | Opt-in approved rainbow-buddy/space manifest: original + action expression + astronaut references; original-only identity judge, hash/approval validation, provider fallback disabled for this pack. |
| `WORKSHEET_SCENE_MAX_CANDIDATES` | `2` | Total image model candidates per scene; clamped to 1–4. One quality attempt per candidate. |
| `WORKSHEET_OPENROUTER_IMAGE_MODELS` | Existing ordered chain | Models tried for each scene; only the first N candidates are considered. |
| `WORKSHEET_SCENE_GATE_BACKEND` | `decisions` | Batched Luna gate; explicit `vision` selects the configured structured vision model. No automatic backend fallback. |
| `WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL` | `openai/gpt-6-luna-decisions` | Only the verified image-capable Luna slug is accepted in this trial. |
| `WORKSHEET_OPENROUTER_SCENE_JUDGE_MODELS` | Sol 6.1 | Overrides only explicit vision gate mode; use `anthropic/claude-haiku-5.5` for the comparison. |
| `WORKSHEET_OPENROUTER_SCENE_JUDGE_REASONING_EFFORT` | `low` for Haiku trial | Scene vision stage only; leaves Sol planning/judging medium. |
| `WORKSHEET_OPENROUTER_EXTRACTION_MODELS` | Sol 6.1 | Independent photo transcription routing. |
| `WORKSHEET_OPENROUTER_PLANNER_MODELS` | Sol 6.1 | Independent content authoring routing. |
| `WORKSHEET_OPENROUTER_JUDGE_MODELS` | Sol 6.1 | Independent pedagogical approval routing. |
| `WORKSHEET_OPENROUTER_REVIEW_MODELS` | Sol 6.1 | Review routing for unapproved content. |
| `WORKSHEET_OPENROUTER_REASONING_EFFORT` | `medium` for Sol 6.1 | Explicit supported effort overrides this default. |
| `WORKSHEET_OPENROUTER_SCENE_TIMEOUT` | Global timeout (180 s) | Per-HTTP-attempt timeout for scene generation and scene gate. |
| `WORKSHEET_OPENROUTER_PLANNER_TIMEOUT`, `...JUDGE_TIMEOUT`, `...REVIEW_TIMEOUT` | Global timeout | Corresponding per-attempt timeouts. |
| `WORKSHEET_ALLOW_PDF_FALLBACK` | Enabled | `0` stops if artwork fails; otherwise emits a usable plain composed PDF with artwork approval false. |
| `WORKSHEET_RUN_MAX_USD` | Unset | Run-scoped admission budget using verified per-call cost reservations. |
| `WORKSHEET_CALL_CEILINGS_JSON` | `{}` | Model ID to conservative USD ceiling per HTTP attempt; mandatory for priced calls when a USD limit is set. |
| `WORKSHEET_RUN_MAX_CALLS` | Unset | All HTTP attempts across roles, retries and fallbacks. |
| `WORKSHEET_RUN_DEADLINE_S` | Unset | Stops admitting work after the shared deadline and clamps remaining per-phase HTTP timeouts. |
| `WORKSHEET_OPENROUTER_REQUIRE_ZDR` | Unset | `1` enforces ZDR plus denied data collection on every inference route; no weaker retry. |

The pooled transport permits four concurrent connections. Transient transport
failures still have one retry; a model chain can make additional calls. These
settings bound concurrency/candidates. Optional run limits reserve every HTTP
attempt atomically across workers and keep unknown costs reserved. Missing prices,
exhausted budgets, too-low ceilings or elapsed deadlines fail closed. Reservations
are only as sound as the supplied ceilings; keep an account/key spending cap.
They do not guarantee provider charges or a hard end-to-end deadline: HTTP phase
timeouts, server-side billing and running threads can outlive the deadline.
Do not race four providers for the same image or assume cancellation prevents billing.
Limits reset per public run/process, so the live-test session budget must also be
tracked externally. Report `run_limits.json` even on failure.

Without a key, the offline pipeline can produce a plain PDF. That is a degraded
result, not a visually approved first pass. Hybrid fallbacks set
`artwork_approved=false` and `all_validators_passed=false`.

## Measurements and feedback

Every public collected run writes `inference_calls.jsonl` and
`timing_summary.json` in its artifact directory, including on failure. Events
contain stage, endpoint, model, attempt, status, duration, available token counts
and reported cost; they exclude prompts, pictures, names and keys. Content
artifacts themselves remain private. Stage spans are nested and may overlap:
do not sum them to infer wall time. `completed` means the function returned,
not that it passed quality. `run_summary.json` records aggregate quality and renderer
results, including artwork degradation. `cost_is_complete=false` means reported spend is
incomplete, not zero; use OpenRouter account records to reconcile it.

All generated candidate bytes, including rejections, are retained privately as
`candidate_N.png`, with selected/outcome/gate/hash/action metadata. Inference
events include candidate and request IDs where available for cost reconciliation.
Names are removed from planner/adaptation prompts; personalization is drawn locally.
Photos, character descriptions and private artifacts can still contain identifying
information; crop/redact inputs and keep them out of git. The legacy whole-page
renderer is unchanged and may include the name in its image prompt.

`frozen_render_package.json` captures the approved package and its original coverage
policy before artwork, so even a failed scene run can be replayed without another
planner call. `python -m experiments.live_replay --manifest ... --output ...` is a
no-inference dry-run by default. `--live` requires key/limits/prices, rejects cache
contamination and produces no plain fallback; `--worksheet 1` allows a small trial.
It reruns deterministic checks and refuses changed or unapproved content.
`--reuse-scenes /private/saved-replay-root` recomposes without inference using
unchanged approved `render_N/learning_scene.*` files, preserving content and
image hashes. It rejects changed/missing/unapproved scenes and cannot be combined
with `--live`. Legacy v2 scene receipts require the original image/vision model
configuration to verify their old cache key; reading an old receipt is not a new
Luna approval. This is layout QA, not a live performance benchmark.

`experiments/photo_intake.py` lets the live tester freeze transcription for human
comparison with the original photo before planning/art. It is dry by default;
`--live` requires a private extraction cache and verified limits. The full run
reuses that cache when photo bytes and extraction models stay unchanged. The
composed photo intake also rejects student-facing regions lost by skill mapping;
mixed story/word-work layouts use semantic mapping rather than dropping a page.

Worksheet gate v5 is an **application rubric**, not a Luna model version. The
requested decision model is `openai/gpt-6-luna-decisions`; OpenRouter may report a
dated served version. Seven semantic checks block: identity .85, task relevance
.35, recognizable procedure .35, outfit .85, child safety .95, no text .95 and
answer-free .95. These remain provisional cutoffs from very little labelled art.
A choosing illustration shows a pencil hovering above unmarked cards, preserving
the prohibition on marked practice answers. Relevant procedure art need not be
artistically perfect; the action/props and theme still have to be recognizable.

The eighth Luna question (estimated painted semantic coverage >=55%) remains
recorded as an advisory score. A probability of .41 is not an area measurement
of 41%, and imposing .95 confidence on that estimate rejected owner-accepted art.
Resolution, foreground bounding **extent** >=55% of image area and printed extent
>=the design-spec minimum still block empty/tiny art. These extents allow white
gaps inside a useful scene. Luna bounds are local nonwhite pixel bounds, which
can include background/decorations; they are not semantic coverage. Haiku vision
returns estimated semantic bounds. Human-labelled tiny-subject/large-background
controls must expose weaknesses in either estimator. Mandatory relevance/action
checks and human review remain necessary; this is not measured first-pass quality.

Explicit `vision` mode can use `anthropic/claude-haiku-5.5` with structured JSON
and short concrete blocking reasons. Its default scene effort is low; Sol planner
and content judge remain medium. No automatic backend/model escalation occurs.
New scene keys bind prompt, policy, models, reference and effort. Old v2/v3/v4
receipts remain usable for no-API recomposition under their original provenance,
never silently becoming v5 approvals.

`python -m experiments.scene_gate_compare --cases /private/cases.json --output ...`
validates genuine frozen packages and human-labelled saved images without paid
calls by default. Explicit `--live` compares Luna and Haiku using the actual v5
rubric, shared verified limits and no image generation. It saves per-image hashes,
raw gates, false accept/reject counts, expected-control misses and partial results
on failure. Optional repeated observations are not independent labelled cases.
It cannot authorize worksheet delivery. See the live handoff for manifest format,
remaining session budget, negative controls and conditional full-run instructions.
The CLI now exits nonzero on missing PDF or failed validation, preserving artifacts;
intentional `image_prompt` output is exempt. Verify the process exit status itself,
especially when using shell pipelines.

The Decisions adapter `ai.openrouter.decide_yes_no()` uses `/api/alpha/decisions`,
separate from chat. The documented image-state format was checked on 2026-10-08
(strings and image_url parts in a top-level state array). Invalid/missing checks
fail closed. A model's self-reported probability is not measured accuracy.

Official API reference: https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request
Multimodal state format: https://openrouter.ai/docs/guides/community/multimodal-decisions
Privacy routing: https://openrouter.ai/docs/guides/features/zdr

Use `python -m experiments.live_decisions --state ... --questions ... --model ...
--output ...` for a dry-run; explicit `--live` adds a bounded shadow call and saves
probabilities. It cannot authorize worksheet delivery.

## Offline checks

```bash
python -m pytest tests/ experiments/corpus_ufli/tests/ -q
python -m ruff check .
python -m mypy .
python -m experiments.on_demand_bench --output /tmp/worksheet-bench
```

The benchmark blocks HTTP even with a key in the shell. It exercises the five
committed lesson fixtures with synthetic artwork and a simulated 50 ms image
latency, comparing one and three workers. Its results establish local composition
and overlap, not live latency, image quality or first-pass acceptance.

Live protocol: [handoffs/on-demand-live-validation.md](handoffs/on-demand-live-validation.md).
There is no demonstrated sub-three-second photo-to-PDF result yet. Fresh image
generation and photo extraction remain on the critical path; measure their p50
and tails before setting a realistic service target.
