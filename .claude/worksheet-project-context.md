# Worksheet Builder — Running Context

> This is the running context document for session-to-session handoffs and multi-agent coordination.
> **Read this first** when starting a new session or picking up work.
> **Update this** at the end of every session with current state, decisions, and next steps.

---

## Current State

**Status:** Core product milestones remain complete. Gemini Embedding 2 RAG Phase 7 is implemented and the curriculum-aware adaptation follow-up is now wired through `adapt/engine.py`. UFLI corpus pipeline is fully executed: crawl complete (148 lessons), acquire complete (539 files), extract complete (148 normalized), index complete (148 curriculum records in `vector_store/`). RAG client now supports API-key or Vertex backends plus embedding-model fallback (`gemini-embedding-exp-03-07` -> `gemini-embedding-2-preview` -> `text-embedding-005`). Curriculum retrieval now flows through `transform.py` and `ab_eval.py` into adaptation so word choices can be steered toward exact UFLI lesson content when overlap is strong enough. Validation for this follow-up passed: focused `ruff`/`mypy` on touched files and full repo suite green (`294 passed`). Gemini access investigation on 2026-03-15 confirmed `.env` config is present and direct Gemini API access works outside the sandbox; prior live eval failures were caused by sandbox DNS/network restrictions, not missing credentials. OCR crash investigation on 2026-03-15 found the remaining stability risk is local PaddleOCR fallback on macOS/Python 3.13, not the RAG code itself: one `PaddleOCR(lang="en")` init raised RSS from ~163 MB to ~862 MB, and one real OCR pass on `samples/input/IMG_0004.JPG` peaked at `ru_maxrss=10432413696` (~10.4 GB on macOS) while processing only the first image. Eval hardening is now implemented enough for safe live runs: `ab_eval.py` and `rag/eval.py` default to `--extract-mode vision_only` so live evals fail fast instead of silently falling back to Paddle, `ab_eval.py` now requires explicit `--seed --extract-mode auto` for the old seed-and-fallback flow, and `extract/ocr.py` reuses a single PaddleOCR instance per process. Phase 14 batch indexing is now implemented too: batch workers return `RunArtifacts` payloads and the main thread performs sequential RAG indexing after worker completion. Harness split is now explicit: `rag/eval.py` is the primary experiment harness with retrieval-health and efficiency metrics, while `ab_eval.py` is the narrower causal check for whether retrieval beats no-RAG and an intentionally weak retrieval control.
**Branch:** `codex/feature-gemini-embedding-2-rag`
**Plan version:** 1.5.0 + `gemini-embedding-2-rag-plan.md` (v2)
**Last Updated:** 2026-03-15

### Milestone Progress

| Milestone | Status | Checkpoints | Notes |
|-----------|--------|-------------|-------|
| M1: Foundation + Source Extraction | **Complete** | ~~1.1~~, ~~1.2~~, ~~1.3~~, ~~1.4~~ | All done |
| M2: Skill Extraction + ADHD Adaptation | **Complete** | ~~2.1~~, ~~2.2~~, ~~2.3~~, ~~2.4~~ | All done (2.2 merged into 2.1) |
| M3: Theme + Render + Validate + E2E | **Complete** | ~~3.1~~, ~~3.2~~, ~~3.3~~, ~~4.4~~ | All done |
| M4: Companion + Avatar | **Complete** | ~~4.1~~, ~~4.2~~, ~~4.3~~ | All done |
| M5: AI Assist + Generative | **Complete** | ~~5.1~~, ~~5.2~~, ~~5.3~~ | OpenAI + Gemini + Claude |

### Active Workstream: Gemini Embedding 2 RAG + UFLI Corpus (2026-03-14)
- **Plan files:**
  - `gemini-embedding-2-rag-plan.md` — RAG architecture and phases (Phases 1-7 code implemented; curriculum-aware adaptation follow-up now complete)
  - `vertex-ai-gemini-migration-plan.md` — future repo-wide Gemini-to-Vertex migration plan; not yet implemented
  - `.claude/plans/reactive-mixing-riddle.md` — UFLI corpus ingestion plan (auto-loaded by Claude Code). Covers crawl/acquire/extract/ingest phases, file inventory, and verification steps
  - `worksheet-builder-consolidated-plan.md` — original product plan (v1.4.0, all 15 checkpoints complete)
- **Completed in branch**:
  - RAG package created: `rag/client.py`, `rag/embeddings.py`, `rag/store.py`, `rag/retrieval.py`, `rag/indexer.py`
  - RAG backend hardening: `rag/client.py` now supports `RAG_GEMINI_BACKEND=auto|api_key|vertex`, `rag/embeddings.py` retries across fallback embedding models, `corpus/ufli/ingest.py` loads `.env` for direct CLI runs
  - Phase 7 modules added: `rag/backfill.py` (artifact-to-index CLI) and `rag/eval.py` (retrieval/adaptation evaluation harness with JSON + Markdown reports)
  - Adaptation consumption path added in `adapt/engine.py` (`rag_prior_adaptations`, distractor blacklist, format mix rotation)
  - Curriculum-aware adaptation added in `adapt/engine.py`: optional `rag_curriculum_references` flows into both `adapt_activity()` and `adapt_lesson()`, builds a deterministic curriculum word bank from retrieved UFLI lesson text, prefers curriculum-backed target words when at least two exact matches are present, and annotates supported items with `curriculum_supported` metadata for auditability
  - Transform pipeline integration in `transform.py` (`RunArtifacts`, optional retrieval before adapt, optional indexing after run)
  - `transform.py` + `ab_eval.py` now preserve curriculum retrieval documents via `_select_rag_curriculum_context()` and pass them into the adaptation stage alongside exemplar/prior-adaptation metadata
  - Gemini access hardening (2026-03-15): `ab_eval.py` now loads `.env` directly instead of relying on `transform.py` import side effects; `extract/vision.py` now accepts either `GEMINI_API_KEY` or `GOOGLE_API_KEY`, matching the RAG client
  - Eval/runtime hardening (2026-03-15): `ab_eval.py` and `rag/eval.py` gained `--extract-mode vision_only|auto|paddle|tesseract` with safe default `vision_only`; `ab_eval.py` now defaults `--no-seed` and refuses `--seed` unless `--extract-mode auto`; `extract/ocr.py` now caches one PaddleOCR instance per process to avoid repeated model loads
  - Phase 14 batch indexing strategy implemented (2026-03-15): `transform.py` now exposes `run_pipeline_collect_artifacts(..., index_results=...)`; `batch.py` workers call it with `index_results=False`, collect `RunArtifacts` payloads, and then index sequentially from the main thread after `ThreadPoolExecutor` completes
  - Harness split implemented (2026-03-15):
    - `rag/eval.py` is now the primary experiment harness and reports retrieval latency, retrieval-context rate, curriculum-reference hit rate, selected-context average score, curriculum-support deltas, and mean RAG runtime overhead in addition to the existing retrieval/validator metrics
    - `ab_eval.py` is now explicitly the causal harness and adds curriculum-support metrics plus an optional `C_bad_rag` negative-control arm (`--negative-control/--no-negative-control`) that routes intentionally weaker retrieval context through adaptation
    - `transform._build_adapted_summary()` now records `curriculum_supported_items` and `curriculum_lesson_ids`, so both harnesses can score curriculum-backed adaptation behavior from run artifacts
  - Config/deps updates: `requirements.txt` (`chromadb>=0.5`, `python-pptx>=0.6.21`, `playwright>=1.40`), `.gitignore` (`vector_store/`, `data/ufli/raw/`, `data/ufli/normalized.jsonl`), `pyproject.toml` mypy override for `chromadb.*`, `playwright.*`, `pptx.*`
  - New RAG tests: `tests/test_rag_embeddings.py`, `tests/test_rag_store.py`, `tests/test_rag_retrieval.py`, `tests/test_rag_indexer.py`, `tests/test_rag_adapt.py`
  - New curriculum steering tests: `tests/test_rag_adapt.py` covers curriculum-backed target-word prioritization and the minimum-match guardrail; `tests/test_transform_rag_context.py` covers curriculum document preservation in transform-side RAG selection
  - **UFLI corpus ingestion pipeline** (new):
    - `corpus/__init__.py`, `corpus/ufli/__init__.py` — package structure
    - `corpus/ufli/crawl.py` — Playwright crawler for UFLI Toolbox (15 lesson group pages, ~148 lessons). Verified against live site. Features: retries with exponential backoff, incremental writes, malformed manifest recovery, browser cleanup via try/finally, realistic User-Agent/headers, rate limiting with jitter, SafeLinks URL unwrapping, A-J vs 1-128 page structure handling
    - `corpus/ufli/acquire.py` — Download PPTX/PDF resources from manifest. Features: retries with backoff, 60s socket timeout, partial file cleanup, resumable, prefers direct PPTX over Google Slides export
    - `corpus/ufli/extract.py` — Text extraction from PPTX (python-pptx) and PDF (PyMuPDF). Outputs `normalized.jsonl`
    - `corpus/ufli/ingest.py` — Embed with Gemini, index into ChromaDB `curriculum` collection. Click CLI with commands: `crawl`, `acquire`, `extract`, `index`, `run-all`
    - `rag/store.py` — Added `CURRICULUM = "curriculum"` collection constant
    - `rag/retrieval.py` — Added `curriculum_references` field to `RAGContext`, curriculum collection query in `retrieve_context()` (reuses existing skill embedding, no extra API call)
    - `transform.py` — Added `curriculum_references` count to RAG diagnostics
    - New tests: `tests/test_corpus_extract.py` (3), `tests/test_corpus_ingest.py` (4), `tests/test_retrieval_curriculum.py` (3) — 10 total
