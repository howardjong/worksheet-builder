# Planner Coverage Architecture Research Report (2026-06-13)

## Executive Decision

**Do not restart the planner from scratch.** The current planner work is directionally right and should be evolved through a targeted contract-layer refactor: add a deterministic `CoverageLedger -> SlotPack -> SlotAuthor` architecture around the existing `WORKSHEET_PLANNER_V2` path.

The current system is not suffering from an unsalvageable planner concept. It is suffering from a missing non-negotiable contract: "all extracted source content must become accountable individual practice." Today that requirement is expressed mostly in prompt prose and checked after the fact with deterministic heuristics plus an LLM judge. The research and the repo evidence both point to the same conclusion: move coverage out of the probabilistic planner's memory and into deterministic data structures, while preserving LLM freedom for activity design, child-facing wording, worked examples, and theme adaptation.

Recommended top pick:

```text
Frozen LiteracySkillModel
  -> deterministic CoverageLedger
  -> deterministic ADHD SlotPack
  -> LLM SlotAuthor
  -> deterministic coverage/answer/cap validators
  -> LLM pedagogy judge
  -> renderer
```

This should be implemented as an evolution of `adapt/llm_planner.py`, not as a clean-room planner rewrite.

## What We Were Trying To Decide

The measured problem was not hypothetical:

- Vision extraction was frozen per image.
- Judge noise was reduced with median-of-3 judging.
- The same frozen source still produced approve/reject flips.
- Planner output ranged from roughly `0.34` to `0.76` on `content_coverage`.
- Overall-score swings of `0.14-0.18` were larger than judge within-run spread.

Diagnosis: the dominant instability is planner-generation variance in how completely dense source material is covered. The planner sometimes covers all words, chains, sentences, and passages; other times it silently drops important content.

The decision question became:

1. Should we keep iterating on the current planner?
2. Should we start over from scratch for the planner layer?
3. How do we guarantee source coverage without making worksheets dull, rigid, or over-templated?

## Current Repo Evidence

### The old planner path had real architectural holes

`adapt/llm_orchestrator.py` implements a legacy loop:

```text
Gemini plans -> GPT judges
  -> if rejected, Gemini retries
  -> if rejected again, GPT takes over planning
  -> GPT takeover is not self-judged
```

The simplification plan records that observed live runs ended in `gpt_takeover_unjudged`, with weak Gemini coverage and GPT output shipping without a verdict. That is a product-risk hole, not just an eval annoyance.

Relevant local evidence:

- `adapt/llm_orchestrator.py`
- `plans/2026-06-12-planner-simplification-plan.md`

### The new planner path is a better chassis

`adapt/llm_planner.py` already moves in the right direction:

- One strong planning call through a provider chain.
- Full source items and canonical UFLI corpus context.
- The model authors actual item text/options/answers.
- One regeneration with feedback.
- Deterministic fallback after repeated rejection.
- Median judge support via `WORKSHEET_JUDGE_SAMPLES`.
- Section-cap enforcement through `adapt/section_cap.py`.

That is not a dead-end architecture. It is close to the right shape, but it still asks the model to satisfy coverage mostly through natural-language instructions:

> Preserve ALL source content as INDIVIDUAL practice...

That instruction is necessary but not sufficient. For dense lessons, the source-item obligation should be represented as data, not hope.

Relevant local evidence:

- `adapt/llm_planner.py`
- `adapt/engine.py`
- `adapt/section_cap.py`
- `validate/content_coverage.py`
- `plans/2026-06-12-planner-simplification-plan.md`

### The current gate is useful but not yet decision-grade

`plans/2026-06-12-next-move-fable5.md` concluded the battery was not yet a sound promotion gate because it conflated:

- vision extraction variance,
- planner variance,
- judge behavior.

It also found a concrete quality defect: garbled concept text could leak into child-facing self-check text, and a worked-example bug could show a wrong attempt. These are fixable product defects, not proof that the planner direction is doomed.

