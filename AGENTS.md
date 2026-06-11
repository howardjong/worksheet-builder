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
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme space --output ./output/
python transform.py ... --render-mode pdf_classic    # default deterministic PDF renderer
python transform.py ... --render-mode image_prompt   # offline prompt artifacts for image-model trials

# Batch
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/
python batch.py ... --render-mode image_prompt  # batch prompt-only image-model trial artifacts
python batch.py ... --no-images    # skip AI images (avoids 35 RPD limit)
python batch.py ... --dry-run      # list only

# RAG
python -m corpus.ufli.ingest index --data-dir ./data/ufli
python -m rag.backfill --artifacts-dir ./samples/output --output-dir ./samples/output
python -m rag.eval --test-dir ./samples/input --profile profiles/ian.yaml
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
- **No AI in critical path.** AI assist is always behind the `extract/adapter.py` interface and is optional.
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

## Session Handoff

At session end, update `.claude/worksheet-project-context.md` with: milestone/checkpoint status, what was completed, what's next (specific files/functions), decisions or open questions, and any gotchas discovered. Commit the context update alongside other changes.
