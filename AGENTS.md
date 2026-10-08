# AGENTS.md

**Worksheet Builder** — skill-preserving worksheet adaptation engine for children ages 5-8 with ADHD. Transforms physical paper literacy worksheets into ADHD-optimized, themed, print-ready activities with progressive avatar engagement.

**Repo:** `https://github.com/howardjong/worksheet-builder.git`
**Plan:** `plans/worksheet-builder-consolidated-plan.md`
**Running context:** `.claude/worksheet-project-context.md` — **READ FIRST** for current state, decisions, handoff notes.

## Commands

```bash
make lint         # ruff check .
make typecheck    # mypy .
make test         # pytest tests/ -v
make test-golden  # golden E2E, no network
make format       # ruff format .

# Transform
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme space --output ./output/  # default render mode: image_gen
python transform.py ... --render-mode pdf_classic    # opt out to the deterministic PDF renderer
python transform.py ... --render-mode hybrid_shell   # on-demand art + vector text; live acceptance pending
python transform.py ... --render-mode image_prompt   # offline prompt artifacts for image-model trials

# Batch
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/
python batch.py ... --render-mode image_prompt  # batch prompt-only image-model trial artifacts
python batch.py ... --no-images    # skip AI images (avoids 35 RPD limit)
python batch.py ... --dry-run      # list only

# RAG
python -m experiments.corpus_ufli.ingest index --data-dir ./data/ufli
python -m rag.backfill --artifacts-dir ./samples/output --output-dir ./samples/output
python -m experiments.rag.eval --test-dir ./samples/input --profile profiles/ian.yaml
```

## Architecture

### Pipeline (deterministic core, AI is optional assist only)

```
Paper → Capture → Normalize → Source Extract → Skill Model → ADHD Adapt → Theme → Render → Validate
```

### Load-bearing constraints — violate and the pipeline breaks

- **Skill-preserving, not page-faithful.** Output may differ from source in layout/wording, but must preserve the literacy skill.
- **ADHD-safe.** Calm themes, limited decorations, chunked content, predictable rewards. **No loot boxes, streak punishment, or leaderboards.**
- **Print-first.** Primary output is printed paper. Digital companion is secondary.
- **AI in the production path, with provider redundancy.** All text, vision, research, audio-judge, and image inference calls use OpenRouter exclusively. Image models retry and fall through to independent model/vendor alternatives; generated pages must pass text, character, matching, and substantial learning-scene gates. After all image options fail, deterministic `pdf_classic` fallback is automatic and explicitly reported. Set `WORKSHEET_ALLOW_PDF_FALLBACK=0` to stop instead. (Owner clarification, Session 68: retain large scenes as the default, restore automatic PDF fallback after exhaustion.)
- **Idempotent.** Same inputs → same outputs. Keyed by `hash(image) + profile + theme + pipeline_version`.
- **Schema validation.** All stage outputs must validate against Pydantic schemas before influencing the pipeline.

### Data contracts (Pydantic)

`SourceWorksheetModel` → `LiteracySkillModel` → `AdaptedActivityModel` → `WorksheetDesignSpec`. Plus `LearnerProfile` and `RewardEventModel`.

### Module layout

- `capture/` — image preprocessing + master storage
- `extract/` — OCR + heuristics + AI assist adapter
- `skill/` — literacy skill taxonomy + extraction
- `adapt/` — ADHD activity adaptation + accommodation rules
- `theme/` — calm theme engine + curated assets
- `companion/` — learner profile, avatar, rewards, caregiver controls
- `render/` — ReportLab PDF, renderer strategies, image-model prompt artifacts, preview
- `validate/` — skill-parity, print, ADHD compliance
- `rag/` — embeddings, store, retrieval, indexer, backfill, eval
- `corpus/` — UFLI crawl/acquire/extract/ingest

## Conventions

