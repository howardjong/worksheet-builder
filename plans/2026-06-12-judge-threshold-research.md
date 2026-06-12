# Judge Threshold Research — outcome & decision (2026-06-12)

Context: planner-v2 A/B battery fails the promotion gate (1/3 approved). Before deciding whether to lower the judge's 0.70 approval bar, we ran a research pass plus an analysis of our own judge logs.

## Data from our run logs (28 real GPT-5.4 judge calls, 2 battery runs)
- Approval rate at current bar (overall ≥ 0.70, every criterion ≥ 0.50): **1/28 (4%)**.
- **Dead zone:** zero scores land in 0.70–0.90; plans are either < 0.70 or ~0.91. The numeric scale is low-resolution / poorly anchored — a 0.68-vs-0.70 distinction is not trustworthy.
- **Coverage is the binding constraint:** lowest sub-score among the 27 rejects was content_coverage 16×, adhd 9×, concept 2×. content_coverage distribution: min 0.10 / median 0.36 / max 1.00 (lowest and widest of all criteria).
- **Lowering the bar barely helps:** with the per-criterion 0.50 floor kept, 0.70→1 approve, 0.67→2, 0.65→3, 0.60→3. The coverage floor binds before the overall bar does.
- Post-visibility-fix planner attempts cluster at 0.66–0.68 (coverage-limited 0.45–0.62), plus one clean 0.91.

## Recommendation (accepted direction)
Do **not** lower 0.70 as the primary fix. Keep the current gate as a conservative blocker. Before promoting planner-v2:
1. **Fix planner coverage first (best next move).** Prompt/planner changes that force individual practice of every source word, word chain, and passage-critical sentence — instead of bundling them into long list items. The two blocked cells are coverage-limited with ADHD now healthy, so this targets real quality, not score-gaming.
2. **(Follow-up) Restructure approval into per-criterion gates** (skill-alignment pass, ADHD pass, no safety/developmental fail, coverage sufficient); keep overall_score for logging/trend only.
3. **(Follow-up) Add an uncertainty band** ~0.62–0.70: "judge unsure" → rerun judge / lean on deterministic validators / fall back, rather than auto-ship.
4. **Lower/relabel the threshold ONLY after a human calibration set** confirms humans approve most 0.66–0.68 worksheets.

## Coverage standard (resolves "is the judge over-strict?")
K-3 reading intervention does NOT require every visible source item on one worksheet (IES WWC Foundational Skills). For this app's skill-preserving contract, "coverage sufficient" = all target skill PATTERNS and critical source items (word chains, key sentences) are represented enough to practice. The judge is over-strict if it demands every visible item, but under-strict if it lets target chains/sentences disappear. The planner-coverage fix should target the critical-items definition, and the judge's coverage rubric should be rewritten to match it.

## Next experiment (before any threshold change)
Calibration battery on existing + new planner logs: reach 60–100 examples (oversample 0.55–0.75); judge each 5× at production settings to measure variance/flip-rate near 0.62–0.70; human-label 30–40 then 100+ (ship/fallback, coverage sufficient/partial/insufficient, skill/ADHD/safety). Metrics: judge–human precision/recall, Cohen's kappa, per-criterion confusion, flip rate. Decision rule: humans approve most 0.66–0.68 + low judge variance → add a borderline-pass/lower rule; humans agree coverage is partial → the planner-coverage fix is the real fix.

## Sources
- OpenAI evaluation best practices — calibrate automated metrics against human evals; prefer pass/fail or pairwise.
- "Trust or Escalate: LLM Judges with Provable Guarantees for Human Agreement" — selective evaluation, calibrated thresholds, abstention/fallback under low confidence.
- "LLM Evaluators Recognize and Favor Their Own Generations" — same-family judging inflates self-preference, correlated blind spots (we self-judge: GPT-5.4 judging GPT-5.4).
- "A Survey on LLM-as-a-Judge" — pointwise vs pairwise, evaluator biases.
- IES WWC Foundational Skills K-3 — decode words, analyze word parts, read connected text daily (anchors the coverage standard).

## Status
Tasks 13–15 of `plans/2026-06-12-planner-simplification-plan.md` remain blocked. Next action pending owner pick: implement the planner-coverage fix (TDD) and re-run the battery.
