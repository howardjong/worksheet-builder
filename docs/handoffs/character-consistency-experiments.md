# Muse: first-pass character consistency experiments

Next live trial: [approved reference consistency screen](approved-reference-consistency.md).
This supersedes earlier experiment ordering and spend snapshots.

Date: 2026-10-09. Repository: `howardjong/worksheet-builder`.
Working branch: `codex/on-demand-composed-worksheets`; do not merge into main.

This is the current experiment handoff. It supersedes the next-trial ordering
and spend snapshots in [the earlier live handoff](on-demand-live-validation.md).
That document remains the reference for vault injection, privacy routing,
run limits, full-pipeline commands and frozen-package verification.
Read [the supplied research report](../research/character-consistency-consolidated-report.md).
The report is preserved verbatim; its recommendations are hypotheses, not new
measurements. This commit adds documentation only. The experiment runner and
transport extensions described below still need implementation before live use.

## Objective and fixed requirements

Improve first-candidate acceptance of fresh, relevant, nonrepetitive illustrations
and measure complete worksheet latency. The child customizes the learning buddy
as a reward: likeness is a product requirement, not optional decoration.

- Keep the v5 Luna rubric and all existing thresholds: identity .85, task .35,
  action .35, outfit .85, safety .95, no text .95, answer-free .95. Keep the
  existing mandatory resolution/geometry/printed-extent checks too.
- Requested artwork judge: `openai/gpt-6-luna-decisions`. Record its actual
  served ID; "v5" identifies the application rubric, not the model.
- Keep Sol planning/content judging at `openai/gpt-6.1-sol`, medium effort.
- Incumbent artist: `openai/gpt-image-2.5-sunburst`. Keep actual practice text
  vector-rendered; art demonstrates a procedure without target answers.
- Generate lesson-specific art on demand. No prebuilt lesson illustration library.
- Do not change thresholds, gate wording, worksheet content or judge references
  mid-experiment. Do not treat a marginal numerical failure as a pass.
- No PDF fallback, unapproved-content override, automatic model escalation or
  whole-run retry for acceptance trials. Existing main/default renderer stays put.

Owner review validates the product requirement but does not calibrate the gate
over a population. Codex's earlier procedure-usefulness judgments of previews
were not canonical-reference likeness approvals and must not become such labels.

## Evidence ledger: inspect before spending

Reported by Muse, not independently reproduced by Codex:

- Tested baseline `a1c76bfdeb48b9852e4ce5a70b8f9f21831d307f`, tree
  `5e2442a639e3b33f4b1dbc1af447dd433b5ed03a`: 1,186 tests, lint/typecheck clean.
- Latest full run failed at artwork after 111s, exit 1, no PDF: planner 47.5s
  in one call, content judge 14s/approve .89. Two Sunburst scenes narrowly
  missed task (.32 vs .35) or identity (.83 vs .85). These are failures.
- Saved-art v5 comparison: Luna 6/6; Haiku 5/6, with one geometry rejection
  despite semantic approval. This is a small smoke comparison, not accuracy.
- Earlier second planner call was a legitimate P3c coverage retry after a missing
  connected-text passage. Do not remove coverage checks to save that time.
- Later reference ablation: identity .72 with reference, .17 without; FLUX.3
  slower/.62 identity; Flare faster but below the product bar. One rewrite
  sample was inconclusive. These support prioritization, not causal proof or
  population yield. Missing references have not been proven to explain Gemini.
- Full fresh first-pass success, novel phone-photo intake and AirPrint remain
  unestablished. Prior successful render replays are not full-pipeline timings.

Inspect `~/workspace/wb-ondemand-run/` and any later experiment roots. Preserve
original unannotated PNGs, canonical references, prompts, frozen packages, gates,
timings, inference logs and owner labels. JPEG previews with red bounds are not
generation references or evaluation inputs. Resolve worksheet/candidate mappings
from artifacts, not the duplicated caption in chat. Mark unknown mappings unknown.

The last quoted ~$3.07 remainder predates later ablations and is stale. Reconcile
all prior spend against the same authorized **$5 cumulative session cap**, including
failures, replays and probes. This plan grants no new $5 allocation. Unknown or
unreconciled charges remain reserved, not zero. If insufficient, complete offline
preparation and return the exact additional budget needed; do not reset the cap.