- **Validated locally**:
  - `.venv/bin/ruff check adapt/engine.py transform.py ab_eval.py tests/test_rag_adapt.py tests/test_transform_rag_context.py` — clean
  - `.venv/bin/mypy adapt/engine.py transform.py ab_eval.py tests/test_rag_adapt.py tests/test_transform_rag_context.py` — clean
  - `.venv/bin/pytest -q tests/test_rag_adapt.py tests/test_transform_rag_context.py` → `8 passed`
  - `.venv/bin/pytest -q tests/test_adapt.py tests/test_rag_adapt.py tests/test_transform_rag_context.py` → `48 passed`
  - `.venv/bin/pytest -q tests` → `285 passed`
  - `.venv/bin/pytest -q tests/test_vision.py tests/test_rag_client.py` → `6 passed`
  - `.venv/bin/ruff check extract/ocr.py ab_eval.py rag/eval.py tests/test_ab_eval.py tests/test_ocr_runtime.py` — clean
  - `.venv/bin/mypy extract/ocr.py ab_eval.py rag/eval.py tests/test_ab_eval.py tests/test_ocr_runtime.py tests/test_rag_eval.py` — clean
  - `.venv/bin/pytest -q tests/test_ab_eval.py tests/test_ocr_runtime.py tests/test_rag_eval.py tests/test_extract.py` → `18 passed`
  - `.venv/bin/ruff check transform.py batch.py batch_utils.py tests/test_batch.py` — clean
  - `.venv/bin/mypy transform.py batch.py batch_utils.py tests/test_batch.py` — clean
  - `.venv/bin/pytest -q tests/test_batch.py` → `27 passed`
  - `.venv/bin/pytest tests/ -v` → `294 passed`
  - `.venv/bin/ruff check ab_eval.py rag/eval.py transform.py tests/test_ab_eval.py tests/test_rag_eval.py` — clean
  - `.venv/bin/mypy ab_eval.py rag/eval.py transform.py tests/test_ab_eval.py tests/test_rag_eval.py` — clean
  - `.venv/bin/pytest -q tests/test_ab_eval.py tests/test_rag_eval.py tests/test_transform_rag_context.py tests/test_rag_adapt.py` → `14 passed`
  - Live eval: `source ~/.zshrc && personal-on && export RAG_GEMINI_BACKEND=vertex && PYTHONPATH=. .venv/bin/python -m rag.eval --test-dir samples/input --profile profiles/ian.yaml --db-path vector_store --theme roblox_obby --include 'IMG_0004.JPG' --output-root ./samples/output/rag_eval_live --extract-mode vision_only --no-images`
    - Output root: `samples/output/rag_eval_live/20260315_185306`
    - Result: `retrieval@3 mean=0.67`, `baseline_validator_pass_rate=1.0`, `rag_validator_pass_rate=1.0`, `rag_selected_source=curated_exemplars`, `rag_selected_count=2`
- **Executed** (2026-03-14):
  - `playwright install chromium` — done
  - **Crawl**: 148 lessons across 15 pages, zero errors, manifest at `data/ufli/manifest.jsonl`
  - **Acquire**: 539 files downloaded (148 PPTX + 131 decodable PDFs + 134 home practice PDFs + 126 additional PDFs). Required SSL fix: added `certifi` + `ssl.create_default_context(cafile=certifi.where())` to `acquire.py` (macOS Python 3.13 has no default CA bundle). All 148 lessons status: `acquired`
  - **Extract**: 148 lessons extracted to `data/ufli/normalized.jsonl` via python-pptx + PyMuPDF
  - **Index**: Completed after backend hardening. Live run used API-key backend auto-selection and `gemini-embedding-2-preview`; 148 lessons indexed into `vector_store/`
- **Pending from RAG plan**:
  - Run broader live eval coverage now that `rag/eval.py` is the primary harness and `ab_eval.py` is narrowed to causal checks
  - Optional docs updates (`README.md`, `CLAUDE.md`)
- **OCR eval crash investigation (2026-03-15)**:
  - Partial run artifacts confirm both live evals died in the first OCR fallback case:
    - `samples/output/ab_eval_live/20260314_215613/seed_runs/IMG_0003/artifacts/preprocessed_ocr_resized.png`
    - `samples/output/rag_eval_live/20260315_015613/IMG_0003/frozen/artifacts/preprocessed_ocr_resized.png`
    - Neither run reached `source_model.json` or a final report, so the failure occurred during Paddle OCR, not later in adaptation/render/RAG scoring.
  - Root-cause factors:
    - `extract/vision.py` returns `None` on sandbox DNS/network failures, which silently forces OCR fallback.
    - `extract/ocr.py` constructs a fresh `PaddleOCR(lang="en")` instance for every OCR call.
    - `ab_eval.py` seeds multiple non-target inputs before evaluating targets, so one invocation can trigger repeated OCR initializations when Gemini is unavailable.
    - Running `rag/eval.py` and `ab_eval.py` concurrently duplicates that memory-heavy OCR path in separate processes.
    - Local fallback safety is weak: `extract_text_with_fallback()` only catches `ImportError`, and local Tesseract is not installed in the current macOS dev environment.
  - Prevention plan:
    - Add an explicit OCR backend switch for evals (`auto|vision_only|paddle|tesseract`) and fail fast instead of silently falling back to Paddle when the intended live Gemini path is unavailable.
    - Cache/reuse a single PaddleOCR instance per process, or isolate OCR in a subprocess with a hard timeout/memory budget so an eval can fall back or abort cleanly instead of crashing the host app.
    - Default eval harnesses to sequential, low-footprint execution (`--no-seed`, single target, no parallel runs) unless live Gemini access is confirmed.
    - Add an OCR smoke/benchmark command that records elapsed time and peak RSS on one sample image before launching long evals.
    - Align the local OCR runtime with the supported matrix before depending on Paddle locally; current dev env is Python 3.13.1 while CI remains Python 3.11.
- **Future follow-up plan**:
  - `vertex-ai-gemini-migration-plan.md` captures the repo-wide Gemini auth/client migration to Vertex AI as a separate workstream after current evals and RAG hardening

### What Exists Now
- `worksheet-builder-consolidated-plan.md` — full implementation plan (v1.4.0, 15 checkpoints)
- `CLAUDE.md` — project guidance for Claude Code
- `.gitignore` — excludes data dirs, python artifacts, IDE files, samples/input/
- `.claude/` — context doc, commands, skills
- `samples/input/` — 6 UFLI phone photos (gitignored, local only)
- `samples/output/` — 3 manually-created adapted worksheet examples (committed)
- `pyproject.toml` — ruff, mypy (strict), pytest config
- `requirements.txt` — all pipeline dependencies pinned
- `Makefile` — lint, typecheck, test, test-golden, test-all, format, clean, batch
- `.github/workflows/ci.yml` — CI with Python 3.11, Tesseract, lint+typecheck+test
- 8 pipeline packages with `__init__.py`: capture, extract, skill, adapt, theme, companion, render, validate
- `capture/preprocess.py` — OpenCV preprocessing (deskew, dewarp, denoise, CLAHE)
- `capture/store.py` — hash-based master storage + archival PDF
- `capture/schema.py` — PreprocessResult, MasterRecord models
- `extract/ocr.py` — PaddleOCR v3/v2 + Tesseract fallback
- `extract/heuristics.py` — UFLI template detection + region classification
- `extract/schema.py` — SourceWorksheetModel, SourceRegion, OCRBlock, OCRResult
- `skill/taxonomy.py` — K-3 literacy taxonomy (6 domains), phonics pattern matcher
- `skill/extractor.py` — rule-based skill extraction dispatched by template_type
- `skill/schema.py` — LiteracySkillModel, SourceItem models
- `tests/test_capture.py` — 11 tests (preprocessing, storage, archival PDF)
- `tests/test_extract.py` — 13 tests (template detection, region classification, confidence)
- `tests/test_skill.py` — 31 tests (taxonomy, word work/story/generic extraction, schema)
- `companion/schema.py` — LearnerProfile + Accommodations (MVP fields, companion Optional)
- `adapt/schema.py` — AdaptedActivityModel, ActivityChunk, ScaffoldConfig, Step, Example, ActivityItem (with options, answer, picture_prompt, worksheet_number/count/title, break_prompt)
- `adapt/rules.py` — AccommodationRules, chunking tables, response format substitutions, FORMAT_RENDERING metadata, BRAIN_BREAK_PROMPTS, color system
- `adapt/engine.py` — ADHD activity adaptation: single-worksheet `adapt_activity()` + multi-worksheet `adapt_lesson()` producing 2-3 mini-worksheets with varied response types (match, trace, circle, fill_blank, write, read_aloud); helpers for distractors, fill-blank generation, comprehension questions, word-picture prompts
- `tests/test_adapt.py` — 40 tests (profile, rules, adaptation engine, multi-worksheet, format variety, schema)
- `validate/schema.py` — ValidationResult, ValidationViolation models
- `validate/skill_parity.py` — skill-parity + age-band validation (domain, skill, grade, format checks)
- `validate/adhd_compliance.py` — 12 ADHD design rule checks (chunk size, instructions, decoration, scoring, format variety, worksheet time limit, etc.)
- `tests/test_validate.py` — 25 tests (skill parity, age band, ADHD compliance, schema)
- `theme/schema.py` — ThemeConfig (with multi_worksheet flag), ThemeColors, ThemeFonts, AssetManifest, ThemedModel models
- `theme/engine.py` — theme loading (YAML) + application; 4 built-in themes
- `theme/themes/space/config.yaml` — Space Adventure theme
- `theme/themes/underwater/config.yaml` — Ocean Explorer theme
- `theme/themes/dinosaur/config.yaml` — Dino Discovery theme
- `theme/themes/roblox_obby/config.yaml` — Roblox Obby Quest (multi_worksheet: true, avatar_position: integrated)
- `tests/test_theme.py` — 11 tests (theme loading, application, round-trip)
- `render/pdf.py` — ReportLab PDF renderer: letter size, margins, vector text, chunks, self-assessment + new format renderers (_draw_match_item, _draw_trace_item, _draw_circle_item, _draw_fill_blank_item, _draw_read_aloud_item, _draw_break_prompt, _draw_chunk_with_scene)
- `render/pose_planner.py` — content-driven scene planning: analyzes chunk content to generate character scene descriptions and word picture prompts
- `render/asset_gen.py` — AI asset generation with hash-based caching; generates character scenes + word pictures via Gemini; graceful fallback when no API key
- `validate/print_checks.py` — PDF print quality validation (dimensions, text, pages)
- `tests/test_render.py` — 20 tests (PDF rendering, multi-format rendering, print quality validation)
- `transform.py` — CLI entry point: single-worksheet (backward-compatible) and multi-worksheet pipelines with format variety validation
- `tests/test_smoke.py` — verifies all packages importable

