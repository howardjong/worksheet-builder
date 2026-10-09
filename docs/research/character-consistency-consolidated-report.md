# First-Pass Character Consistency for Phonics Illustrations

**Consolidated evidence review and production playbook**  
**Verification date:** October 9, 2026  
**Scope:** Hosted image APIs, principally `openai/gpt-image-2.5-sunburst` through OpenRouter; children's worksheets for ages 5–8.

## 1. Executive recommendation

Keep Sunburst as the incumbent while testing a simpler generation workflow: **approve a theme-specific character anchor once, reuse immutable references for each scene, and ask for one clearly staged learning action against a sparse or separately composited background.** Preserve the owner-validated `identity_ok >= 0.85` requirement.

The current request combines identity preservation, wardrobe replacement, pose reconstruction, instructional action, prop placement, and environmental composition. Reducing simultaneous changes is a plausible way to improve yield, but the proposed workflow has not yet been tested with this mascot and gate. It is the highest-priority hypothesis, not an established performance result.

The recommended sequence is:

1. Repair prompt formatting and separate identity, clothing, action, composition, and restrictions.
2. Make hair and facial features visible; use a close-fitting costume that preserves recognizable proportions.
3. Create and approve a neutral themed anchor, checked against the original customized character.
4. Compare themed-anchor-only conditioning with themed anchor plus original reference; test a face crop as an additional condition.
5. Generate one decisive action moment with minimal decoration. Test transparent foregrounds and fixed backgrounds if the renderer supports layers.
6. Sweep supported quality settings independently of the initial prompt/reference experiment.
7. Benchmark MAI-Image-2.6 and Nano Banana 2.1 against the improved Sunburst workflow. Consider Ideogram Precise Edit for localized repair.

No public evidence reviewed establishes that another hosted API is superior on this exact mascot-identity task. Broad editing preference rankings favor Sunburst at `max`, but they do not establish which model or quality setting best passes this product's seven checks. [S5]

**Keep three outcomes distinct:** first-pass scene acceptance; acceptance after repair/retry; and end-to-end readiness for a newly customized character, including anchor preparation.

## 2. Evidence boundaries and the measured problem

This report consolidates three supplied reports. It retains their useful recommendations, resolves their disagreements, and checks material API and benchmark claims against primary documentation, live endpoint records, and original research. No new image generations, repository inspection, or Luna evaluations were performed.

### Product observations supplied in the reports

| Observation | What it supports | What remains unknown |
| --- | --- | --- |
| A supplied ablation reports identity scores of 0.72 with a reference and 0.17 without one. | Reference conditioning materially helped that tested case. | Sample count, repeated-run variability, and raw artifacts are unavailable; this is not a population estimate. |
| The owner agreed with rejection of a 0.83 candidate against a 0.85 threshold. | Retain the existing product acceptance requirement. | One owner judgment does not establish gate calibration across every pose, costume, or character state. |
| Identity is described as the binding check in a seven-check Luna Decisions v5 gate. | Optimize all-check first-pass yield, with particular attention to identity failures. | A complete score distribution and actual baseline yield are not supplied. |
| Earlier product tests reportedly found FLUX.3 and Flare inferior on relevant criteria. | Deprioritize retesting those configurations unless something material changes. | This does not prove that all configurations or future versions of those families are unsuitable. |

Do not recover missing quantities from the second report's broken placeholders. Its claimed likeness bands, per-quality latencies, and baseline yield are excluded because no reproducible supporting measurements were provided.

`identity_ok` is a rubric score. **A score of 0.85 is not an 85% acceptance probability, and the threshold does not imply a target yield of 85%.** Yield is measured separately across generations.

### Evidence hierarchy

| Category | Meaning in this report |
| --- | --- |
| Verified capability | Current official documentation or an inspected endpoint record supports the API behavior. |
| Product observation | Supplied test result; retained with its provenance and limitations. |
| External empirical evidence | Published benchmark or research finding; transfer to this task requires qualification. |
| Proposed intervention | A reasoned implementation or experimental choice; its mascot-specific uplift is unknown. |

## 3. What the current APIs actually support

### Sunburst through OpenRouter

The live OpenRouter Sunburst endpoint record was inspected on the verification date. It advertises the following capabilities. [S1]