The important distinction from that plan still holds:

- Rejection is safe because it falls back.
- Approval ships to a child.
- Therefore the key metric is **judge approve-precision vs human judgment**, not average judge score.

Relevant local evidence:

- `plans/2026-06-12-next-move-fable5.md`
- `plans/2026-06-12-gate-protocol-fix-Bprime.md`
- `plans/2026-06-12-judge-threshold-research.md`

## External Research Findings

### Structured output guarantees schema shape, not semantic completeness

OpenAI Structured Outputs are useful because they can force model responses to match a supplied JSON Schema. The official docs distinguish this from JSON mode: JSON mode ensures valid JSON, while Structured Outputs enforce schema adherence. The docs also warn that structured outputs can still contain mistakes, and that schema support has limits such as object/property constraints and unsupported JSON Schema keywords.

Implication for Worksheet Builder:

- Structured output can require fields like `source_item_id`, `activity_type`, `items`, and `answer`.
- It cannot guarantee that the model made a pedagogically sound item.
- It cannot by itself prove that every source item was covered unless the required source IDs are generated deterministically and checked after output.

Source:

- OpenAI, "Structured model outputs," official API docs, fetched 2026-06-13: https://developers.openai.com/api/docs/guides/structured-outputs

### Constrained decoding can improve validity while harming semantic quality

The 2026 paper "Draft-Conditioned Constrained Decoding for Structured Generation in LLMs" argues that token-level constraints can distort generation when the model has low probability mass on valid continuations. Their proposed approach separates semantic drafting from structural enforcement, improving strict structured accuracy by up to `+24` percentage points in reported benchmarks.

Implication for Worksheet Builder:

- Do not make the LLM solve pedagogy while squeezed through an overly rigid final schema.
- Let deterministic code create the coverage skeleton.
- Let the model author high-quality surface content within slots.
- Validate structure after the model has had enough room to produce good language.

Source:

- Chapparapu et al., "Draft-Conditioned Constrained Decoding for Structured Generation in LLMs," arXiv, submitted 2026-02-08: https://arxiv.org/abs/2603.03305

### Recent structured-output work still shows a reliability gap

"When Correct Isn't Usable" studies the gap between task correctness and strict output usability. It reports that naive or reference prompting can produce task-correct but format-invalid outputs, while constrained decoding can incur `3.6x-8.2x` latency overhead and sometimes degrade task performance. The paper also reports prompt-optimization stability depends heavily on meta-agent capability.

Implication for Worksheet Builder:

- The planner should not depend on prompt wording alone for coverage correctness.
- The system needs deterministic validators and retry/fallback behavior.
- The schema should be just strict enough to make the output auditable.

Source:

- Galeone, "When Correct Isn't Usable: Improving Structured Output Reliability in Small Language Models," arXiv, submitted 2026-05-04: https://arxiv.org/abs/2605.02363

### Agentic loops are improving but do not eliminate variance

Recent 2026 agent reliability work is directly relevant. "How Consistent Are LLM Agents?" measures repeated identical invocations of tool-calling agents and finds "structural consistency, parametric variance": tool sequence similarity averaged `0.87`, while argument consistency averaged `0.69`. Ambiguous tasks reduced argument consistency by `28%`, and `60%` of divergence originated in the first two pipeline steps.

Implication for Worksheet Builder:

- Agent loops can help inspect, repair, and trace behavior.
- They should not own the source-coverage guarantee.
- Reducing ambiguity in the task contract is a stronger lever than adding another agent persona.

Source:

- Yagubyan, "How Consistent Are LLM Agents? Measuring Behavioral Reproducibility in Multi-Step Tool-Calling Pipelines," arXiv, April 2026: https://arxiv.org/abs/2605.28840

"Towards a Science of AI Agent Reliability" argues that single success metrics hide operational flaws, and proposes decomposing reliability into consistency, robustness, predictability, and safety. The authors report that recent capability gains have yielded only small improvements in reliability.