- `companion/profile.py` — profile CRUD (create, update accommodations, ensure companion fields)
- `companion/catalog.py` — 15-item avatar catalog across 3 themes + universal
- `companion/rewards.py` — token economy (effort-based, milestone bonuses, purchase, equip/unequip)
- `companion/caregiver.py` — progress reports, accommodation adjustments
- `complete.py` — CLI entry point for completion, rewards, progress, accommodations
- `tests/test_companion.py` — 28 tests (profile, catalog, rewards, caregiver)

- `extract/adapter.py` — ModelAdapter protocol; OpenAI (GPT-5.4), Gemini (3.1 Flash Lite), Claude adapters; NoOpAdapter baseline; image generation (Gemini 3.1 Flash Image Preview primary, OpenAI gpt-image-1.5 fallback); auto-detection: OpenAI > Gemini > Claude > NoOp
- `tests/test_adapter.py` — 27 tests (schema contracts, adapters, factory, image gen, AI assist runner)
- `extract/vision.py` — Gemini vision fallback: sends image to Gemini when OCR quality is poor (>80 fragments or <0.5 avg confidence)
- `.env` — API keys (gitignored): OPENAI_API_KEY, GEMINI_API_KEY
- `README.md` — project documentation
- `gemini-embedding-2-rag-plan.md` — Gemini Embedding 2 RAG architecture and implementation plan (v2)
- `rag/` — new RAG package (Vertex AI client, embedding service, vector store, retrieval, indexer)
- `batch.py` — batch processing CLI: multi-threaded orchestration with rate limiting, retry, graceful shutdown, manifest-based skip detection
- `batch_utils.py` — batch utilities: FileResult, RateLimiter (token-bucket), ProgressTracker, file collection, manifest I/O, report generation
- `tests/test_batch.py` — 25 tests (file collection, rate limiter, progress tracker, manifest, process_single_file, CLI dry-run)
- `tests/test_rag_*.py` + `tests/test_rag_adapt.py` — RAG unit tests and retrieval-to-adaptation tests
- `corpus/ufli/crawl.py` — Playwright crawler for UFLI Toolbox (15 page groups, ~148 lessons)
- `corpus/ufli/acquire.py` — Resource downloader (PPTX + PDF) with retries
- `corpus/ufli/extract.py` — Text extraction from PPTX (python-pptx) and PDF (PyMuPDF)
- `corpus/ufli/ingest.py` — Embed + index into ChromaDB curriculum collection; Click CLI
- `tests/test_corpus_extract.py` — 3 tests (PPTX/PDF extraction with fixtures)
- `tests/test_corpus_ingest.py` — 4 tests (ingestion, idempotency, grade derivation)
- `tests/test_retrieval_curriculum.py` — 3 tests (curriculum retrieval, grade filtering, empty collection)

### What's Next
**All original milestones remain complete. UFLI crawl/acquire/extract/index are done. Active remaining work is now experiment-harness consolidation/docs and broader production hardening.**

### Handoff Start Here
- **Current ready state**: `vector_store/` contains 148 indexed UFLI curriculum records, transform/eval code now passes curriculum hits into adaptation, and curriculum-backed word steering is covered by tests.
- **Current code state**: `rag/backfill.py` and `rag/eval.py` are implemented; curriculum-aware adaptation is now complete in `adapt/engine.py`; full repo suite is green after the latest changes (`294 passed`); live `rag/eval.py` has been verified against Vertex on one sample input.
- **First task next session**: run a wider multi-image live `rag/eval.py` sweep and inspect whether the new retrieval/curriculum metrics show any lift beyond ties in validator outcomes.
- **Second task after that**: decide whether to add OCR subprocess isolation / memory-budget enforcement for explicit OCR modes (`auto|paddle|tesseract`), since the fail-fast/default path is already in place.
- **Primary files to open first**: `rag/eval.py`, `ab_eval.py`, `transform.py`, `gemini-embedding-2-rag-plan.md`
- **Useful verification commands**:
  - `.venv/bin/pytest -q tests/test_rag_backfill.py tests/test_rag_eval.py tests/test_rag_client.py tests/test_rag_embeddings.py tests/test_rag_retrieval.py tests/test_corpus_ingest.py tests/test_retrieval_curriculum.py`
  - `.venv/bin/python -c 'from rag.store import CURRICULUM, get_or_create_collection, get_store; print(get_or_create_collection(get_store("vector_store"), CURRICULUM).count())'`
- **Environment note**: live Gemini embedding currently works via API-key auto-selection from `.env`. Vertex fallback remains supported in code but was not needed after backend hardening.
- **Sandbox note (2026-03-15)**: a minimal direct Gemini probe failed inside Codex sandbox with `httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known`, then succeeded immediately when rerun with escalation (`pong`). Use escalated commands for live Gemini evals from Codex, or expect OCR-only fallback behavior.
- **OCR note (2026-03-15)**: the local macOS dev env currently has PaddleOCR 3.4.0 / Paddle 3.3.0 on Python 3.13.1 and no `tesseract` binary in `PATH`. Treat local Paddle fallback as memory-unsafe until the eval harness is hardened or the runtime is aligned.
- **Vertex auth note (2026-03-15)**: personal ADC now works for Vertex on `ws-builder-rag` when using `personal-on` (`GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/adc-personal.json`, `GOOGLE_CLOUD_PROJECT=ws-builder-rag`, `GOOGLE_CLOUD_LOCATION=us-central1`). Live repo verification succeeded with `RAG_GEMINI_BACKEND=vertex`; prior failures were caused by ADC authenticating as `hjong@verily.health` instead of `howiejong@gmail.com`.

**Priority 1: Remaining RAG work** (see `gemini-embedding-2-rag-plan.md`)
- Decide how `rag/eval.py` and `ab_eval.py` should coexist or converge
- Expand live eval coverage beyond the verified single-image run if broader evidence is needed

**Priority 2: Testing and polish**
- Test batch processing on full folder of UFLI lessons
- Test multi-worksheet output on more UFLI lessons
- AI asset generation end-to-end (requires Gemini API key with image gen capability)
- Custom font embedding (Nunito TTF files)
- Two-column scene layout refinement (content-column-width-constrained rendering)
- Web/mobile companion app (beyond CLI)

---