| Parameter | Advertised support |
| --- | --- |
| `input_references` | 0–16 images |
| `quality` | `auto`, `low`, `medium`, `high`, `xhigh`, `max` |
| `aspect_ratio` | `1:1`, `3:2`, `2:3`, `4:3`, `3:4`, `16:9`, `9:16`, `21:9`, `auto` |
| `background` | `auto`, `transparent`, `opaque` |
| `n` | 1–10 |
| `output_compression` | 0–100 |
| Provider-specific passthrough | `moderation` |
| `seed`, `input_fidelity`, reference strength, guidance scale | Absent from this endpoint record |

OpenRouter states that an absent capability key is unsupported by the endpoint. Therefore **seed locking is unavailable on the inspected Sunburst route**; a generic API field or support on a different model does not change that. `input_references` transports reference images; it is not an identity-strength control. [S2]

The generic OpenRouter guide currently lists fewer quality values than the Sunburst-specific endpoint. Resolve this documentation mismatch using the selected endpoint's capability record and validate the actual request behavior. Do not extrapolate another provider's parameters to Sunburst. [S1, S2]

OpenAI publishes `gpt-image-2.5-sunburst-2026-09-08` as a dated snapshot. Prefer it when the selected route actually exposes it. Native availability does not prove OpenRouter accepts the same identifier; do not invent an OpenRouter snapshot slug. If the alias cannot be pinned, record that limitation and recheck performance when the serving model changes. [S3]

### What is documented, and what is inferred

OpenAI's prompting guide supports assigning references explicit roles, separating requested changes from preserved attributes, and using narrowly scoped edits. It also warns that higher quality does not guarantee a better result and that repeated edits can drift; compositing is recommended when a region must remain pixel-identical. [S4]

Neither the inspected endpoint nor the cited guidance establishes a public reference-weight knob, special face-crop weighting, or a guaranteed ordering preference among images. Claims about Sunburst's latent architecture, attention layers, token dilution, or Flare's distillation process are not substantiated by the reviewed sources and are omitted.

The safer explanation is behavioral: a full-body image may provide little visible facial detail, and multiple simultaneous transformations can create conflicting requirements. That motivates testing crops and simpler edits without claiming knowledge of proprietary internals.

## 4. Reference architecture and identity governance

### Preserve the original as the identity authority

Maintain an immutable original reference for each customized character state. A theme anchor is a derivative asset, not a new definition of the character.

**Evaluate both anchors and completed scenes against the original customized character.** A scene may resemble a slightly drifted themed anchor while no longer resembling the child's actual buddy. Changing the gate reference to the derived anchor would hide that failure.

The generator may receive different reference combinations in an experiment, but the evaluator's original identity reference, rubric, and preprocessing must remain fixed. Theme-clothing checks can use the themed anchor separately.

### Build a theme anchor once

Create a deliberately simple clothing edit: one character, neutral pose, plain or transparent background, original expression where practical, and a close-fitting spacesuit. Keep the face, hairline, hairstyle silhouette, and recognizable body geometry visible. Avoid a closed helmet, opaque visor, bulky shoulders, or large backpack when they obscure identity evidence.

Require `identity_ok >= 0.85` against the original plus owner approval of likeness and costume. An anchor is not expected to pass scene-specific action checks; those checks apply to completed scenes. Retain failed anchor attempts and their preparation cost rather than reporting only the accepted result.

Cache by **character-state version × theme version × art-direction version**. New hair, clothing-independent accessories, or other child customization must invalidate the corresponding identity package.

### Test the smallest sufficient reference pack

The reports disagree on whether every scene should use only the themed anchor or always include the original. Neither choice has measured superiority. Resolve this with explicit experimental arms:

| Package | Role assignment | Main question |
| --- | --- | --- |
| Original full body | Identity, proportions, canonical style | Current reference baseline |
| Original full body + face crop | Full body supplies build; crop supplies visible face/hair evidence | Does exposing facial detail improve yield? |
| Themed full body alone | Approved identity derivative and theme clothing | Is the simpler single-reference request sufficient? |
| Themed full body + original full body | Theme anchor supplies clothing/pose-independent theme appearance; original supplies underlying identity | Does the original reduce drift or cause casual-clothing leakage? |
| Themed full body + original face crop | Theme anchor supplies overall build/clothing; original crop supplies facial identity | Can two references avoid redundant full bodies? |
| Themed full body + original full body + face crop | Explicit roles for all three | Does a third reference add enough benefit to justify its cost and ambiguity? |