- Python 3.11+, type hints everywhere, Pydantic for all data contracts.
- Persist intermediate artifacts in `artifacts/` for debugging.
- Master images in `masters/` (permanent, reusable).
- Profiles in `profiles/*.yaml`.
- Curated theme assets committed to repo; generated assets cached in `asset_cache/` (gitignored).
- RAG store in `vector_store/`; UFLI curriculum corpus lives in the `curriculum` collection.
- RAG embedding auto-selects API-key Gemini when available in `.env`; Vertex is available via `RAG_GEMINI_BACKEND=vertex`.
- Image renderer env: `OPENROUTER_API_KEY`; `WORKSHEET_IMAGE_PROVIDERS=openrouter` by default. `WORKSHEET_OPENROUTER_IMAGE_MODELS` overrides the ordered chain (default: GPT Image 2.5 Sunburst → Gemini 3 Pro Image → Seedream 5 Pro → Gemini 3.1 Flash Image). `WORKSHEET_IMAGE_MAX_ATTEMPTS` caps quality retries per model (default 3). API transport retries once for transient errors, with bounded backoff. See `docs/openrouter.md`.
- Text/vision models: `WORKSHEET_OPENROUTER_TEXT_MODELS` and `WORKSHEET_OPENROUTER_VISION_MODELS`; default GPT-5.5 plus Claude Sonnet 4.6 / Gemini 3.1 Pro fallbacks. Shared transport/configuration lives in `ai/openrouter.py`. Legacy adapter and image-provider names are compatibility aliases through OpenRouter; no direct SDK bypass exists. Audio judging uses `WORKSHEET_OPENROUTER_AUDIO_MODELS` and the actual waveform. Embeddings and speech synthesis are separate services.
- Lesson mode (`--lesson N`) defaults `WORKSHEET_PLANNER_V2=1` + `WORKSHEET_LLM_ADAPT=1` + `WORKSHEET_OBJECTIVE_COVERAGE=1` (objective-sufficiency planning: sample word pools to thresholds within the ADHD time budget, not exhaustive source coverage) + `WORKSHEET_MAX_WORKSHEETS=auto` (per-lesson evidence-based package budget, `adapt/workload.py`: objective demand vs. the learner's attention capacity, computed up front, logged, persisted to `artifacts/workload_budget.json`; set an integer for a fixed cap; family-balanced trim in `adapt/section_cap.py:enforce_package_cap` — owner policy 2026-07-07: objectives first, but inside what the child can sustain in one sitting; see `docs/research/adhd-workload-budget.md`), scoped to the run; explicit values win, `WORKSHEET_LLM_ADAPT=0` is a real opt-out (`adapt.rules.llm_adapt_enabled()`), and an explicit `WORKSHEET_PLANNER_SLOT_CONTRACT` suppresses the objective default (mutually exclusive). The photo workflow's defaults are unchanged (legacy loop, strict full-coverage rubric, split-never-trim — a photographed single page CAN be fully covered; D30/D31 promotion gate still pending).
- `WORKSHEET_SKIP_ASSET_GEN=1` disables all image generation and forces the deterministic `pdf_classic` fallback (used by tests/CI). Missing keys and exhausted attempts produce an explicitly reported PDF fallback by default; `WORKSHEET_ALLOW_PDF_FALLBACK=0` disables that degradation.

- On-demand composed trials: `hybrid_shell` generates fresh text-free scenes with bounded parallelism (default 3) and draws actual activity text locally. This requires no prebuilt lesson/image library. Content is finalized before judging; approved content is frozen. Deterministic content defects block before image calls, and scene fallback is reported as degraded, not approved. See `docs/on-demand-rendering.md` and `docs/handoffs/on-demand-live-validation.md`. Keep `image_gen` as the default until live and human visual acceptance.

## Session Handoff

At session end, update `.claude/worksheet-project-context.md` with: milestone/checkpoint status, what was completed, what's next (specific files/functions), decisions or open questions, and any gotchas discovered. Commit the context update alongside other changes.