## Key Decisions Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| D1 | PaperBanana dropped | It generates academic illustrations, not worksheet adaptations | 2026-03-07 |
| D2 | Deterministic core, AI as optional assist | Pipeline must work offline without API calls | 2026-03-07 |
| D3 | Physical paper as image-native input | Master images are the authoritative artifact | 2026-03-07 |
| D4 | Skill-preserving, not page-faithful | Preserve instructional intent, not exact layout/wording/word lists | 2026-03-07 |
| D5 | ReportLab for vector-first PDF rendering | Text stays vector (searchable, sharp), raster only for illustrations | 2026-03-07 |
| D6 | PaddleOCR primary, Tesseract fallback | PaddleOCR better on camera photos; Tesseract requires native binary | 2026-03-07 |
| D7 | Pydantic for all data contracts | Single contract layer for schema validation, serialization, type enforcement | 2026-03-07 |
| D8 | Curated theme assets for MVP | No on-demand image generation; pre-made asset packs per theme | 2026-03-07 |
| D9 | ADHD anti-patterns are hard constraints | No loot boxes, streak punishment, leaderboards, variable-ratio rewards — ever | 2026-03-07 |
| D10 | UFLI Foundations as primary input family | Two known templates: word work + decodable story. Private input only, not repo fixtures | 2026-03-07 |
| D11 | MVP = core engine only (M1-M3) | Companion layer (avatar, tokens, caregiver) is post-core, pre-launch | 2026-03-07 |
| D12 | Game-themed structure, visually calm execution | Evidence-consistent ADHD design: game labels are motivational scaffolding but visually subordinate to literacy content | 2026-03-07 |
| D13 | Effort-based rewards, never accuracy-based | XP/points for completing and trying, not for getting answers right | 2026-03-07 |
| D14 | Skill-parity validates instructional intent | Adapted activities may use different words as long as they exercise the same skill pattern | 2026-03-07 |
| D15 | AI output may differ from no-AI output | Both paths produce valid results; AI is bounded, schema-validated, and auditable | 2026-03-07 |
| D16 | Golden test fixtures must be synthetic | Original content mimicking UFLI layout — no copyrighted material in repo | 2026-03-07 |
| D17 | Companion fields are Optional in data contracts | MVP builds and runs without companion layer; reward_event, avatar_prompts, avatar_image all Optional | 2026-03-07 |
| D18 | Ontario curriculum primary, BC at high level | Ontario Language 2023 Strand B/C is specific; BC ELA K-3 is high-level alignment only | 2026-03-07 |
| D19 | GPT-5.4 primary for text, Gemini for images | OpenAI best for structured JSON text tasks; Gemini 3.1 Flash Image Preview for asset generation with OpenAI gpt-image-1.5 fallback | 2026-03-07 |
| D20 | google.genai SDK, not google.generativeai | Old SDK deprecated; new google.genai has different API (Client-based) | 2026-03-07 |
| D21 | Auto-detection: OpenAI > Gemini > Claude | Priority based on available API keys; NoOp baseline when no keys | 2026-03-07 |
| D22 | Gemini vision as OCR fallback, not replacement | OCR runs first; if >80 fragments or <0.5 avg confidence, send image to Gemini for structured extraction. Keeps deterministic path working without API keys | 2026-03-07 |
| D23 | UFLI corpus as 5th ChromaDB collection (`curriculum`) | Gives RAG system canonical lesson content (concepts, target words, teaching sequences) for retrieval during worksheet generation | 2026-03-13 |
| D24 | Playwright for UFLI crawl, not HTTP fetch | UFLI Toolbox is JS-rendered (Divi/WordPress); static fetch returns only framework code | 2026-03-13 |
| D25 | Incremental manifest writes in crawler | Write after each page, not batched at end — crash on page 14 preserves pages 1-13 | 2026-03-13 |

---

## Architecture Quick Reference

### Pipeline Stages & Data Flow
```
[1] Capture    → master page image (PNG)
[2] Normalize  → preprocessed image (OpenCV)
[3] Extract    → SourceWorksheetModel (Pydantic) — OCR + heuristics, Gemini vision fallback
[4] Skill      → LiteracySkillModel (Pydantic) — dispatches by template_type
[5] Adapt      → AdaptedActivityModel (single) or list[AdaptedActivityModel] (multi-worksheet)
[5b] AI Review → iterative quality review
[6] Theme      → themed model with decoration zones; multi_worksheet themes → 2-3 mini-worksheets
[6c] Assets    → AI-generated character scenes + word pictures (optional, cached)
[7] Render     → PDF (ReportLab, vector text, match/trace/circle/fill_blank/read_aloud renderers)
[8] Validate   → skill-parity, age-band, print, ADHD compliance, format variety
```

### UFLI Template Types
```
ufli_word_work:        concept_label, sample_words, word_chain, chain_script,
                       sight_word_list, practice_sentences
ufli_decodable_story:  story_title, illustration_box, decodable_passage
unknown:               falls back to generic heuristics
```

### Module → Checkpoint Mapping
```
capture/    → Checkpoint 1.2
extract/    → Checkpoint 1.3
skill/      → Checkpoint 1.4
adapt/      → Checkpoints 2.1, 2.2
validate/   → Checkpoints 2.3, 2.4, 3.3
theme/      → Checkpoint 3.1
render/     → Checkpoint 3.2
transform.py + tests/test_e2e.py → Checkpoint 4.4 (in Milestone 3)
companion/  → Checkpoints 4.1, 4.2, 4.3 (post-core)
extract/adapter.py → Checkpoint 5.1 (post-launch)
rag/        → RAG Phases 1-6 (embeddings, store, retrieval, indexer)
corpus/     → UFLI corpus pipeline (crawl, acquire, extract, ingest)
```

### UFLI Corpus Pipeline
```
CLI: python -m corpus.ufli.ingest <command> --data-dir ./data/ufli

crawl    → Playwright crawl → data/ufli/manifest.jsonl    ✅ DONE (148 lessons)
acquire  → Download PPTX/PDF → data/ufli/raw/{lesson_id}/ ✅ DONE (539 files)
extract  → python-pptx + PyMuPDF → data/ufli/normalized.jsonl ✅ DONE (148 records)
index    → Gemini embed + ChromaDB → vector_store/         ❌ BLOCKED (Vertex AI 403)
run-all  → All 4 steps in sequence

ChromaDB collections: worksheets, skills, adaptations, exemplars, curriculum

Note: acquire.py was patched to use certifi SSL context (macOS Python 3.13 fix).
Note: index step requires GOOGLE_CLOUD_PROJECT=ws-builder-rag env var.
```

### Key Files (once created)
| File | Purpose |
|------|---------|
| `transform.py` | CLI: transform worksheets (full pipeline) |
| `complete.py` | CLI: mark completion, award tokens (post-core) |
| `extract/heuristics.py` | UFLI template detection + region classification |
| `extract/adapter.py` | Model adapter interface (swap AI providers by config) |
| `adapt/rules.py` | ADHD accommodation rules (chunking tables, substitutions) |
| `skill/taxonomy.py` | K-3 literacy skill taxonomy |
| `skill/extractor.py` | Skill extraction dispatched by template_type |
| `validate/skill_parity.py` | Instructional-intent preservation validation |
| `validate/adhd_compliance.py` | ADHD design rules enforcement |

---

## ADHD Design Summary (for quick reference)

**Core principle:** Game-themed structure, visually calm execution.

- **Decoration budget:** 0-2 decorative + unlimited functional visuals per page
- **Color system:** Blue (directions), Green (examples), Gold (rewards), Black (content), White (background)
- **Avatar:** 1-2 instances per page in fixed zones, one consistent character, visually subordinate
- **Chunking:** ~3-7 min per chunk, grade-scaled item counts (K: 2-3, Grade 3: 5-8)
- **Game labels:** "Level 1" / "Challenge" are fine but must be visually subordinate — child focuses on literacy, not mechanics
- **Rewards:** Effort-based stars/checkmarks per section. No complex XP totals, no accuracy scoring
- **Self-assessment:** "I can... / I'm still learning..." checklist at end of each worksheet
- **Time estimates:** Soft cues only ("About 3 minutes"), configurable off for anxious children

---

## Open Questions

| # | Question | Context | Status |
|---|----------|---------|--------|
| Q1 | PaddleOCR vs Tesseract cross-platform install | PaddleOCR has heavier dependencies; may affect dev setup | Open |
| Q2 | Nunito font licensing for embedded PDF | Listed as primary theme font | Open |
| Q3 | How to create synthetic golden test images | Need to mimic UFLI layout without using UFLI content | Open — solve during Checkpoint 1.3 |

---

## Gotchas Discovered