Derive face crops directly from the original bytes where possible. Generating a new face portrait introduces another opportunity for drift; enlarging a crop also cannot recover detail absent from the source. Preserve the full hairstyle and identity-defining ears/accessories in the crop.

Use angle-matched references only if difficult views justify them. Any generated turnaround view must first be approved against the original. Start with separate front/three-quarter/profile images rather than a dense montage, then test a compact sheet only if needed. Additional views, transparent backgrounds, and a particular crop shape are hypotheses, not guaranteed improvements.

TRACE-Bench found anchoring deteriorated as reference images contained more entities. It also separates anchoring from extracting and correctly applying attributes. This supports testing clean, unambiguous evidence, but does not prove that multiple views of one mascot are harmful or that Sunburst benefits from a particular crop arrangement. [S6]

A standalone costume reference remains a useful optional input for **anchor creation** when garment appearance matters. It need not be another input to every scene once an approved themed anchor already specifies that costume.

Every production scene should start from the immutable package. Avoid using the previous worksheet scene as the next scene's character master: that permits accepted deviations to accumulate. This is a workflow recommendation, not a measured Sunburst drift rate.

## 5. Prompt contract and scene composition

Fix the reported concatenation/punctuation defect before comparative testing. Keep identity descriptors and costume/background colors in separate blocks. Ambiguous text can confuse attribute assignment; claims that punctuation produces a particular attention-layer effect are unnecessary and unsupported.

Use a short owner-approved descriptor containing visible identifying traits. Do not invent ratios, fur markings, or catchlight coordinates absent from the reference. Preserve eye design and facial structure while allowing the gaze and expression required by the action. Demanding identical highlights or an unchanged pose while asking for a new action creates avoidable contradictions.

The following is a **proposed template**, illustrated with a three-slot tile action. Adapt the action to the actual lesson; the template is not proof of a pedagogical objective or guaranteed adherence.

```text
DELIVERABLE
One text-free worksheet illustration for children ages 5–8.
Show one learning buddy performing one clear action.

REFERENCE ROLES
Image 1 is the approved themed full-body anchor. It supplies the current
spacesuit and overall character appearance.
Image 2 is the original customized character. It is the identity authority
for face, hair, skin/fur markings, and body proportions. Ignore its casual
clothing. Both images depict the same character; show that character once.
[Optional Image 3 is a crop of the original face and hairstyle. It provides
additional identity detail and does not introduce another character.]

IDENTITY — PRESERVE
Preserve the original character's face shape, eye design and spacing,
nose and mouth design, hairline, hairstyle silhouette, skin/fur colors,
distinctive markings, age, and recognizable head/body/limb proportions.
[Insert the brief owner-approved visible identity descriptor.]
Preserve the canonical illustration style. Do not redesign or age the buddy.

ALLOWED CHANGES
Change the pose, gaze, hand positions, and expression only as needed for
the action. Retain the approved close-fitting spacesuit. Keep the face and
identity-defining hair unobstructed; no closed helmet or bulky padding.

ACTION AND OBJECT STATE
Show a shallow horizontal track with exactly three outlined tile slots.
The middle and right slots each hold one blank ivory square tile.
The left slot is empty. One matching tile sits just outside the left end
of the track, between its starting spot and the empty left slot.
The buddy's fingertip visibly contacts that moving tile and pushes it
toward the empty slot. Exactly three solid tiles exist in the whole image:
two stationary and one moving. Do not draw a duplicate or motion ghost.

MOVEMENT CUE
If arrows are permitted: one simple arrow beside the moving tile points
into the empty slot. Keep its path clear of the hand, tiles, and face.
If arrows are prohibited: use track alignment, hand contact, and two short
motion streaks behind the tile; do not add an arrow.

COMPOSITION
Show the recognizable face, both hands, and the complete track clearly.
Use a plain work surface. Character and action dominate the useful image
area. Do not place decorative objects over the face, hands, or destination.
Background: pale and sparse, with at most two small distant space motifs
near the edges. [For layered rendering, replace this with a transparent
background and no scenery; request transparency through the API too.]

TILE APPEARANCE
All tiles are identical matte ivory classroom cards, with simple outlines.
Every tile is completely blank: no printing, drawings, color coding,
embossing, letters, numerals, or writing-like marks.

HARD CONSTRAINTS
One character. No extra hands, fingers, tiles, or tracks.
No words, letters, numbers, logos, watermarks, captions, pseudo-text,
speech bubbles, signage, or decorative control-panel markings anywhere.
Only the movement cue explicitly allowed above may act as a graphic symbol.
```

