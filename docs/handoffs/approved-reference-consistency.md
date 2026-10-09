# Approved character references: next live consistency screen

This is the next experiment handoff on `codex/on-demand-composed-worksheets`.
Keep main unchanged. No renderer promotion or merge is authorized here.

## What changed

Howard approved the new reference library on 2026-10-09: 12 expressions, 12
study/support poses, eight outfits and 12 accessories. The six source sheets,
44 named PNG crops, original source pages/crops, generation prompts, gallery,
catalog and hash/approval manifest are committed at
`assets/characters/rainbow_learning_buddy/reference_library/v1/`.
Approval is for visual likeness and reference use. It is not a live identity
gate result or evidence of reliable first-pass generation. The original
character remains the identity authority; no production defaults changed.

Muse's earlier implementation is now on remote at `57c1504`. Its reported
screen found A 0/4, B 0/4, C 1/4, D 0/4. The structured prompt performed worse;
do not build the new comparison on that rewrite. Howard rejected the shown
samples for likeness, including the nominal C pass. Do not count that image
as a human-approved success. This new library supplies better conditioning
inputs, not a lower acceptance bar.

## Hypotheses and design

Hold the current procedure prompt, activity content, generation settings and
Luna v5 rubric fixed. Every arm adds the same short reference-role instruction.
That makes this a matched reference-input comparison; A is not a byte-identical
replay of the old prompt. All arms keep the identical frozen original as their
first generation image and their only judge identity reference.

| Arm | Second reference: face/hair detail | Third reference |
| --- | --- | --- |
| A | Exact crop of frozen original | None |
| B | Approved generated neutral-friendly face | None |
| C | Exact crop of frozen original | Approved astronaut |
| D | Approved generated neutral-friendly face | Approved astronaut |

H1: the sharper approved face improves likeness conditioning. H2: the approved
astronaut reduces identity drift during costume transformation. The full 2x2
design can expose interaction: the outfit might help only with one face source.
It does not isolate image resolution from artistic reconstruction within H1.

Two actions (word building and considering blank choices), two repetitions per
arm: 16 fresh images, 32 logical image/gate calls, up to 64 HTTP attempts with
transport retries. Concurrency three, interleaved schedule seed 20261009.
These are independent candidates, not quality retries. No provider fallback.
If the verified remaining allocation cannot fit 16, reduce to one repetition
for all arms/actions (eight images). Never drop a losing arm mid-block.

Image: `openai/gpt-image-2.5-sunburst`, quality auto, background opaque, 16:9.
Gate: `openai/gpt-6-luna-decisions`, existing seven checks and geometry policy.
Identity remains >=0.85. Record the served model/provider, not just requested ID.
No planner calls are needed for this screen.

## Offline preflight and inputs

1. Fetch the branch into an isolated worktree and pin the exact commit/tree from
   Codex's handoff. Read AGENTS and running context. Run `make lint`,
   `make typecheck`, `make test-all` using repository dependencies.
2. Validate the full approved library (`test_library_hashes_and_owner_approval`).
   The runner checks selected PNG hashes, dimensions and approval before inference;
   it rejects unrelated characters/themes, invalid crop bounds, unbalanced arms,
   or action labels inconsistent with the frozen worksheet.
3. Use the genuine private hash-bound approved package from the previous live
   run. Do not manufacture an approval or re-plan to accommodate the experiment.
   Restore missing reference paths only by relocating the exact original bytes;
   verify their SHA-256 against the prior screen. Never substitute a generated
   library image as the gate authority. Leave approved worksheet content unchanged.
4. Copy the example below into a private manifest. Set the actual package path,
   the exact face-crop rectangle from the earlier screen, and worksheet indices
   that dry-run confirms select `build` and `choose` actions. Resolve the library
   path against the pinned checkout, not the private manifest directory.

```json
{
  "package": "/PRIVATE/genuine/frozen_render_package.json",
  "face_crop_rect": [0.33, 0.0, 0.66, 0.42],
  "procedures": {"word_building": 1, "blank_choices": 2},
  "repeats": 2,
  "arms": ["A", "B", "C", "D"],
  "design": "approved_reference",
  "expression": "neutral-friendly",
  "reference_library": "/PINNED/CHECKOUT/assets/characters/rainbow_learning_buddy/reference_library/v1/manifest.json"
}
```