## Phase 0: offline preparation and provenance

Use an isolated worktree from the current remote test-branch head. Record commit,
tree and main head; inspect intervening changes. Read AGENTS.md and current
project context first. Preserve other worktrees/artifacts. Run the normal offline
checks before inference. No OpenRouter key is needed for this phase.

Implement the smallest opt-in experiment support on the test branch:

1. **Reference roles:** generation gets an ordered reference pack; judging always
   gets the immutable original customized character. `_reference()` currently
   prioritizes pose over canonical over base. Inspect which bytes are truly the
   owner-approved original; do not silently substitute a pose or themed anchor.
   Give generation and judging separate functions/explicit inputs. Changing a
   generation reference must not change gate-reference hashes.
2. **Transport:** extend `ai/openrouter.generate_image()` compatibly to accept
   multiple references and explicit supported quality/background parameters.
   Preserve legacy single-reference callers. Validate conflicting arguments,
   reference limits and model-specific capabilities before a paid request.
   Preserve RGBA when transparency is present; current RGB conversion loses it.
   Do not send unsupported seed, strength or input-fidelity controls.
3. **Prompt experiment:** preserve the exact current `scene_prompt()` output as
   arm A, and add an experiment-only structured prompt for B/D. The current
   `character_block` mixes generic theme style/body/face/palette descriptions
   into a noun phrase. Keep source identity authoritative; separate identity,
   costume, one selected section/action, props, sparse composition and exclusions.
   Do not invent facial measurements or let generic "rounded astronaut" style
   override the reference. Face and hair remain visible; costume should preserve
   proportions. Remove unrelated section goals and busy environmental requests.
   Keep the actual required action, outfit and answer-free policy unchanged.
4. **Runner:** proposed new module `experiments/character_consistency.py` (does
   not exist in this documentation commit). Use a validated private case manifest,
   dry-run default, explicit `--live`, existing telemetry/run-limit admission and
   bounded workers. No independent untracked API client. Snapshot plans/prompts
   before inference, preserve each result incrementally, and resumably skip only
   completed trial IDs. Every repetition generates a fresh image, not a cache hit.
   Shadow results cannot write production scene approval receipts.
5. **Accounting:** bind trial identity to code, prompt version, original-reference
   hash, ordered generator references, crop rectangle, spec/action hash, model,
   provider routing and parameters. Record retries and actual HTTP attempts.
   Hash/snapshot gate state/questions/thresholds/preprocessing. Generator prompt
   changes require new scene cache keys if later integrated into production.

Meaningful offline checks: multiple-reference payload/order, unchanged single-ref
callers, RGBA preservation, rejected unsupported settings, original-reference
invariance, dry-run no-network, budget admission across workers, retained partial
results and fail-closed exits. Run `make lint`, `make typecheck`, `make test-all`
after implementation. Do not claim this documentation-only commit includes them.

Build private manifests from genuinely approved frozen content where available.
Freeze content and selected actions; do not pay for fresh planning during the
image screen. Verify frozen content hashes. Additional character states are
explicit experiment inputs, not edits to the signed frozen package or fabricated
approval. Human labels must identify author, reference state and criterion.

## Phase 1: bounded prompt/reference discovery

Hypotheses: conflicting prompt instructions reduce likeness; an original face/hair
crop improves identity conditioning without sacrificing the required action.

| Arm | Prompt | Generation references | Evaluation reference |
| --- | --- | --- | --- |
| A | Exact current prompt | Original full-body | Same original full-body |
| B | Structured, single-action, sparse prompt | Original full-body | Same original full-body |
| C | Exact current prompt | Original full-body + original face/hair crop | Same original full-body |
| D | Identical to B | Original full-body + original face/hair crop | Same original full-body |

Use **two authorized character/customization states x two procedures** (word
building and considering blank choices), two fresh repetitions per arm: 8 images
per arm, **32 images total**. This is a complete 2x2 factorial design: prompt
(current/revised) x references (original/original+crop). A/B measures the prompt
bundle with one reference; C/D measures it with the crop. A/C and B/D measure
the crop under each prompt. Preserve the current prompt body verbatim; any
reference-role preamble must be identical across all arms and snapshotted.