Resolve bracketed alternatives before sending the prompt. Render only reference-role statements for images actually supplied. This also corrects a count ambiguity in one source report: **a three-slot track holds two stationary tiles and receives one moving tile**, rather than three stationary tiles plus an additional tile.

### Background separation

If the renderer supports layers, compare a transparent **character + hands + task props** foreground with the sparse-background condition. Composite onto a preapproved background deterministically. Transparency is an advertised Sunburst capability, but improved identity from layering is unmeasured. [S1]

Inspect alpha edges, especially hair, hands, shadows, and tile outlines. Gate the final composite at its actual worksheet crop and scale; a foreground that passes in isolation may become unreadable, occluded, or too small after placement. Include compositing and final verification in latency/cost metrics.

Avoid a rigid, supposedly optimal percentage of canvas coverage. Reserve sufficient foreground space for face recognition and the complete action, then test the composition at the printed/displayed worksheet size.

## 6. Wordless learning-action grammar

Blank manipulatives can depict a motor/spatial procedure. They cannot by themselves identify a target word, assign a particular sound to a tile, or prove that a learner is blending rather than simply arranging objects. Supply the linguistic meaning through the surrounding worksheet, audio, or teaching instructions.

This distinction matters: sound manipulation without letters illustrates phonemic awareness; phonics instruction also involves relationships between sounds and written symbols. A zero-text illustration can support either lesson, but it does not independently supply those relationships. Elkonin-style activities use one counter per spoken phoneme, which is not necessarily one per letter. [S7]

| Intended procedure | Proposed visual action | Limitation |
| --- | --- | --- |
| Slide/group tiles | Fingertip pushes a blank tile along a track into a clear gap | Communicates movement/grouping; the worksheet establishes the sound task. |
| Segment sounds | Counters placed into distinct compartments, or moved apart | A static separated row does not show the act of segmenting. |
| Substitute a sound | One tile visibly removed from a slot, with one replacement nearby | Identical blank tiles do not identify which phoneme changes. |
| Tap each sound | Finger contacts one counter in a small row | A single frame shows one tap; sequence and timing need external support. |
| Blend | One continuous hand sweep along a fixed row of separate counters | Physical adjacency alone is not evidence of spoken blending. |
| Choose/consider | Pencil or finger clearly poised over the intended choice area | Hovering alone may communicate uncertainty rather than the required action. |
| Sort | Object moves toward a clearly distinct container | The sorting rule must be provided elsewhere when objects carry no semantic marks. |

Prefer one decisive action moment initially: clear hand contact, one moving object, an obvious destination, and a small countable set of props. Extra reserve tiles, motion ghosts, and repeated panels add ambiguity and object-count demands; use them only when comprehension improves.

Zero text need not mean zero symbols. Explicitly decide whether simple arrows and motion streaks are allowed, align the gate with that decision, and ban writing-like marks rather than accidentally banning the intended cue.

If one frame is insufficient, test two equal before/after panels with consistent props and a clear left-to-right order. Do not assume that panel continuity or arrows are universally obvious to children. Research on visual narrative comprehension shows developmental and experience-related differences; it does not directly validate this particular worksheet design. [S8]

Run a small formative comprehension study across the 5–8 range. Without worksheet text, ask what is moving and where it should go; observe interpretation of the hand, slot, and direction cue. Then test the complete worksheet with its linguistic context. Evaluate motor comprehension, task comprehension, and character recognition separately. A VLM pass is not a substitute for child usability evidence.

## 7. Variance controls and alternative APIs

### Freeze controllable inputs

Use an explicit quality setting for the primary experiment. `high` is a reasonable starting candidate, not a proven optimum. Test `medium`, `high`, and `xhigh`; add `max` if gains remain plausible and its cost fits the budget. Do not attach invented identity bands or timing guarantees to these settings.

Freeze model/version where possible, provider route, prompt version, reference bytes/order, output dimensions, format, transparency policy, final crop, and gate model/rubric/preprocessing. Log both requested and observed output properties. Keep provider fallback disabled where the actual Images API routing schema supports that configuration; do not copy an unverified chat-routing payload.

