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
- **AI in the production path, with provider redundancy.** The default render/adapt path may call AI APIs. Reliability comes from provider fallback chains (Gemini → OpenAI → future providers) ending in the deterministic `pdf_classic` renderer — not from removing AI. Offline runs still work via deterministic fallbacks. (Supersedes the old "No AI in critical path" rule; see decision D26.)
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
- Image renderer (`image_gen`, the default render mode) env: `WORKSHEET_IMAGE_PROVIDERS` (comma-ordered fallback chain, default `openai,gemini`), `WORKSHEET_GEMINI_IMAGE_MODEL` (default `gemini-3-pro-image`), `WORKSHEET_OPENAI_IMAGE_MODEL` (default `gpt-image-2-2026-04-21`), `WORKSHEET_IMAGE_MAX_ATTEMPTS` (per-provider page-gen attempts, default 3 — cost guardrail). See decision D29.
- Text-model env: `WORKSHEET_OPENAI_TEXT_MODEL` (default `gpt-5.4`) — one knob for the judge, planner (openai leg), and ai_review. `WORKSHEET_PLANNER_PROVIDERS` (default `openai,gemini`) orders the planner chain.
- Lesson mode (`--lesson N`) defaults `WORKSHEET_PLANNER_V2=1` + `WORKSHEET_LLM_ADAPT=1`, scoped to the run; explicit values win, and `WORKSHEET_LLM_ADAPT=0` is a real opt-out (`adapt.rules.llm_adapt_enabled()`). The photo workflow's defaults are unchanged (legacy loop; D30/D31 promotion gate still pending).
- `WORKSHEET_SKIP_ASSET_GEN=1` disables all image generation and forces the deterministic `pdf_classic` fallback (used by tests/CI). Offline runs with no API keys degrade to `pdf_classic` the same way.

## Session Handoff

At session end, update `.claude/worksheet-project-context.md` with: milestone/checkpoint status, what was completed, what's next (specific files/functions), decisions or open questions, and any gotchas discovered. Commit the context update alongside other changes.
