# Next-Move Decision — Fable 5 analysis (2026-06-12)

Input: 3 A/B battery runs + 2 TDD fixes (grader-visibility, planner-coverage); gate still reads 1/3; IMG_0005 swung 0.91→0.61 on the same image. Question: what next, and is the battery even a sound gate?

## Verdict
**Fix the gate's measurement, don't replace it or trust it as-is.** Do the real quality fixes now (A + the small worked-example bug), then fix how the gate measures (freeze extraction + median-of-N judging + two consecutive passing runs), then a small human precision check before flipping the default. The 0.91→0.61 swing is **NOT judge noise — it is the non-deterministic vision step injecting the worksheet's header text into the plan** (garbled concept → leaked into the child's self-check line). That is a real product bug, deterministic and cheap to fix, currently mis-billed as "judge variance."

## Why the battery (as defined) is not yet a sound gate
1. **Wrong composite:** an end-to-end cell conflates vision extraction (non-deterministic) + planner quality + judge behaviour. IMG_0005 proves a cell can fail for reasons unrelated to the planner.
2. **Underpowered + noisy:** 1 sample/cell, 3 cells, binary outcomes, demonstrated flips → per-cell pass probability is intermediate, so a single 2-of-3 run can false-fail AND false-pass.
3. **Untrustworthy scale near the bar:** the 0.70–0.90 dead zone + cusp cells at 0.66–0.68 make the judge effectively ternary (bad / cusp / great), and 0.70 sits on the cusp boundary.

Minimum changes to make pass/fail mean something (**"B′"**): (a) run vision ONCE per image, cache the skill-model artifact, and have all battery cells consume the same frozen input; (b) judge each plan 3–5× and take the median; (c) require the gate to pass on two consecutive battery runs.

## Ranked moves (impact-per-effort toward a DEFENSIBLE decision, not just a green gate)
1. **A — concept sanitization.** Real quality fix (garbage text was headed for a printed worksheet). Deterministic, small, TDD-able; likely recovers IMG_0005; removes the one demonstrated source of run-to-run flips.
2. **D-small — the worked-example bug** ("Example: make cute. Change u to a. Write cate? No."). Real content defect; also a warning sign about approve-precision. Do it with A.
3. **B′ — gate protocol fix** (frozen extraction + median-of-N + two consecutive runs). Fixes the measurement, which is required before any pass/fail is defensible. (Plain "judge N×" alone would NOT have caught IMG_0005, because that was upstream.)
4. **C-small — human precision check** on ~15–20 plans (the approved ~0.86–0.91 plans + the 0.62–0.70 cusp plans already in logs), plus a cross-vendor Gemini judge pass on the same cells (already wired via `_call_gemini`'s `model` param). The defensibility step before flipping the default. Full 60–100-example calibration only if this finds problems.
5. **D-large — dense-story full-passage coverage.** Genuinely hard, biggest effort, and NOT required for promotion: a rejected IMG_0004 plan falls back to the deterministic engine (safe; independent validators pass). Ship as a known limitation; fix post-promotion. (Partly judge taste — the deterministic content-coverage validator already passes.)

Quality vs measurement: A + D-small fix real quality; B′ + C-small fix the measurement; D-large is mixed.

## Sequencing with checkpoints
1. **A + D-small** (deterministic, TDD). Checkpoint: tests green; the garbled-concept string provably cannot reach prompts or self-check lines.
2. **B′** (pin extraction for battery, median-of-N judging, gate = 2 consecutive passing runs). Checkpoint: battery runs twice; per-cell medians stable across both (no flips). If IMG_0005 still flips with frozen extraction → judge noise is bigger than the data shows → escalate to full C.
3. **Evaluate the gate honestly.** Expected: IMG_0003 + IMG_0005 pass reliably → 2/3 green; IMG_0004 rejects → deterministic fallback (safe). Checkpoint: passes both runs → proceed; passes 1 of 2 → run a third; persistent instability → stop.
4. **C-small before flipping anything:** human-review approved + cusp plans; run the Gemini second-opinion judge. Pass → flip default (Tasks 13–14). **Hold Task 15 (delete old path)** until 1–2 weeks of production telemetry on planner outcomes.
5. **Post-promotion:** D-large (dense-story coverage) and vision-extraction robustness as their own tracked workstreams.

## The one metric to watch
**Judge-approve precision vs human judgment** — of the plans the judge approves (plus the 0.62–0.70 cusp plans), what fraction does a human consider shippable? Rejection is safe (fallback); approval ships to a child, so approve-precision is the consequential metric. **Stop rule:** if ≥~20% of judge-approved plans have real defects (worked-example-bug class), build the full calibration set before any promotion, regardless of battery results. If approved plans are consistently good, promotion is defensible even with IMG_0004 rejecting.

## Self-judging risk
Real in principle, but the data shows the OPPOSITE of the classic failure: this self-judge REJECTS ~96% of same-family output while independent deterministic validators pass it — so the threats are noise/miscalibration, not sycophancy. Mitigations in order: the deterministic validators (free, already disagreeing informatively); the Gemini cross-vendor second opinion (step 4); the human spot-check. Don't swap the gate judge wholesale until cross-vendor agreement is measured.

## Wrong assumptions in the prior framing (flagged)
- "0.91→0.61 demonstrates judge variance" → primarily **vision-step variance**; option B alone would not have prevented it.
- "1/3 cells approved = failure" → rejection falls back safely and the old loop is already demonstrably worse (coverage FAILs, an llm_failure). The promotion question is "is the planner system better and are its approvals trustworthy," not "can 3 images clear an uncalibrated 0.70 in one lucky run."
- "C = pause coding" → false dichotomy; the 15–20-plan human check runs in parallel with steps 1–3 using artifacts already on disk.

## Status
Accepted as the plan of record. Tasks 13–15 of `plans/2026-06-12-planner-simplification-plan.md` stay blocked. Immediate next action: implement A (concept sanitization) + D-small (worked-example bug) with TDD, pending owner go-ahead.