Implication for Worksheet Builder:

- A single judge score should not be the release gate.
- The planner should be evaluated on separate dimensions: deterministic coverage, ADHD caps, pedagogy, visual/engagement quality, and approve-precision.

Source:

- Rabanser et al., "Towards a Science of AI Agent Reliability," accepted at ICML 2026, arXiv version updated 2026-06-02: https://arxiv.org/abs/2602.16666

"ReliabilityBench" evaluates LLM agents under repeated execution, semantic perturbation, and tool/API faults. It reports that perturbations reduced success from `96.9%` to `88.1%`, and that ReAct was more robust than Reflexion under combined stress in their benchmark.

Implication for Worksheet Builder:

- Reflexion-style self-repair is not guaranteed to reduce variance.
- A deterministic coverage ledger is a simpler, stronger reliability mechanism for this domain.

Source:

- Gupta et al., "ReliabilityBench: Evaluating LLM Agent Reliability Under Production-Like Stress Conditions," arXiv, submitted 2026-01-03: https://arxiv.org/abs/2601.06112

### LLM-as-judge needs calibration, especially for long-form output

"Benchmarking LLM-as-a-Judge for Long-Form Output Evaluation" reports a substantial reliability gap for long-form judgments: rubrics and references help, but are not always sufficient.

Implication for Worksheet Builder:

- The judge can be a useful gate, but it should not waive deterministic coverage failures.
- The judge should be calibrated against human review for approve-precision.

Source:

- Chen et al., "Benchmarking LLM-as-a-Judge for Long-Form Output Evaluation," arXiv, submitted 2026-06-01: https://arxiv.org/abs/2606.01629

"Grading Scale Impact on LLM-as-a-Judge" finds that grading scale changes human-LLM agreement, with 0-5 scales producing the strongest aggregate alignment in their study. It also warns that pooled reliability can hide benchmark heterogeneity.

Implication for Worksheet Builder:

- Scalar thresholds like `overall >= 0.70` are fragile near the boundary.
- Prefer pass/fail labels with defect categories for release gates, plus scalar scores for diagnostics.
- Track subgroups: dense word work, word chains, decodable passages, Roll and Read, sentence practice.

Source:

- Li et al., "Grading Scale Impact on LLM-as-a-Judge: Human-LLM Alignment Is Highest on 0-5 Grading Scale," arXiv, submitted 2026-01-06: https://arxiv.org/abs/2601.03444

## Answer To The "Too Constraining" Concern

The proposed architecture is only too constraining if it is implemented as a fixed worksheet template. It should not be.

The deterministic layer should constrain:

- source-item coverage,
- exact spelling and sentence preservation,
- word-chain step accountability,
- answer-key validity,
- ADHD caps,
- print safety,
- no forbidden reward patterns.

The LLM should still control:

- activity framing,
- child-facing instructions,
- examples,
- distractors,
- theme integration,
- narrative/context,
- transitions,
- calm reward/avatar moments,
- choice among approved practice forms.

In other words:

```text
Determinism decides what must be practiced and what cannot break.
The LLM decides how the practice becomes engaging.
```

That preserves the product's ability to create attractive and adaptive worksheets. It also prevents the current failure mode where the model produces something charming but incomplete.

## Recommended Target Architecture

### 1. Deterministic CoverageLedger

Create an internal ledger from `LiteracySkillModel.source_items` and corpus enrichment:

```python
CoverageLedgerEntry:
    source_item_id: str
    source_region_index: int | None
    item_type: Literal[
        "word",
        "word_chain_step",
        "word_chain",
        "sentence",
        "passage",
        "roll_and_read_word",
        "sight_word",
    ]
    exact_text: str
    parent_source_text: str | None
    required_practice_count: int
    allowed_practice_forms: list[str]
    skill_role: str
    priority: Literal["required", "optional_enrichment"]
```

This is the hard contract. The model should not invent or drop ledger entries.