The rectangle/indices above are examples, not a claim about private artifacts.

```bash
python -m experiments.character_consistency \
  --manifest /PRIVATE/new-reference-manifest.json \
  --output /PRIVATE/new-reference-dry-run
```

Review `prompts.json`, `experiment_report.json`, reference hashes/order, and crop
provenance. Prompts must match within each action across all four arms; the
original hash must match everywhere. Dry-run makes zero inference calls.

## Paid screen admission

Use only the existing vault surrogate. Never print or write the real key.
Reconcile the cumulative $5 session cap first: Muse's ~$2.01 spent/~$2.99 left
report also mentioned an unmeasured screen and a conservative $0.50 reservation.
Resolve whether that reservation was already included. Unknown charges remain
reserved; that report is not a fresh $5 allocation.

Allocate at most min($1.20, actually remaining) to this screen, with verified
current per-call ceilings, attempt cap (64 for 16 trials; 32 for eight), and
300s cooperative deadline. Keep the external cap. The runner requires allocation
for the entire block at declared ceilings including one transport retry per
call; reduce complete blocks or stop if it cannot fit. Existing in-flight calls
cannot be unbilled by a deadline. No automatic rerun after a partial block.

Set `WORKSHEET_RUN_MAX_USD`, `WORKSHEET_RUN_MAX_CALLS`,
`WORKSHEET_RUN_DEADLINE_S`, `WORKSHEET_CALL_CEILINGS_JSON` and
`WORKSHEET_SCENE_GATE_BACKEND=decisions` and
`WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL=openai/gpt-6-luna-decisions`.
Then run the same command with `--live` and a
fresh private output directory. Retain candidates, gates, hashes, served models,
timing, inference log and limits. Worker context propagation now has offline
regression coverage for shared cost recording and over-ceiling rejection.

## Readout and next step

Report gate pass counts and identity scores by arm and action, generation/gate
latency, reconciled cost, and descriptive main effects/interaction. Small n is a
screen, not proof of a production success rate. Treat errors/missing gates as
failures. Show Howard every gate pass and representative near misses, with arm
labels hidden if practical. First-pass quality requires both all gates and
owner likeness acceptance; report false accepts and false rejects separately.

If a configuration helps, confirm it on fresh candidates before integration.
A bounded follow-up can compare neutral vs happy-open-smile supplements within
that configuration, with the same procedure and explicit permission for a
natural expression change in the generation prompt. Keep the gate unchanged;
flag human-approved expressions that the gate rejects rather than lowering the
identity bar. Other poses/accessories stay out of this first screen.

Only after fresh gate passes and owner acceptance, wire the selected conditioning
pack into on-demand generation with hash/approval checks and the original gate
authority. Then, if the reconciled remaining cap covers it, reserve at most
$0.60 for one fresh lesson-100 full pipeline run (Sol medium planner/content
judge; qualified Luna gate; no PDF fallback). That integration needs a tested
commit; this experiment-only change does not alter production reference selection.
If integration is not yet committed, stop with the comparison evidence and
return it to Codex. Do not report render-only replay as end-to-end success.

Full-run acceptance: a fresh PDF, all content/scene/print checks, owner likeness
and useful varied actions, no regeneration or degradation. Measure from intake
through PDF completion and expose every retry. Report the phone-photo and actual
AirPrint paths as pending until tested with an authorized photo/device.

## Copy-paste Muse task

> Fetch and pin the commit/tree supplied by Codex on
> `codex/on-demand-composed-worksheets`; keep main untouched. Follow
> `docs/handoffs/approved-reference-consistency.md` in full. First run offline
> checks and a zero-cost dry-run. Reconcile the existing cumulative $5 budget,
> including the previously unmeasured screen, before any paid call. Use my vault
> surrogate and run the balanced A/B/C/D approved-reference comparison within
> the bounded screen allocation, with current prompt, Sunburst, Luna v5 and
> identity >=0.85. Keep the frozen original as the judge reference. Save every
> candidate and return pass counts, identity scores, timing, actual reconciled
> spend and owner-review images. No automatic integration, threshold changes,
> merging, or full-pipeline run before fresh gate and owner acceptance. If a
> budget or preflight requirement fails, return the evidence without spending.