Report the interaction as `(pass_rate_D - pass_rate_B) - (pass_rate_C -
pass_rate_A)`: does the crop help more under the revised prompt? Also report
case-level contrasts and identity/action outcomes. With only eight observations
per arm this is descriptive evidence, not a statistically established interaction.
The prompt is a practical bundle; no result attributes benefit to one sentence.

Use only existing authorized original states. A crop is derived from original
bytes without generative retouching. Store its coordinates/hash. If a second state
is unavailable, use one, reduce counts and explicitly narrow generalization;
do not spend on creating a second state just to fill the matrix. Do not falsify
owner approval of an unreviewed synthetic state.

Freeze 16:9, n=1, one Sunburst route and identical supported quality/background
settings across arms. Use explicit `quality=auto`, `background=opaque` if endpoint
preflight confirms support, to isolate prompt/reference changes. Record that auto
may itself vary internally. Quality sweeps happen separately. Record original
image/reference dimensions and output sizes; never silently resize only one arm.

Generate a deterministic randomized/interleaved schedule, balance arm/case blocks,
save the scheduling seed, and use at most 3 concurrent jobs. The scheduling seed
is not an image-generation seed. Keep observed provider/served-model identity;
pin the advertised route and disable hidden provider fallback where supported.
If stable routing cannot be verified, label the routing limitation rather than
claiming an exact model/provider comparison. Model-version changes split results.

One image and one combined Luna gate per trial: 64 planned logical calls for the
full screen, up to 128 HTTP attempts if both transports allow one retry. Disable
quality-regeneration/model fallback in the screen. Transport retries are accounted
separately; strict no-retry success requires first HTTP attempts too. Validate and
gate once even rejected candidates; retain all seven raw scores and geometry.
No repeated gate sampling by default. Invalid results and provider errors count
against scheduled first-pass success, with separate reasons.

Before every block, verify endpoint capabilities/current prices and conservative
per-attempt ceilings for Sunburst and Luna. Use the existing vault surrogate and
shared limits. Reserve a conservatively priced complete pipeline trial when the
remaining cap permits. If the whole screen does not fit, execute complete balanced
blocks (all four arms for a case/repetition); preserve the unrun schedule.
Do not leave an arm untested while spending its allocation on extra winner samples.
Do not exceed the authorized cap to finish a statistically tidy matrix.

### Parallelism and later interaction tests

Design of experiments and concurrency solve different problems: the factorial
layout estimates combined effects, while bounded concurrent requests reduce
elapsed collection time. Keep concurrency 3 across arms, randomize within
complete blocks and interleave arms over time. Record dispatch/completion times,
queueing, provider changes, rate limits and HTTP retries. Do not launch one arm
at low load and another at high load. Avoid selecting only the fastest completed
trials; preserve every scheduled outcome. Generation must precede its gate, and
anchor approval must precede anchor-conditioned scenes; independent trials can
run together. Extra speculative candidates are not free latency improvements.

When the full 32-image screen does not fit, prefer fewer complete factorial
blocks (for example one repetition over four cases = 16 images), rather than
removing one cell and losing interaction visibility. If fewer character states
are available, document the narrower population. Small denominators remain
inconclusive; do not extrapolate a formal power calculation.

Later, if refs appear beneficial but quality is unclear, cross reference choice
with quality (2x2), rather than sweeping quality only at one reference setting.
If anchors are the leading hypothesis, cross original/themed primary reference
with crop absent/present (2x2) when budget permits. Do not combine prompt, refs,
anchor, quality, model and composition into one large matrix. A fractional design
is worthwhile only with an explicit aliasing plan; a small full factorial avoids
confounding the interaction we most want to measure. Pilot failures/separation
can make logistic interaction estimates unreliable; report raw cell rates and
paired case-block contrasts before fitting a model.

### Discovery decision rule

Predeclare before inference: prefer a candidate over A only if it has at least
two more all-check first-pass successes out of the planned eight observations,
has no observed new safety/text/answer leakage, and blinded human review supports
likeness and procedure usefulness. This is an operational shortlist rule, not
statistical significance or promotion. For a reduced screen, report directional
results without applying the eight-observation rule. If tied, favor the simpler
reference pack and report no measured winner. Never relabel a rejection to win.

