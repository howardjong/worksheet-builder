# Character-consistency screen: 4-arm prompt x reference factorial — findings

Date: 2026-10-09. Commit: 0794cee (tree 61366ba), test branch only.
Runner: `experiments/character_consistency.py` (new). Manifest and prompts
snapshotted before inference; 16 trials, seed 20261009, concurrency 3.

## Design

| Arm | Prompt | Generation references | Gate reference |
|-----|--------|----------------------|----------------|
| A | Exact production `scene_prompt()` | Original full-body | Immutable original |
| B | Experiment-only structured prompt | Original full-body | Immutable original |
| C | Exact production `scene_prompt()` | Original full-body + face crop | Immutable original |
| D | Experiment-only structured prompt | Original full-body + face crop | Immutable original |

One authorized character state x two procedures (word building, blank-choice
considering) x two fresh repetitions = 16 images. Second customization state
unavailable; population explicitly narrowed. Sunburst, quality=auto,
background=opaque, 16:9, provider fallback disabled. Luna v5 gate, thresholds
unchanged (identity .85, task .35, action .35, outfit .85, safety .95,
no-text .95, answer-free .95). No retries or model fallback in the screen.

Face crop: fractional rect (0.33, 0.0, 0.66, 0.42) of original bytes, no
generative retouching; crop sha 75efedebd1d6c2e6 (full hash in manifest).

## Results by arm (all-check first-pass)

| Arm | Pass | Identity range | Identity median |
|-----|------|---------------|-----------------|
| A | 0/4 | 0.77–0.81 | 0.79 |
| B | 0/4 | 0.64–0.73 | 0.69 |
| C | **1/4** | 0.79–0.86 | 0.81 |
| D | 0/4 | 0.45–0.76 | 0.61 |

The single pass: C_blank_choices_r1 (identity 0.86, task 0.81, action 0.95,
all other checks 1.0).

## Interaction

Pass-rate interaction (D−B) − (C−A) = (0−0) − (0.25−0) = **−0.25**.
The face crop helps under the current prompt (+1 pass, median identity
0.79→0.81) and does not help under the structured bundle. Descriptive only
(n=4/arm); not a statistical establishment.

## Directional read (reduced screen; 8-observation rule not applied)

- **Shortlist: arm C** (current prompt + original + face crop). Only arm with
  a pass; best identity distribution; no new safety/text/answer leakage.
- **Structured bundle (B/D) directionally worse on identity** than the current
  prompt under both reference packs. D additionally produced a no-helmet,
  pencil-touching failure (identity 0.59, outfit 0.0) — the "close-fitting
  spacesuit / pale sparse background" bundle did not survive the gate's theme
  and action checks. This judges the bundle as implemented, not the template
  concept in the abstract.
- Identity remains the binding check: 15/16 trials failed it; all other
  checks passed on 14/16 or better.

## Latency (successful vs failed, generation + gate)

- Approved (n=1): gen 23.6s, gate 3.0s.
- Failed (n=15): gen mean 23.1s (range 19.1–30.6s), gate mean 2.9s.
- No meaningful latency difference between outcomes; generation dominates.

## Cost and telemetry note

Per-trial cost was not recorded: the runner's ThreadPoolExecutor did not
propagate the telemetry/limits ContextVars to worker threads, so
`inference_calls.jsonl` is empty and the $1.95 process cap was not enforced
in-thread. Fixed by submitting via `contextvars.copy_context().run`
(committed). Actual is estimated ~$0.23 (16 x ~$0.0137 + 16 x ~$0.0004);
**conservatively reserved at $0.50** pending a measured rerun. No overrun
occurred; all 16 trials completed within the 900s deadline.

## Owner-review candidates (private artifacts, not in git)

- `C_blank_choices_r1.png` — the sole pass; likeness + procedure usefulness.
- `D_blank_choices_r1.png` — structured-bundle failure mode (no helmet,
  pencil touches card); useful contrast for the prompt decision.
- `B_word_building_r1.png` — structured prompt, middling identity (0.70).

## Proposed next block (not auto-run)

Per the handoff's conditional rules: owner review of the C shortlist comes
before integration and any full-pipeline trial. If C is accepted, the next
bounded block is a quality sweep (medium vs high) on the fixed C reference
pack, ~16 trials / ~$0.25, then integration as a test-branch option and one
fresh lesson-100 pipeline trial (~$0.60 ceiling).
