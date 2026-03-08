# Worksheet Builder — Running Context

> This is the running context document for session-to-session handoffs and multi-agent coordination.
> **Read this first** when starting a new session or picking up work.
> **Update this** at the end of every session with current state, decisions, and next steps.

---

## Current State

**Status:** All 5 milestones complete. Full pipeline + companion + AI assist layer implemented. 189 tests passing.
**Branch:** `main`
**Plan version:** 1.4.0
**Last Updated:** 2026-03-07

### Milestone Progress

| Milestone | Status | Checkpoints | Notes |
|-----------|--------|-------------|-------|
| M1: Foundation + Source Extraction | **Complete** | ~~1.1~~, ~~1.2~~, ~~1.3~~, ~~1.4~~ | All done |
| M2: Skill Extraction + ADHD Adaptation | **Complete** | ~~2.1~~, ~~2.2~~, ~~2.3~~, ~~2.4~~ | All done (2.2 merged into 2.1) |
| M3: Theme + Render + Validate + E2E | **Complete** | ~~3.1~~, ~~3.2~~, ~~3.3~~, ~~4.4~~ | All done |
| M4: Companion + Avatar | **Complete** | ~~4.1~~, ~~4.2~~, ~~4.3~~ | All done |
| M5: AI Assist + Generative | **Complete** | ~~5.1~~, ~~5.2~~, ~~5.3~~ | OpenAI + Gemini + Claude |

### What Exists Now
- `worksheet-builder-consolidated-plan.md` — full implementation plan (v1.4.0, 15 checkpoints)
- `CLAUDE.md` — project guidance for Claude Code
- `.gitignore` — excludes data dirs, python artifacts, IDE files, samples/input/
- `.claude/` — context doc, commands, skills
- `samples/input/` — 6 UFLI phone photos (gitignored, local only)
- `samples/output/` — 3 manually-created adapted worksheet examples (committed)
- `pyproject.toml` — ruff, mypy (strict), pytest config
- `requirements.txt` — all pipeline dependencies pinned
- `Makefile` — lint, typecheck, test, test-golden, test-all, format, clean
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
- `adapt/schema.py` — AdaptedActivityModel, ActivityChunk, ScaffoldConfig, Step, Example, ActivityItem
- `adapt/rules.py` — AccommodationRules, chunking tables, response format substitutions, color system
- `adapt/engine.py` — ADHD activity adaptation (chunking, instructions, worked examples, self-assessment)
- `tests/test_adapt.py` — 28 tests (profile, rules, adaptation engine, schema)
- `validate/schema.py` — ValidationResult, ValidationViolation models
- `validate/skill_parity.py` — skill-parity + age-band validation (domain, skill, grade, format checks)
- `validate/adhd_compliance.py` — 10 ADHD design rule checks (chunk size, instructions, decoration, scoring, etc.)
- `tests/test_validate.py` — 25 tests (skill parity, age band, ADHD compliance, schema)
- `theme/schema.py` — ThemeConfig, ThemeColors, ThemeFonts, ThemedModel models
- `theme/engine.py` — theme loading (YAML) + application; 3 built-in themes
- `theme/themes/space/config.yaml` — Space Adventure theme
- `theme/themes/underwater/config.yaml` — Ocean Explorer theme
- `theme/themes/dinosaur/config.yaml` — Dino Discovery theme
- `tests/test_theme.py` — 11 tests (theme loading, application, round-trip)
- `render/pdf.py` — ReportLab PDF renderer (letter size, margins, vector text, chunks, self-assessment)
- `validate/print_checks.py` — PDF print quality validation (dimensions, text, pages)
- `tests/test_render.py` — 12 tests (PDF rendering, print quality validation)
- `transform.py` — CLI entry point wiring full 8-stage pipeline
- `tests/test_smoke.py` — verifies all packages importable

- `companion/profile.py` — profile CRUD (create, update accommodations, ensure companion fields)
- `companion/catalog.py` — 15-item avatar catalog across 3 themes + universal
- `companion/rewards.py` — token economy (effort-based, milestone bonuses, purchase, equip/unequip)
- `companion/caregiver.py` — progress reports, accommodation adjustments
- `complete.py` — CLI entry point for completion, rewards, progress, accommodations
- `tests/test_companion.py` — 28 tests (profile, catalog, rewards, caregiver)

- `extract/adapter.py` — ModelAdapter protocol; OpenAI (GPT-5.4), Gemini (3.1 Flash Lite), Claude adapters; NoOpAdapter baseline; image generation (Gemini 3.1 Flash Image Preview primary, OpenAI gpt-image-1.5 fallback); auto-detection: OpenAI > Gemini > Claude > NoOp
- `tests/test_adapter.py` — 27 tests (schema contracts, adapters, factory, image gen, AI assist runner)
- `.env` — API keys (gitignored): OPENAI_API_KEY, GEMINI_API_KEY
- `README.md` — project documentation

### What's Next
**All milestones complete.** The engine is fully built. Remaining work:
- Real-world testing with UFLI phone photos
- Custom font embedding (Nunito TTF files)
- Avatar image composition (layered PNG/SVG rendering)
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

---

## Architecture Quick Reference

### Pipeline Stages & Data Flow
```
[1] Capture    → master page image (PNG)
[2] Normalize  → preprocessed image (OpenCV)
[3] Extract    → SourceWorksheetModel (Pydantic) — includes template_type
[4] Skill      → LiteracySkillModel (Pydantic) — dispatches by template_type
[5] Adapt      → AdaptedActivityModel (Pydantic) — companion fields Optional
[6] Theme      → themed model with decoration zones (avatar Optional for MVP)
[7] Render     → PDF (ReportLab, vector text, avatar Optional)
[8] Validate   → skill-parity, age-band, print, ADHD compliance
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