Audit all boundary cases, all passes for safety/text/answers, and a shuffled
contact sheet of positives/rejections against their original references. Ask
Howard for likeness and procedure labels separately; Muse labels are provisional.
A larger face that boosts the gate but makes the action unreadable is a regression.

## Phase 2: targeted follow-ups, not an automatic giant matrix

Only proceed within a reconciled allocation and if the previous stage identifies
a useful direction. Do not run all follow-ups automatically. Report a proposed
next block and conservative cost if the existing cap cannot cover it.

| Priority | Hypothesis and comparison | Required controls |
| --- | --- | --- |
| 1 | Wardrobe changes cause drift: best original-reference condition vs themed anchor alone vs anchor + original face crop. | Original remains judge reference; same prompt/action/settings. |
| 2 | Quality improves yield: medium vs high, then xhigh only if justified. | Winning reference pack fixed; include added cost/time and actual output sizes. |
| 3 | Scene complexity hurts identity/action: sparse complete scene vs transparent foreground composition. | Same character/props/action; verify alpha and evaluate the final printed composite. |
| 4 | An alternative improves the best incumbent: MAI-Image-2.6 or Nano Banana 2.1. | Reverify current OpenRouter IDs/capabilities; same task/reference roles and compare all-check yield. |
| 5 | Identity-only repair is cheaper than regeneration. | Separate recovery arm; preserve correct action, re-gate all checks; never count as first-pass. |

**Anchor rules:** Create a neutral clothing-only edit of the original on demand,
using a plain background and unchanged visible face/hair/proportions. Gate likeness
against the original and obtain owner likeness/costume acceptance before using it
as an approved anchor. Do not treat a scene's action score as an anchor criterion.
Preserve original bytes and anchor provenance. The anchor is a character/theme
setup asset, not precreated lesson art. Version/invalidate it after customization.
Limit any pilot to one anchor candidate per state; failed setup is a reported
failure, not a free unbounded retry loop. Pending owner review, continue useful
offline analysis rather than pretending the anchor is approved.

Charge anchor generation/gating to cold end-to-end time and cost, and separately
report warm reuse. State the actual reuse count for amortized results; do not
assume a large imaginary user base. Evaluate every scene against the original,
never a drifted anchor. Compare anchor + original full-body only if the crop arm
leaves an unresolved failure; avoid starting with every possible reference pack.

**Composition rules:** Keep one contact/movement/destination clear. Blank tiles
illustrate word-building procedure, not verified phonemes. Avoid pseudo-writing,
control panels and arbitrary exact tile counts. Do not add arrows/motion cues
unless they fit the frozen artist/gate contract; otherwise make a separate policy
experiment. Include composition/cropping time and final print-size readability.
Alpha-based extent versus today's nonwhite bounds is a separate geometry policy:
do not silently change the gate or compare different policies as the same arm.

## Phase 3: confirmation, integration and complete latency measurement

Expand the shortlisted configuration to fresh representative character/action
cases with a matched incumbent comparison. Aim for at least 30 observations per
arm for initial confirmation when separately funded; this remains imprecise and
does not certify 95% yield. Broader 100-200 observations per arm require an explicit
budget and a justified study design. Report counts and case-stratified rates;
repeated generations of one scene are not independent product cases. Do not
advertise p95 latency from eight observations or assign precise power from this
screen. Keep development and confirmation cases distinct.

After offline checks and owner review, integrate the chosen configuration as an
explicit test-branch option with correct cache/provenance keys, then make **one**
fresh lesson-100 full-pipeline trial if its conservative ceiling fits. Use live
Sol medium planning/judging, fresh art, Luna, vector composition and validators;
parallel independent scene jobs (max 3). Set `WORKSHEET_SCENE_MAX_CANDIDATES=1`,
image chain Sunburst only, `WORKSHEET_ALLOW_PDF_FALLBACK=0`, and the diagnostic
300s admission deadline plus an external watchdog/account cap. No auto whole-run
retry. Capture actual Python returncode, not tee status. Timing ends only at a
merged, validated PDF; record subsequent human-review time separately. Product
acceptance still requires that review. Failures have their own elapsed times.