### 2. Deterministic ADHD SlotPack

Pack ledger entries into worksheets and sections before authoring:

```python
PracticeSlot:
    slot_id: str
    worksheet_index: int
    section_index: int
    source_item_ids: list[str]
    activity_family: str
    max_items: int
    required_exact_text: list[str]
```

Rules:

- Split over-cap sections into more mini-worksheets.
- Never drop ledger entries to satisfy caps.
- Keep word chains grouped as build activities.
- Preserve full source sentences.
- Put dense passages into connected reading activities rather than scattering every sentence if that better preserves fluency.

### 3. LLM SlotAuthor

The LLM receives the slot pack, not an open-ended "make 2-3 worksheets" request. It authors:

- section title,
- micro-goal,
- instructions,
- worked example,
- item text,
- answer options,
- correct answers,
- picture prompts if relevant,
- brief rationale.

The output must include the source IDs it used:

```json
{
  "slot_id": "ws1_s2",
  "covered_source_item_ids": ["word_004", "word_005"],
  "items": [...]
}
```

### 4. Deterministic validators

Hard fail if:

- `required_source_item_ids != emitted_source_item_ids`,
- an emitted ID is unknown,
- exact words/sentences drift when preservation is required,
- answer keys are missing or invalid,
- section/item caps are exceeded,
- activity options contain bundled word lists,
- worked examples model wrong answers or non-words.

### 5. LLM pedagogy judge

Judge only what deterministic code cannot:

- clarity,
- age appropriateness,
- ADHD suitability,
- concept alignment,
- flow,
- engagement,
- worked-example usefulness.

The judge cannot override deterministic coverage failure.

## Why Not Start Over

Starting over would make sense if the current planner had bad boundaries, no fallback, no eval harness, and no clean way to insert deterministic contracts. That is not the case.

Keep these pieces:

- `adapt/llm_planner.py` provider-chain direction.
- `WORKSHEET_PLANNER_V2` feature flag.
- deterministic fallback.
- section-cap enforcement.
- authored item schema direction.
- full-source plus corpus prompt context.
- judge with one regeneration.
- battery/gate infrastructure.

Replace or tighten these pieces:

- natural-language-only "preserve everything" prompt obligations,
- fuzzy/heuristic coverage as the primary guarantee,
- scalar judge threshold as the release gate,
- uncalibrated self-judge approval.

This is a strangler refactor, not a rewrite:

```text
Existing planner-v2
  -> add ledger
  -> add slot pack
  -> require IDs in model output
  -> validate exact ID coverage
  -> keep the existing fallback/judge/render pipeline
```

## Build-vs-Buy Assessment

| Need | Recommendation | Rationale |
|---|---|---|
| Coverage guarantee | Build | Domain-specific and small. No generic agent framework knows what a UFLI word chain means. |
| Structured output | Use provider features plus Pydantic | OpenAI Structured Outputs and Pydantic validation are useful for schema adherence, but semantic coverage must be app-owned. |
| Agent orchestration | Do not make it primary | Recent agent SDKs are improving quickly, but 2026 reliability research still shows variance under repeated runs. |
| Evals and CI | Consider Promptfoo or existing local battery | Promptfoo is open-source, local/CI-friendly, and supports multi-provider eval matrices. Useful for regression comparison. |
| Trace/eval platform | Braintrust or LangSmith only if workflow volume warrants it | Braintrust offers evals, CI/CD, online scoring, and production trace feedback; pricing starts free and Pro is listed at `$249/month`. LangSmith is strong if the project moves toward LangGraph/LangChain. |
| Human calibration | Build a small local review workflow first | A 15-20 plan spot check is enough before default promotion; expand to 60-100 only if approve-precision is weak. |

Sources:

- OpenAI Agents SDK docs: https://developers.openai.com/api/docs/guides/agents
- OpenAI Agents SDK April 2026 update: https://openai.com/index/the-next-evolution-of-the-agents-sdk/
- Pydantic AI agents docs: https://pydantic.dev/docs/ai/core-concepts/agent/
- LangSmith evaluation docs: https://docs.langchain.com/langsmith/evaluation
- Braintrust evaluation docs: https://www.braintrust.dev/docs/evaluate
- Braintrust pricing, fetched 2026-06-13: https://www.braintrust.dev/pricing
- Promptfoo docs, fetched 2026-06-13: https://www.promptfoo.dev/docs/intro/

## Gate Trustworthiness Plan

The release gate should become a layered decision, not a single judge score.

### Hard pass/fail gates

- Coverage ID equality.
- Valid answers.
- ADHD caps.
- No invalid worked examples.
- No concept-leak or garbled OCR leakage.
- Required text present in final render where applicable.

### Soft quality gates

- GPT judge for pedagogy and engagement.
- Gemini second-opinion judge on approved and cusp cases.
- Human review of approved and near-threshold plans.

### Calibration metric

Primary metric:

```text
judge approve-precision = human-shippable approved plans / all judge-approved plans
```

Stop rule:

- If roughly `20%` or more of judge-approved plans contain real child-facing defects, do not promote default-on.
- Build a larger 60-100 example calibration set before promotion.

This matches the product risk: false rejects are tolerable because fallback is safe; false approvals can reach a child.

## Cheapest Falsification Experiment

Build a thin prototype for the same three frozen images:

1. Create ledger entries from frozen `LiteracySkillModel`.
2. Pack them into ADHD-safe slots.
3. Ask the LLM to author slot content with `covered_source_item_ids`.
4. Reject if required IDs do not equal emitted IDs.
5. Run the existing battery twice with median-of-3 judging.
6. Blind-review current planner-v2 output vs slot-contract output for engagement.

Success criteria:

- Zero missing required source IDs.
- No coverage approve/reject flips from missing content.
- No human-rated engagement drop compared with current planner-v2.
- No increase in invalid worked examples or answer-key errors.

Falsifies the recommendation if:

- Coverage improves but worksheets become visibly flat or repetitive.
- Slot authoring produces many unnatural filler items.
- The packer over-constrains activity variety.
- Human reviewers prefer current planner-v2 despite coverage gains.

If falsified, do not abandon the whole direction. Loosen the packer:

- Let the LLM choose from allowed activity families per slot.
- Preserve source IDs and caps.
- Keep deterministic equality checking.

## Concrete Next Moves

1. Finish the already-planned real quality fixes:
   - concept sanitization,
   - worked-example bug.
2. Finish the B-prime gate protocol:
   - frozen extraction,
   - median-of-N judge,
   - two consecutive passing runs.
3. Add a small design doc or task section for `CoverageLedger` and `SlotPack`.
4. Prototype the ledger/slot path behind a new env flag, for example:
   - `WORKSHEET_PLANNER_SLOT_CONTRACT=1`
5. Compare:
   - legacy loop,
   - current planner-v2,
   - planner-v2 plus slot contract.
6. Do the 15-20 plan human approve-precision check before default promotion.

## Bottom Line

The planner should not be restarted from scratch. The current repo already has the right macro-direction: single-call planner, full source context, authored items, deterministic fallback, section caps, and a gate harness.

The missing piece is the deterministic coverage contract.

The recommended decision is:

```text
Keep planner-v2.
Add CoverageLedger and SlotPack.
Make source coverage deterministic and ID-based.
Keep LLM freedom for engagement and pedagogy.
Promote only after approve-precision and frozen-battery evidence are good.
```

That gives the project the best chance to eliminate content-coverage variance without turning the output into a boring compliance worksheet.

## Citation Validation Note

This report uses primary or near-primary sources where possible: official product docs/release notes for tools, arXiv papers for research claims, and local repo plans/code for project state. URLs were fetched or searched during the 2026-06-13 research pass. Vendor comparison/pricing details can drift, so re-check tool pricing before purchase decisions.