| # | Gotcha | Impact | Resolution |
|---|--------|--------|------------|
| G1 | pytesseract is only a Python wrapper | CI needs `apt-get install tesseract-ocr` | Added to CI workflow |
| G2 | PDF/A is not a simple ReportLab toggle | Requires ocrmypdf or equivalent | Deferred to post-MVP |
| G3 | OpenDyslexic not evidence-backed for ADHD | Was listed as font option | Removed, replaced with Nunito |
| G4 | "All source target words must appear" is too strict | Blocks valid adaptations for phonics, morphology, fluency | Changed to instructional-intent preservation |
| G5 | GitHub PAT needs `workflow` scope to push CI files | `.github/workflows/ci.yml` push rejected without it | User needs to update PAT or push CI file via web UI |
| G6 | google.generativeai deprecated | FutureWarning on import | Migrated to google.genai SDK |
| G7 | UFLI Toolbox A-J page has different table structure | 2 columns (Lesson + Slide Deck) vs 6 columns (1-128 pages); row headers say "Getting Ready A" not "A" | Structural detection (link presence in first cell) + `_normalize_lesson_id()` |
| G8 | Some UFLI Google Slides URLs wrapped in Outlook SafeLinks | `nam10.safelinks.protection.outlook.com` URL wrapping on A-J page | `_extract_gslides_id()` unwraps via `urllib.parse.parse_qs` |
| G9 | UFLI Toolbox has 15 lesson group pages, not 5 | Original assumption was 5 slugs; actual site has 15 slug pages | Verified via Playwright MCP, hardcoded all 15 slugs |
| G10 | macOS Python 3.13 has no default SSL CA bundle | `urllib.request.urlretrieve` fails with `SSL: CERTIFICATE_VERIFY_FAILED` | Added `certifi` package + `ssl.create_default_context(cafile=certifi.where())` to `acquire.py`; replaced `urlretrieve` with `urlopen` + chunked write (urlretrieve doesn't accept SSL context) |
| G11 | Vertex AI ADC permissions for embedding model | `gemini-embedding-exp-03-07` returns 403 `PERMISSION_DENIED` even with `GOOGLE_CLOUD_PROJECT` set and quota project configured. ADC user needs `aiplatform.endpoints.predict` permission | Re-authenticated ADC with quota project (`gcloud auth application-default login --project=ws-builder-rag`); still blocked. May need service account key or different auth approach |
| G7 | GPT-5.4 uses max_completion_tokens not max_tokens | 400 error with max_tokens param | Changed to max_completion_tokens |
| G8 | gpt-image-1.5 doesn't support response_format param | 400 error; returns b64_json by default | Removed response_format param |

---

## Session Log

### Session 1 — 2026-03-07 (Planning)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built initial plan through 7 versions (0.1.0 → 1.0.0)
- Key pivots: dropped PaperBanana, added physical paper input, ADHD design, avatar progression, skill-preserving adaptation, companion layer

### Session 2 — 2026-03-07 (Plan Review + Refinement)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Applied 4 rounds of review feedback (v1.0.0 → v1.4.0):
  - **v1.1.0:** Narrowed MVP to core engine; fixed skill-parity validator; resolved AI-assist contradiction; fixed CI Tesseract + PDF/A issues; softened curriculum claims; corrected ADHD evidence; clarified Pydantic as single contract layer
  - **v1.2.0:** Evidence-consistent ADHD design overhaul using Perplexity research (PMC10453933, PMC5280087, Longwood/BCH tools); established "game-themed structure, visually calm execution"; added decoration budget, chunking targets, effort-based rewards, self-assessment, avatar placement rules
  - **v1.3.0:** Split UFLI into two templates (word work + decodable story); restrained game framing; added UFLI rights boundary; softened research language to "evidence-consistent"
  - **v1.4.0:** Accuracy pass for clean build: threaded template_type through data model; added UFLI-specific region types; made companion fields Optional; separated LearnerProfile MVP vs companion fields; noted golden fixtures must be synthetic; added self_assessment to AdaptedActivityModel
- Reviewed all 6 input samples (UFLI phone photos) and 3 output samples (manually-created adapted worksheets)
- Identified key tension: output samples are more visually dense than ADHD evidence supports → resolved with "game structure, calm execution" principle

**What's next:** Checkpoint 1.1 — Repository scaffold + CI

### Session 3 — 2026-03-07 (Checkpoint 1.1 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.1: repo scaffold, dependencies, CI, Makefile, package structure
- Created pyproject.toml (ruff, mypy strict, pytest config)
- Created requirements.txt with all pinned deps (PaddleOCR, OpenCV, ReportLab, Pydantic, etc.)
- Created Makefile with 7 targets
- Created CI workflow with Tesseract install
- Created 8 pipeline packages with __init__.py
- Created smoke test verifying all packages importable
- All acceptance criteria pass: `make lint`, `make typecheck`, `make test`
- Hit G5: GitHub PAT missing `workflow` scope, blocking push of ci.yml

**What's next:** Checkpoint 1.2 — Image Capture + Preprocessing

### Session 4 — 2026-03-07 (Checkpoint 1.2 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.2: image capture, preprocessing, master storage
- `capture/schema.py` — PreprocessResult and MasterRecord Pydantic models
- `capture/preprocess.py` — full OpenCV pipeline: page detection, perspective warp, deskew (Hough), denoise, CLAHE contrast normalization, border trimming
- `capture/store.py` — hash-based master storage (idempotent) + archival PDF via ReportLab
- `tests/test_capture.py` — 11 tests with synthetic worksheet image generator (skew, perspective, noise, desk background variants)
- Tested against real UFLI sample: perspective correction detected and applied correctly
- Resolved numpy/OpenCV typing issues with mypy strict mode (used `np.ndarray[Any, Any]` alias)

**What's next:** Checkpoint 1.3 — OCR + Source Extraction

### Session 5 — 2026-03-07 (Checkpoint 1.3 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.3: OCR extraction, UFLI template detection, region classification
- `extract/schema.py` — SourceWorksheetModel, SourceRegion, OCRBlock, OCRResult Pydantic models with template_type and UFLI-specific region types
- `extract/ocr.py` — PaddleOCR v3 (dict output format) + v2 (list format) + Tesseract fallback; polygon-to-bbox conversion; sorted output
- `extract/heuristics.py` — detect_ufli_template (keyword matching + story structure detection); map_to_source_model with template-specific classifiers for word work, decodable story, and generic fallback
- `tests/test_extract.py` — 13 tests: template detection (4), source model mapping (6), confidence gating (3)
- Discovered PaddleOCR v3 requires paddlepaddle and has new API (dict output with rec_texts/rec_scores/rec_polys instead of list-of-lists)
- PaddleOCR v3 is slow on CPU (~2-3 min per image); added PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK env var
- Added pytesseract to mypy ignore list in pyproject.toml
- G5 resolved: PAT updated with workflow scope, CI file pushed

**What's next:** Checkpoint 1.4 — Skill Taxonomy + Extraction

### Session 6 — 2026-03-07 (Checkpoint 1.4 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.4: Skill Taxonomy + Extraction — completes Milestone 1
- `skill/schema.py` — LiteracySkillModel and SourceItem Pydantic models
- `skill/taxonomy.py` — K-3 literacy taxonomy with 6 domains, phonics pattern matcher with word-boundary-aware matching for short patterns
- `skill/extractor.py` — rule-based extraction dispatched by template_type: word work → phonics domain with concept label pattern matching, chain/sight word extraction; decodable story → fluency domain with CVCe passage analysis; generic fallback with reduced confidence
- `tests/test_skill.py` — 31 tests: taxonomy (8), word work extraction (10), decodable story extraction (7), generic extraction (3), schema validation (3)
- Fixed false positive in phonics pattern matcher: 2-char patterns (sh, ch, st, etc.) were matching inside words like "just" → added word boundary requirement for short patterns
- All 56 tests pass, lint clean, types clean

**What's next:** Checkpoint 2.1 — LearnerProfile + Accommodation Rules

### Session 7 — 2026-03-07 (Checkpoint 2.1 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 2.1: ADHD Activity Adapter + Accommodation Rules + LearnerProfile
- `companion/schema.py` — LearnerProfile with MVP fields (name, grade_level, accommodations) and Optional companion fields (avatar, preferences, progress); YAML load/save
- `adapt/schema.py` — AdaptedActivityModel, ActivityChunk, ScaffoldConfig, Step, Example, ActivityItem Pydantic models
- `adapt/rules.py` — AccommodationRules derived from grade+profile; chunking tables (K:2-3, G1:3-5, G2:4-6, G3:5-8); response format substitutions; instruction limits by grade; font size minimums; color system; time estimates
- `adapt/engine.py` — Full adaptation pipeline: source items → chunked activity items with worked examples (fading scaffolding), numbered instructions, time estimates, self-assessment checklist, decoration zones; handles phonics, fluency, and generic domains
- `tests/test_adapt.py` — 28 tests: profile (4), rules (7), adaptation engine (17)
- All 84 tests pass, lint clean, types clean

**What's next:** Checkpoint 2.2/2.3 — Accommodation Rules Engine + Skill-Parity Validation

### Session 8 — 2026-03-07 (Checkpoints 2.3 + 2.4 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 2.3 + 2.4: Skill-Parity Validation + ADHD Compliance — completes Milestone 2
- `validate/schema.py` — ValidationResult and ValidationViolation Pydantic models with add_violation helper (errors set passed=False, warnings don't)
- `validate/skill_parity.py` — 5 checks: domain preserved, specific skill preserved (warning), grade band (±1 grade allowed), response types compatible, non-empty adaptation; plus age_band validator
- `validate/adhd_compliance.py` — 10 checks: chunk size limits, numbered instructions, instruction word/step limits, decoration budget (≤2), no dense text, worked example in first chunk, self-assessment present, no accuracy-based scoring, decoration zone coords valid, time estimates reasonable
- `tests/test_validate.py` — 25 tests: skill parity (8), age band (3), ADHD compliance (11), schema (3)
- All 109 tests pass, lint clean, types clean

**What's next:** Checkpoint 3.1 — Theme Engine

### Session 9 — 2026-03-07 (Checkpoints 3.1 + 3.2 + 3.3 + 4.4 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 3.1-3.3 + 4.4: Theme Engine + PDF Renderer + Print Validation + E2E Pipeline — completes Milestone 3 and all MVP milestones
- `theme/schema.py` — ThemeConfig, ThemeColors, ThemeFonts, DecorativeConfig, ThemedModel
- `theme/engine.py` — load themes from YAML, apply theme to adapted model, plan decoration placements within zones
- 3 built-in themes: space (Space Adventure), underwater (Ocean Explorer), dinosaur (Dino Discovery)
- `render/pdf.py` — ReportLab PDF renderer: letter size (8.5x11"), 0.75" margins, vector text, grade-scaled font sizes, chunk headers, numbered instructions, worked examples in green-tinted boxes, activity items with response format indicators, self-assessment checklists, themed footer
- `validate/print_checks.py` — PDF validation: readable, letter dimensions, has pages, non-empty pages, vector text present
- `transform.py` — Full CLI pipeline: preprocess → store master → OCR → source model → skill extraction → ADHD adaptation → theme → render PDF → validate (skill parity + age band + ADHD compliance + print quality) → persist all artifacts
- `tests/test_theme.py` — 11 tests: theme loading (6), theme application (5)
- `tests/test_render.py` — 12 tests: PDF rendering (7), print quality validation (5)
- All 132 tests pass, lint clean, types clean

**What's next:** MVP complete. Post-core milestones: M4 (Companion + Avatar) and M5 (AI Assist)

### Session 10 — 2026-03-07 (Checkpoints 4.1 + 4.2 + 4.3 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 4.1-4.3: Companion + Avatar layer — completes Milestone 4
- `companion/schema.py` — expanded with structured models: AvatarConfig, Preferences, Progress, CompletionRecord, OperationalSignals (replacing generic dict[str, Any] fields)
- `companion/profile.py` — create_profile (saves to YAML), update_accommodations, ensure_companion_fields
- `companion/catalog.py` — 15 avatar items across universal + 3 themes; get_item, get_affordable_items, get_milestone_items
- `companion/rewards.py` — predictable effort-based token economy: 10 tokens/worksheet, milestone every 5 (25 bonus), purchase/equip/unequip items; enforces ADHD-safe rules (no accuracy scoring, milestone items auto-unlock)
- `companion/caregiver.py` — view_progress report, adjust_accommodations
- `complete.py` — CLI: --lesson (award), --progress (report), --buy (purchase), --set-chunking (adjust)
- `tests/test_companion.py` — 28 tests: profile (5), catalog (6), rewards (13), caregiver (4)
- All 160 tests pass, lint clean, types clean

**What's next:** M5 (AI Assist + Generative) — post-launch milestone

### Session 11 — 2026-03-07 (Checkpoint 5.1-5.3 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 5.1-5.3: AI Assist layer — completes Milestone 5 and all milestones
- `extract/adapter.py` — ModelAdapter Protocol with 4 methods (tag_regions, infer_skill, review_ocr, suggest_adaptations); NoOpAdapter (deterministic baseline); ClaudeAdapter (Anthropic API); adapter factory with auto-detection (uses Claude if ANTHROPIC_API_KEY set, else NoOp); run_ai_assist runner with schema-validated outputs
- AI schema contracts: RegionTag, SkillInference, OCRCorrection, AdaptationSuggestion, AIResult — all Pydantic models
- No API keys needed — pipeline works fully without them; AI is optional assist
- Added anthropic to mypy ignore list
- `tests/test_adapter.py` — 17 tests: schema contracts (5), NoOp adapter (5), factory (5), AI assist runner (2)
- All 177 tests pass, lint clean, types clean

**Status:** All 15 checkpoints across 5 milestones implemented

### Session 12 — 2026-03-07 (AI Provider Integration + Testing)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Added OpenAI (GPT-5.4) and Gemini (3.1 Flash Lite) adapters for text tasks
- Added image generation: Gemini 3.1 Flash Image Preview (primary) + OpenAI gpt-image-1.5 (fallback)
- Set auto-detection priority: OpenAI > Gemini > Claude > NoOp
- Migrated from deprecated google.generativeai to google.genai SDK
- Fixed GPT-5.4 requiring max_completion_tokens instead of max_tokens
- Fixed gpt-image-1.5 not supporting response_format param (returns b64 by default)
- Added .env to .gitignore to protect API keys
- Integration tested all providers end-to-end: text and image generation confirmed working for both Gemini and OpenAI
- Added generate_image() top-level function with Gemini-first, OpenAI-fallback chain
- Added README.md with full project documentation
- Updated requirements.txt with openai, google-genai, python-dotenv
- All 189 tests pass, lint clean, types clean

### Session 13 — 2026-03-07 (Gemini Vision Fallback + E2E Real-World Test)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Added `extract/vision.py` — Gemini vision fallback for poor OCR results
- Quality gate: if OCR produces >80 fragments or avg confidence <0.5, send image to Gemini
- Gemini receives the actual worksheet image and returns structured JSON (template_type + regions)
- E2E tested on real UFLI Lesson 59 phone photo (two-page spread: word work + decodable story):
  - OCR-only: 113 fragments, wrong template (decodable_story), wrong domain (fluency), 8-page PDF
  - With Gemini fallback: 8 clean regions, correct template (word_work), correct skill (CVCe phonics), 2-page PDF
- Wired into transform.py pipeline automatically — no user intervention needed
- Gemini correctly identified both pages, prioritized word work page as planned
- All 189 tests pass, lint clean, types clean

### Session 14 — 2026-03-09 (Multi-Sensory Activities + Content-Driven Illustrations)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Implemented multi-worksheet adaptation engine and multi-format PDF rendering
- **Problem addressed:** UFLI Lesson 59 produced 15 items across 4 chunks, ALL "write" format. Decodable story dropped entirely. No variety.
- **Solution:** `adapt_lesson()` splits one lesson into 2-3 focused mini-worksheets:
  - Worksheet 1 "Word Discovery": match (word-picture), trace (dotted letters), circle (pattern recognition)
  - Worksheet 2 "Word Builder": word chains (write), fill-blank (missing vowels), sight words (write)
  - Worksheet 3 "Story Time": sentence completion (fill-blank with word bank), read-aloud passage, comprehension (circle)
- `adapt/schema.py` — Added `options`, `answer`, `picture_prompt` to ActivityItem; `worksheet_number/count/title`, `break_prompt` to AdaptedActivityModel
- `adapt/engine.py` — Added `adapt_lesson()` + 8 helper functions (discovery/builder/story chunk builders, distractor generation, fill-blank, sentence-to-blank, comprehension questions, word-to-picture prompts)
- `adapt/rules.py` — Added FORMAT_RENDERING metadata, BRAIN_BREAK_PROMPTS
- `render/pdf.py` — Added 7 new drawing functions: match tiles, trace letters, circle bubbles, fill-blank with word bank, read-aloud styled box, break prompts, two-column scene layout
- `render/pose_planner.py` — NEW: content-driven scene planning from chunk content
- `render/asset_gen.py` — NEW: AI asset generation with hash-based caching (Gemini Flash), graceful fallback
- `theme/schema.py` — Added AssetManifest model, multi_worksheet flag on ThemeConfig
- `theme/themes/roblox_obby/config.yaml` — NEW: multi_worksheet theme with integrated avatar
- `transform.py` — Split into single-worksheet (backward-compatible) and multi-worksheet pipeline branches
- `validate/adhd_compliance.py` — Added format variety check (Check 11) and worksheet time limit (Check 12)
- 20 new tests (12 adapt + 8 render), all 214 pass, lint clean, types clean
- **Fully backward compatible** — `adapt_activity()` and single-worksheet themes work unchanged

### Session 15 — 2026-03-09 (Rendering Quality Fixes + Word Picture Embedding)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Fixed `render/asset_gen.py` — migrated from deprecated `google.generativeai` SDK with unsupported `response_mime_type="image/png"` to `google.genai` SDK with `response_modalities=["TEXT", "IMAGE"]`, matching the working pattern in `companion/generate_overlays.py`. Uses reference character (`rainbow_roblox.png`) for scene consistency.
- Fixed text-image overlap in `render/pdf.py` — `_draw_chunk_with_scene()` now constrains text to a 60% content column via `content_left`/`content_right` parameters passed through `_draw_chunk()` and all item renderers. Scene images occupy 32% column on alternating sides with a gap. Text never enters the scene column.
- Embedded word pictures in match items — `_draw_match_item()` now accepts `asset_manifest` and renders actual AI-generated images (e.g., running dog for "chase", playground slide for "slide") instead of placeholder dashed boxes. Falls back to dashed placeholder when no manifest.
- All item renderers (`_draw_trace_item`, `_draw_circle_item`, `_draw_fill_blank_item`, `_draw_read_aloud_item`) now accept column bounds for constrained rendering.
- Added rendering quality check — `validate/print_checks.py` Check 6 uses PyMuPDF to detect text blocks overlapping with image bounding boxes (flags when >20% of text block area intersects an image). Runs automatically in pipeline.
- E2E tested: 11 AI images generated (7 character scenes + 4 word pictures), 0 text-image overlaps across all 3 worksheets, all validations pass
- All 214 tests pass, lint clean

### Session 16 — 2026-03-09 (ADHD-Optimized Typography)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Researched ADHD-friendly typography via Perplexity (sources: audioeye.com, neurodivergent.blog, reciteme.com, forbrain.com)
- Selected two free Google Fonts (OFL license, embedded in PDF):
  - **Fredoka** (headings) — rounded, fun, kid-friendly, clear letter differentiation
  - **Lexend** (body) — ADHD-optimized spacing, designed to reduce visual stress, clear b/d p/q I/l/1 differentiation
- Downloaded variable TTF files from `google/fonts` repo, stored in `assets/fonts/`
- `render/pdf.py` — registered fonts via `pdfmetrics.registerFont(TTFont(...))` with graceful fallback to Helvetica if TTFs not found
- Applied evidence-based ADHD spacing:
  - Line height: 1.7x font size (research shows 1.5x insufficient for ADHD)
  - Character spacing: 0.4pt body, 0.7pt headings (reduces visual crowding)
  - Word spacing: 1.5pt extra (aids tracking)
- Increased font sizes for K-1 (heading 20-22pt, body 16-18pt vs previous 16-18pt, 14-16pt)
- `theme/themes/roblox_obby/config.yaml` — updated to use Lexend/Fredoka
- Spacing applied via Canvas._charSpace/_wordSpace (setCharSpace/setWordSpace only on TextObject)
- All 214 tests pass, lint clean

### Session 17 — 2026-03-09 (Batch Processing with Rate-Limited API Orchestration)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Implemented batch processing CLI for bulk worksheet transformation
- `batch.py` — click CLI with `--input-dir`, `--profile`, `--theme`, `--output`, `--workers`, `--max-retries`, `--force`, `--dry-run`, `--no-images`, `--no-recursive`, `--rpm` options
- `batch_utils.py` — FileResult dataclass, RateLimiter (sliding-window token bucket, thread-safe via threading.Condition), ProgressTracker (thread-safe with ETA), collect_input_files, load/save manifest, generate_report
- Rate limiting: default 4 RPM to stay under Gemini's 5 RPM hard limit (Tier 1)
- Retry: exponential backoff (5s → 10s → 20s) + random jitter, configurable max retries
- Graceful shutdown: SIGINT handler lets running workers finish, cancels pending, writes partial report
- Skip detection: `batch_manifest.json` tracks completed files; re-runs skip automatically unless `--force`
- `--no-images` flag: sets `WORKSHEET_SKIP_ASSET_GEN=1` env var; 1-line check added to `render/asset_gen.py` returns None immediately. Enables bulk text-only processing (avoids 35 RPD image gen limit)
- `pipeline_fn` parameter on `_process_single_file` for testability (avoids pymupdf segfault from heavy transform module import under pytest)
- `tests/test_batch.py` — 25 tests covering all utilities and orchestration
- Updated Makefile (batch target), CLAUDE.md (batch CLI usage), README.md (batch processing section)
- All 239 tests pass (214 existing + 25 new), lint clean

### Session 18 — 2026-03-09 (CI Fixes — Lint + Type Errors)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Fixed all CI failures (lint + typecheck were failing, tests passing)
- **Ruff lint fixes (16 errors → 0):**
  - Removed unused imports across `batch_utils.py`, `companion/generate_overlays.py`, `tests/test_batch.py`, `tests/test_companion.py`
  - Fixed `UP017` — `timezone.utc` → `datetime.UTC` in `batch.py`
  - Fixed `I001` — sorted import blocks in `tests/test_batch.py`, `batch.py`
  - Fixed `E501` — line-length violations in `generate_overlays.py`, `complete.py`, `validate/ai_review.py`
  - Fixed `N806` — `MAX_OCR_SIDE` → `max_ocr_side` (local var in function) in `extract/ocr.py`
- **Mypy type fixes (39 errors → 0):**
  - Added type parameters to bare `dict` annotations in `batch_utils.py`, `validate/ai_review.py`, `companion/generate_overlays.py`
  - Fixed type conflict in `complete.py` — `equip_item`/`unequip_item` results shadowed `RewardResult`-typed variable
  - Changed `_display_catalog(profile: object)` → `_display_catalog(profile: LearnerProfile)`
  - Added `Callable` type alias for `pipeline_fn` in `batch.py` (was untyped `object`)
  - Changed `_validate_format_variety(list[object])` → `Sequence[AdaptedActivityModel]` in `transform.py`
  - Added `# type: ignore` for Gemini SDK incomplete type stubs (`generate_content` arg-type, `putdata` arg-type)
- All 239 tests still pass, lint clean, typecheck clean

### Session 19 — 2026-03-11 (Gemini Embedding 2 RAG Phases 1-6)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Created feature branch `codex/feature-gemini-embedding-2-rag` before implementation.
- Implemented RAG core package:
  - `rag/client.py` — Vertex AI client (`vertexai=True`) + `rag_available()` + model availability startup check.
  - `rag/embeddings.py` — `embed_text`, `embed_image`, `embed_pdf`, `embed_multimodal` with configurable dimensionality and task type.
  - `rag/store.py` — ChromaDB persistent store wrapper + collection helpers + query helper.
  - `rag/retrieval.py` — staged hybrid retrieval (skill-primary, content-secondary), grade filtering, dedup by `source_hash`.
  - `rag/indexer.py` — run artifact indexing for worksheets, skills, adaptations, exemplars; learner-name redaction before indexing text.
- Integrated retrieval-to-adaptation path in `adapt/engine.py`:
  - Added optional `rag_prior_adaptations` parameter to `adapt_activity()` and `adapt_lesson()` (backward-compatible defaults).
  - `_generate_distractors()` now supports blacklist from prior adaptations.
  - Added `_suggest_format_mix()` and `_extract_distractor_blacklist()` helpers.
  - Word Discovery format order can rotate when prior runs used same format mix.
- Integrated RAG in `transform.py` with non-blocking behavior:
  - Added `RunArtifacts` model for branch-agnostic indexing payload.
  - Added optional retrieval step before adaptation.
  - Added optional indexing step after single/multi branch completion.
  - Preserved `run_pipeline()` return type (`str` PDF path) for caller compatibility.
- Added tests:
  - `tests/test_rag_embeddings.py`
  - `tests/test_rag_store.py`
  - `tests/test_rag_retrieval.py`
  - `tests/test_rag_indexer.py`
  - `tests/test_rag_adapt.py`
- Updated config/deps:
  - `requirements.txt` adds `chromadb>=0.5`
  - `.gitignore` adds `vector_store/`
  - `pyproject.toml` adds mypy ignore for `chromadb.*`
- Validation status:
  - `ruff check .` ✅
  - `mypy .` ✅
  - `pytest tests -v --ignore=tests/test_e2e.py` ✅ (`247 passed, 3 skipped`)

**What's next:**
- Implement RAG Phase 7 modules: `rag/backfill.py` and `rag/eval.py`.
- Decide and implement batch main-thread indexing strategy from RAG plan phase 14.
- Optional docs pass for RAG usage/setup in `README.md` and `CLAUDE.md`.

### Session 20 — 2026-03-11 (GCP Project + Vertex Auth Setup for RAG)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Switched gcloud auth context to `howiejong@gmail.com` (user-provided account for project access).
- Verified target project exists and is active:
  - `ws-builder-rag` (`projectNumber: 715442045755`)
- Confirmed billing is linked (`billingEnabled: true`).
- Enabled required APIs on `ws-builder-rag`:
  - `aiplatform.googleapis.com`
  - `serviceusage.googleapis.com`
  - `iam.googleapis.com`
  - `iamcredentials.googleapis.com`
- Created runtime service account:
  - `worksheet-rag-runtime@ws-builder-rag.iam.gserviceaccount.com`
- Granted IAM bindings:
  - Service account → `roles/aiplatform.user`
  - Service account → `roles/serviceusage.serviceUsageConsumer`
  - User `howiejong@gmail.com` → `roles/serviceusage.serviceUsageConsumer` (for ADC quota project usage)
  - User `howiejong@gmail.com` on SA → `roles/iam.serviceAccountTokenCreator`
- Re-authenticated ADC as `howiejong@gmail.com` and set ADC quota project to `ws-builder-rag`.
- Updated local `.env` GCP setting:
  - `GOOGLE_CLOUD_PROJECT=ws-builder-rag`
- Verified live Vertex model availability check succeeded for:
  - `GEMINI_EMBEDDING_MODEL=gemini-embedding-2-preview`

**Current status:**
- Local machine is configured for Vertex-backed RAG embeddings against `ws-builder-rag`.
- Existing non-RAG Gemini paths in repo remain API-key based (auth migration still separate from RAG workstream).

### Session 21 — 2026-03-11 (A/B Evaluation Harness + RAG Context Quality Gating)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Implemented quality-first RAG context selection in `transform.py`:
  - Added `_select_rag_adaptation_context()` helper.
  - Adaptation now prefers `curated_exemplars` over generic `prior_adaptations`.
  - Curated exemplar retrieval is now deduped by `source_hash` (to avoid over-weighting one source).
  - Selected RAG metadata now includes `_rag_score` and `_rag_doc_id`.
  - Added `artifacts/rag_context.json` output for every run (selected source/count/avg score or retrieval error).
- Improved exemplar indexing in `rag/indexer.py`:
  - Exemplar metadata now includes primitive adaptation summary fields (e.g. `response_formats`, `estimated_minutes`, `distractor_words`) when available.
  - This allows curated exemplar retrieval to influence adaptation heuristics directly.
- Added deterministic paired A/B runner `ab_eval.py`:
  - Freezes Stage 1-4 per holdout target (`source_model.json` + `skill_model.json`).
  - Seeds vector store from non-target inputs.
  - Runs `A_no_rag` and `B_with_rag` from identical frozen artifacts.
  - Produces `scorecard.md` + `scorecard.json` and per-variant `rag_context.json`.
  - Supports `--clean-db`, `--seed`, and `--images/--no-images`.
- Updated docs:
  - `README.md` now includes A/B evaluation usage for `ab_eval.py`.
- Added/updated tests:
  - New `tests/test_transform_rag_context.py` for curated-vs-prior context selection behavior.
  - Updated `tests/test_rag_indexer.py` to assert exemplar metadata carries adaptation summary fields.
  - Updated `tests/test_rag_retrieval.py` to assert curated exemplar deduplication by `source_hash`.
- Validation run:
  - `.venv/bin/ruff check ...` on touched files ✅
  - `.venv/bin/mypy ...` on touched files ✅
  - `.venv/bin/pytest -q tests/test_transform_rag_context.py tests/test_rag_indexer.py tests/test_rag_retrieval.py` ✅ (13 passed)

**What's next:**
- Run `ab_eval.py` on a multi-target holdout set (not just `IMG_0004.JPG`) and review `scorecard.md`.
- Consider tightening retrieval filters further (domain/skill match in addition to grade) if B quality remains flat.
- Add learner-facing effectiveness rubric scoring (manual or evaluator-assisted) to complement validator flags.

### Session 22 — 2026-03-11 (A/B Harness Smoke Validation + Current Working State)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Ran end-to-end smoke test of `ab_eval.py`:
  - Command used (no seed): holdout `IMG_0004.JPG`, theme `roblox_obby`, `--no-images`.
  - Output root: `samples/output/ab_eval_smoke/20260311_170208`
  - Scorecard generated successfully:
    - `B selected source`: `curated_exemplars`
    - `B selected count`: `3`
    - Aggregate result: tie (`Delta score = 0`) for this single holdout.
- Verified run provenance files are emitted as designed:
  - Per variant `artifacts/rag_context.json`
  - Frozen artifacts under `frozen/artifacts/` (`source_model.json`, `skill_model.json`)
- Additional retrieval quality fix validated:
  - Curated exemplar retrieval deduplicates by `source_hash`.
  - Test coverage updated and passing.

**Current status (ready to run):**
- `ab_eval.py` is operational for deterministic paired A/B.
- RAG adaptation context now quality-gated (curated-first + deduped).
- Recommended next run is multi-target holdouts with seeding enabled to produce aggregate evidence.

### Session 23 — 2026-03-14 (UFLI Corpus Pipeline Execution)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Executed the UFLI corpus pipeline (crawl → acquire → extract → index):
  - **Crawl**: Successfully crawled all 15 UFLI Toolbox lesson group pages, captured 148 lessons into `data/ufli/manifest.jsonl`. Zero errors, ~60 seconds total with polite rate limiting.
  - **Acquire**: Downloaded 539 resource files across all 148 lesson directories. Hit macOS Python 3.13 SSL issue — `urllib.request.urlretrieve` fails because Python 3.13 ships without a default CA bundle. Fixed by adding `certifi` package and replacing `urlretrieve` with `urlopen(req, context=ssl_ctx)` + chunked file write. All 148 lessons marked `acquired`.
    - Resource breakdown: 148 PPTX slide decks, 131 decodable passage PDFs, 134 home practice PDFs, 126 additional activity PDFs
  - **Extract**: Successfully extracted text from all 148 lessons into `data/ufli/normalized.jsonl` using python-pptx (PPTX) and PyMuPDF (PDF).
  - **Index**: BLOCKED by Vertex AI permissions. The ADC user account gets 403 `PERMISSION_DENIED` on `aiplatform.endpoints.predict` for model `gemini-embedding-exp-03-07`. Re-authenticated ADC with `--project=ws-builder-rag` and quota project was accepted, but embedding calls still fail. Possible causes: (1) user IAM role missing `aiplatform.user`, (2) experimental model may need allowlist, (3) need service account key instead of user ADC.
- **Code changes**:
  - `corpus/ufli/acquire.py` — Added `certifi`, `ssl` imports; created `_SSL_CTX` with certifi CA bundle; replaced `urlretrieve` with `urlopen` + chunked write for SSL compatibility
- **Data on disk**:
  - `data/ufli/manifest.jsonl` — 148 records, all status `acquired`
  - `data/ufli/raw/` — 148 directories, 539 files (PPTX + PDF)
  - `data/ufli/normalized.jsonl` — 148 extracted lesson records
  - `vector_store/` — empty (indexing not yet completed)

**What's next:**
- Fix Vertex AI auth to unblock `ingest index` step. Options: (1) grant `roles/aiplatform.user` to `howiejong@gmail.com` on `ws-builder-rag`, (2) use service account key file, (3) try `GEMINI_EMBEDDING_MODEL=text-embedding-005` (GA model, not experimental), (4) switch to API key auth (`GOOGLE_API_KEY`) with non-Vertex client
- Once indexing works: `GOOGLE_CLOUD_PROJECT=ws-builder-rag python -m corpus.ufli.ingest index --data-dir ./data/ufli`
- The ingestion is idempotent — re-running is safe

### Session 24 — 2026-03-14 (RAG Backend Fallback Hardening + Successful Corpus Index)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Hardened the RAG embedding path to reduce dependence on the failing Vertex ADC setup:
  - `rag/client.py` now supports `RAG_GEMINI_BACKEND=auto|api_key|vertex`
  - Auto mode prefers `GOOGLE_API_KEY` / `GEMINI_API_KEY` when present, otherwise falls back to Vertex via `GOOGLE_CLOUD_PROJECT`
  - `rag/embeddings.py` now retries embedding requests across model candidates in order: configured model, `gemini-embedding-2-preview`, `text-embedding-005`
  - `corpus/ufli/ingest.py` now loads `.env`, so `python -m corpus.ufli.ingest ...` sees the same key/project config as `transform.py`
- Added regression coverage:
  - `tests/test_rag_client.py` — backend selection for api-key and Vertex modes
  - `tests/test_rag_embeddings.py` — fallback-to-next-model behavior
- Re-ran the live corpus index outside the sandbox after a sandbox DNS failure:
  - `python -m corpus.ufli.ingest index --data-dir ./data/ufli`
  - Auto-selected API-key backend from `.env`
  - Successfully embedded against `gemini-embedding-2-preview`
  - Indexed all 148 lessons into the `curriculum` collection in `vector_store/`
  - Verified local Chroma count: `148`
- Validation run:
  - `.venv/bin/pytest -q tests/test_rag_client.py tests/test_rag_embeddings.py tests/test_corpus_ingest.py` → `14 passed`
  - `.venv/bin/ruff check rag/client.py rag/embeddings.py corpus/ufli/ingest.py tests/test_rag_client.py tests/test_rag_embeddings.py` → clean
  - `.venv/bin/mypy rag/client.py rag/embeddings.py corpus/ufli/ingest.py tests/test_rag_client.py tests/test_rag_embeddings.py` → clean

**What's next:**
- Completed in Session 25: RAG Phase 7 module implementation (`rag/backfill.py`, `rag/eval.py`)
- Next remaining follow-up: consume `curriculum_references` in `adapt/engine.py` for curriculum-aware target-word validation

### Session 25 — 2026-03-14 (Phase 7 Modules: Backfill + Eval)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Implemented `rag/backfill.py`:
  - Scans artifact directories for `source_model.json`, `skill_model.json`, `adapted_model*.json`, `validation*.json`, and matching PDFs
  - Reconstructs `index_run()` payloads from saved artifacts rather than requiring a fresh pipeline run
  - Aggregates per-worksheet validation files for multi-worksheet runs
  - Resolves nested `artifacts/` directories back to their corresponding PDF output directories
- Implemented `rag/eval.py`:
  - Freezes extraction + skill per input using the existing A/B helper path
  - Computes retrieval@3 using current `RAGContext`
  - Runs baseline vs RAG variants and reports validator pass rate, format-change rate, unique RAG format sets, and distractor novelty
  - Writes both `report.json` and `report.md`
- Added focused tests:
  - `tests/test_rag_backfill.py`
  - `tests/test_rag_eval.py`
- Validation run:
  - `.venv/bin/pytest -q tests/test_rag_backfill.py tests/test_rag_eval.py tests/test_rag_client.py tests/test_rag_embeddings.py tests/test_rag_retrieval.py tests/test_corpus_ingest.py tests/test_retrieval_curriculum.py` → `25 passed`
  - `.venv/bin/ruff check rag/backfill.py rag/eval.py rag/__init__.py tests/test_rag_backfill.py tests/test_rag_eval.py` → clean
  - `.venv/bin/mypy rag/backfill.py rag/eval.py rag/__init__.py tests/test_rag_backfill.py tests/test_rag_eval.py` → clean

**What's next:**
- Integrate `curriculum_references` into `adapt/engine.py`
- Decide whether `rag/eval.py` should replace or complement `ab_eval.py`
- Run a real evaluation pass and, if useful, a live `rag.backfill` smoke run against saved outputs