Persist exact request payloads, decoded outputs, reference hashes, raw gate responses, billed cost, timing, request identifiers, and failure reasons. Keep application `session_id` or trace data in local telemetry unless the selected endpoint explicitly accepts those fields. Stored output bytes provide durable replay of an artifact; identical seedless requests do not.

### Candidate priorities

The current Artificial Analysis broad editing leaderboard reports the following leading entries. The intervals are its reported 95% Elo intervals, not Luna score uncertainty. [S5]

| Model/configuration | Editing Elo | Product relevance |
| --- | ---: | --- |
| Sunburst `max` | 1183 ± 8 | Strong incumbent; does not establish `high` or `max` mascot yield. |
| Flare `max` | 1163 ± 7 | Broad strength does not overturn the supplied task-specific failures. |
| MAI-Image-2.6 | 1139 ± 8 | Credible multi-reference challenger. |
| Nano Banana 2.1 | 1137 ± 9 | Credible character-consistency challenger. |

MAI and Nano Banana's intervals overlap; their nominal ranks do not establish a meaningful difference on mascot identity. General editing preference also rewards aesthetics and successful edits beyond identity preservation.

| Candidate | Verified capability / evidence | Recommendation |
| --- | --- | --- |
| Sunburst | Inspected OpenRouter endpoint accepts up to 16 references. [S1] | Keep as incumbent; test workflow simplification first. |
| MAI-Image-2.6 | Inspected OpenRouter endpoint accepts up to five references. [S9] | Include in the bounded finalist benchmark. |
| Nano Banana 2.1 | OpenRouter accepts up to 14 references; Google advertises consistency for up to four characters and fidelity for up to ten objects. [S10, S11] | Include as a challenger; character counts are not a required slot partition or an identity guarantee. |
| Ideogram 4.5 Precise Edit | Official documentation describes masks, up to four reference images, and copying untouched pixels exactly. [S12] | Test for localized repair; unchanged pixels can be preserved, but corrected face likeness is still unproven. |
| Recraft V4 Pro | Inspected OpenRouter endpoint accepts one reference. [S13] | Lower priority; test a pre-costumed anchor if style/cost justify it. Do not infer poor identity solely from its reference limit. |
| Specialized consistent-character APIs | No repeatable task-specific evidence established in this review. | Require raw outputs and a controlled evaluation before adoption. |

TRACE-Bench reports Nano Banana **2**, not 2.1, with an Anchor score of 0.7724; its evaluated model table does not include Sunburst. Those scores use another task mix and scoring system, so neither the value nor rank can be translated into the Luna threshold. [S6]

Do not infer a fixed speed advantage from a provider-wide latency dashboard. Measure each contender with the actual reference pack, resolution, task suite, gate, and repair policy. Likewise, compare billed cost per accepted final image rather than isolated token prices.

## 8. Experimental program

### Primary outcomes

For every initial candidate, record:

- **Identity first-pass yield:** fraction with unrounded `identity_ok >= 0.85`.
- **All-check first-pass yield:** fraction passing all seven production checks on attempt one; the primary outcome.
- Identity median, 10th and 25th percentiles, and near-miss share `0.80 <= score < 0.85`.
- Procedure/action pass rates and zero-text violations, reported separately.
- Candidate and completed-asset latency p50/p95, billed cost, failures, and retry exhaustion.
- Owner-audited identity and child comprehension for finalist samples.

Keep the original canonical evaluator reference fixed across arms. Use the same output preprocessing and final worksheet placement. Confirm the gate's actual seven checks from the existing configuration rather than reconstructing their definitions from prose.

### Block 1: prompt and scene simplification

| Arm | References | Prompt change |
| --- | --- | --- |
| A | Current original full body | Current prompt, at the experiment's explicit fixed quality |
| B | Same as A | Correct formatting and add identity/change/blank-surface contracts |
| C | Same as A | B plus sparse, procedure-first composition |

Retain the historical production baseline if it uses `auto`, but label it separately: A estimates prompt differences at matched quality, not the full difference from historical production. Screen about **30 outputs per arm**, balanced across character × scene specifications.

### Block 2: reference strategy

Use C's prompt/composition as the common base and compare:

| Arm | Change from C |
| --- | --- |
| D | Original full body plus original face crop |
| E | Approved themed full body alone; wardrobe redesign removed from the scene request |
| F | Approved themed full body plus original full body |
| G | Approved themed full body plus original face crop |
| H, optional | F plus original face crop |

Start with roughly **30 outputs per new arm** and reuse C as the control only if runs are close enough in time and serving conditions remain comparable. Include concurrent control runs otherwise. This is a staged screen, not a full factorial or a guarantee of statistical significance.

If removing actual background clutter from the reference is relevant, compare the unaltered source and an isolated version separately. If the source is already isolated, do not add a redundant arm. Advance angle-matched views only for documented difficult poses. Test transparent foreground compositing against the winning sparse-background condition in a separate block.

For anchor arms, record all preparation attempts and use the same approved themed anchor for the same character state across applicable arms. Do not handpick easy characters or regenerate anchors selectively after viewing scene outcomes.

### Block 3: quality and model challengers

First sweep supported quality settings on the winning Sunburst strategy. Then compare the resulting Sunburst configuration with MAI-Image-2.6 and Nano Banana 2.1 using equivalent scene requirements and reference roles. Respect each endpoint's limits; do not force unsupported quality or transparency parameters onto contenders.

This sequential design saves budget but can miss quality × reference interactions. If two strategies are close, run a small cross-check at another quality setting before choosing. Compare any model-specific optimized prompt in a separately labeled arm rather than silently changing the requirements.

### Confirmation and decision criteria

Use fresh generations and an independent confirmation suite for the best two configurations. **100–200 outputs per finalist** can confirm large improvements; **roughly 400 or more per arm** may be needed for a reliable decision about an uplift around ten percentage points, depending on baseline and clustering. These are planning ranges, not a power calculation for this dataset.

For independent observations near a 50% pass rate, approximate individual-rate 95% margins are ±10 points at n=100 and ±7 at n=200. Repeated samples from the same character/scene can be correlated; nominal sample size may overstate precision.

Randomize and interleave conditions over time. Balance across actual procedure types, difficult poses, and materially different customization states. Without a usable seed, pairing is at the **character × scene specification** level, not identical random noise.

Use Wilson intervals for descriptive rates and stratified/cluster-aware bootstrap comparisons or an appropriate mixed-effects analysis for treatment differences. Do not interpret overlapping single-arm intervals as a definitive test of the difference. Report uncertainty and the full failure mix.

Predeclare a practical success target, for example **at least +10 percentage points in all-check first-pass yield**, with no material procedure/text regression and acceptable completed-asset latency/cost. This is a proposed business criterion; choose the actual target and regression tolerances before running confirmation.

Blindly audit outputs around 0.80–0.90 and a random sample elsewhere. A strategy can raise the gate score through face size or frontal presentation without improving the child's recognition or the instruction. Freeze Luna model/version, rubric, scoring precision, and owner calibration throughout the comparison.

Tag failures: face geometry; hair/markings; body proportions; costume leakage; obscured identity; pose/contact; ambiguous procedure; glyphs; clutter; count errors; crop/alpha/compositing; and API failure. Use the taxonomy to choose subsequent experiments rather than adding every technique at once.

## 9. Accepted-image economics and bounded retries

Let `p` be the **whole-gate** acceptance probability per candidate, `t` its mean generation-plus-verification time, and `c` its mean billed cost including verification.

For identically distributed independent attempts, unlimited sequential retries, and positive `p`:

```text
Expected attempts to acceptance = 1 / p
Expected time to acceptance = t / p
Expected candidate cost to acceptance = c / p
```

These are planning approximations for production, where hard scenes, changing retries, rate limits, and correlations violate the simple assumptions. Do not divide a p95 candidate latency by yield and call it a p95 delivery estimate.

For a maximum of `K` independent attempts under the same assumptions:

```text
Probability of delivering an accepted image = 1 - (1 - p)^K
Expected attempts spent per requested image = [1 - (1 - p)^K] / p
```

For illustration only, if generation plus verification takes 28 seconds, increasing yield from 25% to 50% reduces the unlimited-retry expected time from 112 to 56 seconds. With three attempts allowed, completion rises from about 58% to 88%; neither configuration guarantees delivery. These numbers are hypothetical, not measured product performance.

Measure real pipeline outcomes directly: total spend divided by accepted deliverables, terminal failures, and elapsed delivery time across all requests. Include failed attempts, timeout/backoff overhead, repair, compositing, and an amortized share of anchor preparation. Report cold customization-to-ready latency separately from cached-anchor scene generation.

