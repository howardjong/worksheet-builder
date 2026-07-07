# Model Architecture Synthesis (2026-06-19)

## Purpose

This note captures useful architecture recommendations from a multi-model architecture comparison exercise. The goal is not to restart Worksheet Builder from scratch. The goal is to preserve the best ideas that emerged from the comparison and fold them into the existing codebase where they strengthen the current objective-sufficiency, planner, validation, and rendering work.

The strongest recurring theme was simple: the system should be organized around a durable representation of the literacy objective, with AI operating inside bounded slots and deterministic code owning correctness, safety, and print quality.

## Model Ranking Snapshot

Best result per model, based on fit for this project:

| Rank | Model | Assessment |
| ---: | --- | --- |
| 1 | GLM 5.2 | Best purpose-fit. Its central `SkillObjective` contract was the clearest architecture spine. Strong restraint, clean AI boundaries, and good future-proofing. |
| 2 | Minimax M3 | Very close to GLM. Excellent `SkillModel + AdaptPolicy` split, strong eval-set thinking, narrow V1 discipline, and good avoidance of agents/RAG/microservices. |
| 3 | Kimi 2.6 Thinking | Strong, balanced, and practical. Good schema-first pipeline and AI boundaries, but less crisp than GLM/Minimax on the exact literacy contract. |
| 4 | Mimi/Mimo v2.5 Pro | Thorough and high-quality. Strong validation, logging, provider strategy, and risk treatment. Slightly broader and less elegant than Minimax's contract design. |
| 5 | Qwen 3.7 Max Thinking | Good framing: this is structured document transformation, not an AI wrapper. Strong on deterministic rendering and semantic-worker boundaries, weaker on usable citations and the core skill-preservation object. |
| 6 | DeepSeek V4 / V4-Pro Thinking | Solid and practical in its best run, but more generic and sometimes over-prescriptive. Less deeply tuned to early-literacy correctness. |
| 7 | Gemini 3.5 Flash | Later run was much improved, with useful skill-lock and deterministic-gate instincts. Still weaker validation logic and more premature stack choices. |
| 8 | Gemini 3.1 Pro | Sane outline, but too thin for decision-ready architecture. Less depth on contracts, evals, calibration, and literacy-specific failure modes. |

If using an ensemble for future architecture review, excluding GLM and Gemini, the best practical trio is:

| Role | Model |
| --- | --- |
| Anchor rigor | Minimax M3 |
| Thorough safety/ops reviewer | Mimi/Mimo v2.5 Pro |
| Framing/contrast voice | Qwen 3.7 Max Thinking |

Kimi was strong, but if latency is too high, Mimi/Mimo is the better replacement than DeepSeek because it preserves more of Kimi's safety and validation strengths while adding operational detail.

## Recommendations Worth Carrying Forward

### 1. Make the literacy objective the central contract

The best idea from the model comparison was GLM's `SkillObjective` / Minimax's `SkillModel` framing. Worksheet Builder should treat the literacy objective as the durable spine of the pipeline.

In this repo, that does not mean replacing `LiteracySkillModel`. It means hardening the existing model and adjacent objective-ledger work so the objective is explicit, auditable, and shared by planning, validation, and judging.

Useful fields or concepts to carry forward:

- objective cells
- required practice forms
- source-item evidence
- target graphemes, phonemes, word patterns, and irregular words
- samplable pools versus required forms
- answer-key and source-artifact blockers
- corpus/taxonomy version
- confidence and uncertainty flags

This aligns with the existing objective-sufficiency direction: the judge should score against a deterministic ledger, not discover the objective from scratch.

### 2. Add an explicit adaptation policy boundary

Minimax's `AdaptPolicy` idea is worth considering. It separates what the worksheet teaches from how the worksheet is adapted for a learner, profile, theme, and ADHD constraints.

A lightweight first version could include:

- maximum items per chunk/page
- instruction length/style rules
- response-format preferences
- theme density and decoration limits
- scaffold/support settings
- reward/avatar rules, including explicit bans on streak punishment, leaderboards, loot boxes, and variable-ratio reward loops

Do not make this a giant configuration universe. The value is the boundary: pedagogy lives in the objective model; accommodations and presentation choices live in the policy.

### 3. Treat the skill taxonomy as governed data

Several models correctly converged on a governed, versioned literacy taxonomy. AI may classify into the taxonomy or suggest refinements, but it should not invent the taxonomy at runtime.

For this repo, the pragmatic path is:

- keep UFLI and early-literacy taxonomy coverage narrow and explicit;
- version the taxonomy/corpus assumptions used by a run;
- make taxonomy changes visible to tests and eval fixtures;
- avoid building a concept graph until a flat or lightly hierarchical taxonomy fails.

### 4. Build a golden eval set as a product asset

Minimax and Mimi/Mimo were strongest here. A living fixture set is likely higher leverage than more architecture work.

The fixture set should include representative worksheet families with expected:

- extraction artifacts;
- literacy objective / objective ledger;
- adaptation policy;
- adapted activity expectations;
- validation outcomes;
- known failure cases, including adversarial skill-drift examples.

This fixture set should be used to evaluate model, prompt, planner, judge, and renderer changes. It should grow from real failures and human-reviewed examples.

### 5. Standardize run bundles

The repo already persists artifacts, but the model exercise reinforced the value of a consistent run bundle shape.

A useful run bundle should include:

- source hash and pipeline version;
- model/provider versions and prompt hashes;
- intermediate JSON artifacts;
- objective ledger / skill model;
- adaptation policy or equivalent settings;
- validator reports;
- judge inputs/outputs;
- render metadata;
- final PDF/image artifacts;
- failure/retry history.

This makes future model upgrades measurable instead of impressionistic.

### 6. Keep provider roles configurable and eval-gated

The best answers treated providers as role-specific, not global. Worksheet Builder already has provider chains in multiple places; the general principle is worth standardizing:

- extraction / vision;
- planning / adaptation;
- judging;
- image rendering;
- fallback / deterministic mode.

Changing a role's model should require an eval run, not a code rewrite. A provider upgrade should be considered a product change when it can alter child-facing output.

### 7. Preserve the anti-overbuild discipline

The models that scored best all converged on similar non-goals:

- no microservices unless a real scaling boundary appears;
- no agent graph as the core product loop;
- no vector DB/RAG unless retrieval is the actual bottleneck;
- no broad personalization before the objective-preservation loop is reliable;
- no reward mechanics that create ADHD-hostile pressure or manipulation;
- no AI-generated full-page visual design unless it clears strict print, text, and skill-preservation gates.

This is directly relevant to any future simplification effort: keep the deterministic extraction/profile/adaptation/render/validation core, and move experiments behind clear flags, harnesses, or separate eval tools.

## Practical Next Step

The most actionable synthesis is:

```text
LiteracySkillModel / ObjectiveLedger
  -> AdaptPolicy
  -> planner / slot author
  -> deterministic validators
  -> judge calibrated against fixtures
  -> renderer
```

Before adding more AI capability, prioritize formalizing the objective-centered contract and eval fixtures. That gives future models a stable place to plug in without quietly changing the educational task.

## What Not To Do

Do not use this comparison as a reason to rewrite the app from scratch. The existing repo already contains much of the right shape: Pydantic contracts, deterministic rendering paths, provider fallback concepts, objective-sufficiency work, RAG/eval tooling, and artifact persistence. The useful move is targeted consolidation around the objective contract, adaptation policy boundary, and eval fixtures.