Use command/configuration names in the earlier handoff, overriding its historical
Haiku selection with Luna. Export `WORKSHEET_SCENE_GATE_BACKEND=decisions` and
`WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL=openai/gpt-6-luna-decisions`.
Per-process `WORKSHEET_RUN_MAX_USD`, call ceilings, calls and deadline must fit
the cumulative remainder; a process restart never replenishes the session cap.
Record cold anchor setup separately and include it in cold totals. A frozen replay
is useful for isolated rendering, but never substitutes for this full trial.

First-pass package success requires no planner coverage retry, art regeneration,
provider fallback, repair or validator failure. Record HTTP retries separately
and also give strict no-HTTP-retry success. Report recovered package success
separately. Two independent scenes with .95 yield each give only .9025 package
yield; do not claim a .95 package rate from scene scores. Measure real packages.

Once artwork yields reliably, inspect planner request/output/token timings.
Compare a compact structured response with explicit connected-text obligations
against the existing response, keeping Sol medium and the same coverage/judge
contracts. Do not merge this change into the image ablation. The reported 47.5s
planner + 14s content judge are already ~61.5s before art: better images alone
cannot establish a three-second workflow.

If an authorized anonymized novel phone photo is available and separately fits
the remaining budget, run the full photo path with extraction uncertainty/skill
checks; otherwise mark it pending. Do not substitute the lesson fixture for photo
acceptance. Howard must perform physical AirPrint/legibility acceptance with the
actual phone/printer; a PDF preview is not printing evidence.

## Required result bundle and closeout

Keep sensitive images, profiles/photos, generated art/PDFs and raw prompts private.
Commit only sanitized code, schemas, reproducible commands, aggregate results and
artifact identifiers/hashes that contain no personal data or credential material.
Use vault injection; never paste/log/store the real key. Preserve existing ZDR
routing for real child material; no weaker privacy fallback.

Private outputs:

- Frozen experiment manifest, shuffled schedule, case associations and original
  reference hashes; explicit labels including reviewer and approval scope.
- JSONL per trial: arm/case/repeat, code/tree, prompt/hash, reference roles/order/
  hashes/crop, model requested/served/provider, quality/background, candidate
  hash/dimensions, raw seven gate scores, booleans/geometry, outcome and concrete
  failed checks, generation/gate/composition durations, attempts/retries, tokens,
  cost/reservations and error. Preserve outputs before the next call.
- Summary: scheduled/completed/missing trials; all-check first-candidate and
  identity-only rates; per-case results; invalid/provider failures; human disagreement;
  cost per accepted scene including failures; cold/warm setup and complete-package
  timings. Show denominators and incomplete blocks; unknown charges remain unknown.
- Contact sheets at useful review size and actual printed-scale previews; original
  PNGs without overlays. Keep annotation overlays as separate derived files.
- Per-process limits/telemetry plus cumulative account reconciliation. A deadline
  prevents new admission; it does not cancel billed in-flight work automatically.

Commit the implemented harness/options and sanitized findings to the test branch,
update project context, run relevant checks, and push without force. Inspect a
moved remote head before reconciling; never overwrite another agent's work. Return
commit/tree, exact commands, budget ledger, measured winner or inconclusive result,
the principal failure taxonomy, and the smallest next experiment. Stop paid work
at budget exhaustion or a reproducible protocol defect, preserving partial evidence.
No merge, model/gate-default promotion, >=95% quality or <3s claim from this screen.

## Primary capability references

Historical review date 2026-10-09; Muse must recheck before inference:

- Sunburst endpoint capabilities: <https://openrouter.ai/api/v1/images/models/openai/gpt-image-2.5-sunburst/endpoints>
- OpenRouter image generation/routing: <https://openrouter.ai/docs/guides/overview/multimodal/image-generation>
- OpenAI reference/edit prompting guidance: <https://developers.openai.com/api/docs/guides/image-prompting>
- MAI endpoint capabilities: <https://openrouter.ai/api/v1/images/models/microsoft/mai-image-2.6/endpoints>
- Nano Banana candidate: <https://openrouter.ai/google/gemini-nano-banana-2.1>

Advertising reference support is not evidence of likeness yield on this buddy.