## 10. Repair policy and production rollout

Repair is a separate recovery intervention; it does not improve literal attempt-one yield. Use it when the instructional action and composition pass and identity is the principal remaining defect.

Provide the candidate as the edit source and the original canonical identity reference, optionally the themed anchor for clothing. Request one narrowly defined identity correction while preserving successful scene elements. A face repair may also require hair or head-outline edits; substantial body-proportion errors can require changing pose and are poorer repair candidates.

```text
Correct only the buddy's identity to match the original canonical character:
face shape, facial design, hair silhouette/markings, and recognizable proportions.
Keep the successful learning action, hand contact, tile counts, destination,
camera, spacesuit, blank surfaces, and composition unchanged.
Do not add text or decorative marks.
```

Use one repair attempt as an initial budget policy, then rerender or return the existing product fallback if it fails. One is a practical starting limit, not a vendor guarantee. Re-run **all seven checks** after repair, because corrected likeness can disturb hands, props, blankness, or layout.

If a successful action region must remain pixel-identical, use the endpoint's documented masking/preservation behavior or composite the approved repaired region over the original. Confirm mask polarity and seam quality for the selected API. Prompt-only preservation is not a guarantee. [S4, S12]

### Rollout checklist

- [ ] Recover baseline artifacts and full gate definitions; fix prompt compilation defects.
- [ ] Freeze original identity assets, descriptors, reference hashes, and evaluator inputs.
- [ ] Approve themed anchors against originals; record preparation failures and cost.
- [ ] Run staged prompt/reference screening with explicit quality and randomized scheduling.
- [ ] Confirm the best configurations on fresh representative generations.
- [ ] Validate final-scale child comprehension and owner-audited likeness.
- [ ] Sweep quality; evaluate challengers against the improved incumbent.
- [ ] Evaluate repair as its own policy, including downstream regressions and total cost.
- [ ] Store final outputs and provenance; deploy gradually with an available rollback configuration.

## 11. Resolution of source-report conflicts

| Conflicting or unsupported claim | Consolidated resolution |
| --- | --- |
| Sunburst seeds are effective vs no seed is documented | The inspected endpoint omits `seed`; seed locking is unavailable on that route. [S1, S2] |
| Face/anatomy/costume decomposition must replace every single reference | Multi-reference capability is verified; improved mascot yield is not. Test against single-reference and themed-anchor conditions. |
| Always use themed anchor alone vs always add original | Neither is established. Compare both, keep the original fixed as evaluation authority, and define clothing roles explicitly. |
| `high` guarantees roughly 0.85–0.91 identity; lower quality causes fixed drift | Unsupported ranges removed. Quality must be measured on this workload. |
| Nano Banana 2.1 is the only verified replacement, with about half the latency | Unsupported superiority and speed guarantees removed; MAI is another accessible challenger. |
| Precise architecture and attention mechanisms explain observed errors | Unsupported internal mechanisms replaced with observable conflicts and testable hypotheses. |
| Exact canvas percentages or a three-reference pack are optimal | Treat as adjustable composition/reference choices, not established optima. |
| Nano Banana 2's TRACE score establishes 2.1 performance or predicts Luna | Different version, workload, and scoring system; no such inference is valid. |
| All symbols must be banned while an arrow communicates motion | Define allowed movement cues separately from text and writing-like marks. |
| Static separated tiles communicate segmentation; blanks communicate a word | Show an action/state transition and provide linguistic meaning outside the illustration. |
| A themed anchor passing its own likeness test validates later scenes | Anchors and scenes must retain comparison to the original customized character. |
| `session_id`, seed, and trace fields belong in every API request | Use only endpoint-supported request fields; retain application trace data in telemetry. |
| One combined variant isolates prompt, reference, and quality benefits | Confounded variants cannot attribute effects; separate intervention blocks and confirm finalists. |
| Narrow repair raises first-pass acceptance | Report first-pass yield and repaired delivery yield independently. |

## Sources and verification notes

Bracketed source IDs below replace the supplied reports' missing bibliographies, duplicated citations, and conversation-specific citation tokens. URLs are portable in this Markdown document. Endpoint records and rankings are time-sensitive; the statements above reflect inspection on October 9, 2026. Product observations remain attributed to the supplied reports because raw test artifacts were not available.

