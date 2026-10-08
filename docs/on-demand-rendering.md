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

## Request path

1. Capture and extract the new photo into the existing source/skill schemas.
2. Adapt within the learner's grade, workload and format constraints. In composed
   mode, instructional pictures are not guaranteed: avoid picture-dependent
   matching and choose asset-independent tasks before judging.
3. Finalize splitting, caps and instruction clarity **before** the pedagogical
   judge sees the package. An approved package is not edited by AI review later.
   A live composed run requires affirmative pedagogical approval before artwork.
   Deterministic answer-key, coverage, skill, grade, ADHD and workload checks also
   stop failed content before any illustration calls.
4. Generate a text-free learning scene for each mini-worksheet, with bounded
   overlap across independent worksheets. One combined vision call checks stable
   character identity (when a reference exists), learning action, no text/answers
   and substantial scene area. Provider fallback remains sequential for each
   scene. One scene is reused on that worksheet's continuation pages.
5. Compose serially with ReportLab: measured headings, real practice text, dotted
   tracing, choices, sound boxes and writing areas. Short written items in grades
   2–3 can use numbered pairs; longer text and younger learners stay full-width.
   Check actual drawn instructions, examples, options and item text. Keep the
   final practice with its caregiver log; reject pages without child practice.
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
| `WORKSHEET_SCENE_MAX_CANDIDATES` | `2` | Total image model candidates per scene; clamped to 1–4. One quality attempt per candidate. |
| `WORKSHEET_OPENROUTER_IMAGE_MODELS` | Existing ordered chain | Models tried for each scene; only the first N candidates are considered. |
| `WORKSHEET_OPENROUTER_SCENE_JUDGE_MODELS` | Existing vision chain | Combined scene gate model chain. |
| `WORKSHEET_OPENROUTER_PLANNER_MODELS` | Existing text chain | Independent content authoring routing. |
| `WORKSHEET_OPENROUTER_JUDGE_MODELS` | Existing text chain | Independent pedagogical approval routing. |
| `WORKSHEET_OPENROUTER_REVIEW_MODELS` | Existing text chain | Review routing for unapproved content. |
| `WORKSHEET_OPENROUTER_REASONING_EFFORT` | Provider default | Optional supported effort; evaluate low effort before adopting. |
| `WORKSHEET_OPENROUTER_SCENE_TIMEOUT` | Global timeout (180 s) | Per-HTTP-attempt timeout for scene generation and scene gate. |
| `WORKSHEET_OPENROUTER_PLANNER_TIMEOUT`, `...JUDGE_TIMEOUT`, `...REVIEW_TIMEOUT` | Global timeout | Corresponding per-attempt timeouts. |
| `WORKSHEET_ALLOW_PDF_FALLBACK` | Enabled | `0` stops if artwork fails; otherwise emits a usable plain composed PDF with artwork approval false. |

The pooled transport permits four concurrent connections. Transient transport
failures still have one retry; a model chain can make additional calls. These
settings bound concurrency/candidates, **not total spend or an end-to-end
hard deadline**. Do not race four providers for the same image or assume cancelling
a request prevents billing. A spend limit requires account/gateway enforcement.

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

The Decisions adapter `ai.openrouter.decide_yes_no()` supports named probability
checks using `/api/alpha/decisions`, separate from chat completions. Luna image
checks and Jev text checks are experimental **shadow evaluation**: they cannot
approve or override a worksheet. Live wire-format support, thresholds and false
acceptance rates must be checked against human labels before promotion. A model's
self-reported probability is not measured accuracy.

Official API reference: https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request

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