- **[S1] OpenRouter — live Sunburst endpoint capabilities.** [Endpoint record](https://openrouter.ai/api/v1/images/models/openai/gpt-image-2.5-sunburst/endpoints). Inspected via public HTTP and web retrieval; establishes reference count, quality values, background options, and omitted controls.
- **[S2] OpenRouter — dedicated Images API guide.** [Documentation](https://openrouter.ai/docs/guides/overview/multimodal/image-generation). Establishes endpoint-specific capability discovery and that absent capability keys are unsupported. Its generic quality example is less complete than S1.
- **[S3] OpenAI — Sunburst model documentation.** [Model page](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst). Establishes the dated native model identifier; does not establish its availability on another provider route.
- **[S4] OpenAI — Image prompting guide.** [Guide](https://developers.openai.com/api/docs/guides/image-prompting). Supports reference roles, change/preserve boundaries, scoped edits, workload-specific quality evaluation, and compositing for exact preservation. The proposed workflow and prompt are adaptations, not measured results from this guide.
- **[S5] Artificial Analysis — AA-Image-Editing v2.0.** [Leaderboard](https://artificialanalysis.ai/image/leaderboard/editing). Source of broad editing Elo values and intervals; evaluates pairwise human preference rather than this product's identity rubric.
- **[S6] Wang et al. — TRACE-Bench: Decomposing and Diagnosing Multi-Reference Image Generation.** [Paper abstract](https://arxiv.org/abs/2608.16765); [authors' project page and results](https://amuseum-whr.github.io/TraceBench/). Approximately 1,600 cases across nine models. The inspected results include Nano Banana 2 and GPT-Image-1.5, not Sunburst or Nano Banana 2.1. The project table lists Disentangle 0.7384 and Apply 0.7989 for Nano Banana 2; the abstract's compressed attribute-fidelity wording should not be treated as another directly comparable identity metric.
- **[S7] Reading Rockets — Elkonin Boxes.** [Instructional guidance](https://www.readingrockets.org/classroom/classroom-strategies/elkonin-boxes). Supports one token/box per phoneme. This is practice guidance, not a trial validating the proposed generated illustration.
- **[S8] Cohn et al. — (Pea)nuts and bolts of visual narrative: Structure and meaning in sequential image comprehension** (2012). [Original study](https://doi.org/10.1016/j.cogpsych.2012.01.003). Also **Fivush and Mandler — Developmental changes in the understanding of temporal sequence** (1985), [study record](https://pubmed.ncbi.nlm.nih.gov/4075867/). These motivate attention to sequence comprehension and developmental differences; no claim is made that they validate this mascot, arrows, or a universal age cutoff.
- **[S9] OpenRouter — MAI-Image-2.6.** [Model page](https://openrouter.ai/microsoft/mai-image-2.6); [live endpoint record](https://openrouter.ai/api/v1/images/models/microsoft/mai-image-2.6/endpoints). Endpoint inspected via public HTTP; up to five references.
- **[S10] OpenRouter — Nano Banana 2.1.** [Model page](https://openrouter.ai/google/gemini-nano-banana-2.1); [live endpoint record](https://openrouter.ai/api/v1/images/models/google/gemini-nano-banana-2.1/endpoints). Endpoint inspected via public HTTP; up to 14 references. Browser retrieval of the JSON failed, but direct HTTP returned the capability record.
- **[S11] Google — Gemini Nano Banana 2.1.** [Official model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1). Source of advertised four-character/ten-object multi-image capabilities; no Luna performance guarantee.
- **[S12] Ideogram — API overview.** [Official documentation](https://developer.ideogram.ai/ideogram-api/api-overview). Source of Precise Edit masking, reference-image, and untouched-pixel preservation claims; corrected-region identity remains task-specific.
- **[S13] OpenRouter — Recraft V4 Pro live endpoint record.** [Endpoint](https://openrouter.ai/api/v1/images/models/recraft/recraft-v4-pro/endpoints). Inspected via public HTTP; one reference on this route. This limit does not imply a universal limit on every Recraft product or prove an architectural identity weakness.

**Outstanding evidence needed:** original ablation artifacts and sample counts; full baseline score/yield/latency distributions; exact gate definitions and calibration examples; new generation results for the proposed reference and composition arms; and comprehension evidence from the target children.
