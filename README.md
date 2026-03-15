# Worksheet Builder

A skill-preserving worksheet adaptation engine for children ages 5-8 with ADHD. Transforms physical paper literacy worksheets (phone photos or scans) into ADHD-optimized, themed, print-ready PDF activities.

## What it does

```
Phone photo of worksheet  -->  ADHD-adapted, themed PDF
```

1. **Capture** a worksheet with your phone camera
2. **AI vision** (Gemini) analyzes the photo and extracts structured content — OCR is the fallback if no API key
3. **Skill extraction** identifies the literacy skill being taught (phonics, fluency, etc.)
4. **ADHD adaptation** chunks content into multi-sensory activities with varied response types (match, trace, circle, fill-blank, write, read-aloud)
5. **AI quality review** iteratively evaluates the adapted worksheet for correctness before rendering
6. **Multi-worksheet split** produces 2-3 focused mini-worksheets per lesson (Word Discovery, Word Builder, Story Time) with brain breaks between them
7. **Theme** applies a calm visual theme (Space, Underwater, Dinosaur, or Roblox Obby Quest)
8. **Render** produces print-ready PDFs with vector text, word-picture matching tiles, traceable letters, and styled reading boxes
9. **Validate** checks skill preservation, ADHD compliance, format variety, and print quality

AI vision (Gemini) is the primary extraction mode — dramatically more accurate than OCR on phone photos. The pipeline falls back to OCR if no API key is set. AI quality review catches structural issues before the final PDF is generated.

## Quick start

```bash
# Clone and setup
git clone https://github.com/howardjong/worksheet-builder.git
cd worksheet-builder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Transform a worksheet (single PDF)
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme space --output ./output/

# Transform into multi-worksheet set (3 mini-worksheets with varied activities)
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output/

# Batch process a folder of worksheets
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/

# Mark completion and award tokens
python complete.py --profile profiles/ian.yaml --lesson 5

# Backfill saved artifacts into the RAG store
python -m rag.backfill --artifacts-dir ./samples/output --output-dir ./samples/output

# Evaluate retrieval and baseline-vs-RAG behavior
python -m rag.eval --test-dir ./samples/input --profile profiles/ian.yaml

# View progress
python complete.py --profile profiles/ian.yaml --progress
```

### Create a learner profile

```python
from companion.profile import create_profile

profile = create_profile(name="Ian", grade_level="1", base_character="robot")
# Saves to profiles/ian.yaml
```

### Optional: AI assist

Set an API key in your environment (or `.env` file) to enable AI-enhanced extraction:

```bash
export OPENAI_API_KEY="your-key"      # Primary — GPT-5.4 for text tasks
export GEMINI_API_KEY="your-key"      # Gemini 3.1 Flash Lite for text + image generation
export ANTHROPIC_API_KEY="your-key"   # Claude as fallback
```

Extraction priority: **Gemini vision (primary) > OCR fallback**. Quality review: **Gemini 2.5 Flash (primary) > GPT-5.4 fallback**. No keys = OCR-only mode (still works).

### AI image generation

Generate custom avatar items and theme assets:

```python
from extract.adapter import generate_image

# Tries Gemini first, falls back to OpenAI, returns None if no keys
path = generate_image(
    "A friendly robot character, flat color, white background",
    "assets/robot.png"
)
```

| Capability | Primary | Fallback |
|---|---|---|
| Worksheet extraction | Gemini 3.1 Flash Lite (vision) | PaddleOCR / Tesseract |
| Quality review | Gemini 2.5 Flash | GPT-5.4 |
| Text tasks | OpenAI GPT-5.4 | Gemini 3.1 Flash Lite / Claude |
| Image generation | Gemini 3.1 Flash Image Preview | OpenAI gpt-image-1.5 |

## ADHD design principles

The engine follows evidence-consistent ADHD design rules:

- **Game-themed structure, visually calm execution** — levels and XP labels motivate, but the visual field stays clean
- **Multi-sensory activities** — word-picture matching, letter tracing, word circling, fill-in-the-blank, writing, and read-aloud — varied formats produce 40% greater gains over isolated read/write
- **Multi-worksheet split** — one lesson becomes 2-3 focused mini-worksheets (5-8 min each) with brain breaks
- **Chunked content** — 2-3 items per chunk (K) up to 5-8 (Grade 3), ~3-7 minutes each
- **Effort-based rewards** — tokens for completing and trying, never for accuracy or speed
- **Predictable layout** — instructions always top-left, examples in shaded box, consistent placement
- **Decoration budget** — max 2 decorative elements per page, unlimited functional visuals
- **Self-assessment** — "I can..." / "I'm still learning" checklist at the end

### Anti-patterns (enforced by validators)

- No dense text blocks or cluttered pages
- No accuracy-based or speed-based scoring
- No leaderboards, streak punishment, or loot boxes
- No patterned backgrounds behind text
- No multiple characters or scattered decorations

## Architecture

```
Paper → [1] Capture → [2] Store → [3] Extract (AI vision / OCR) → [4] Skill → [5] Adapt → [5b] AI Review → [6] Theme → [7] Render → [8] Validate
```

| Stage | Module | Input | Output |
|-------|--------|-------|--------|
| Capture | `capture/preprocess.py` | Phone photo | Cleaned image |
| Store | `capture/store.py` | Cleaned image | Hash-named master |
| Extract | `extract/vision.py` (primary) or `extract/ocr.py` + `heuristics.py` (fallback) | Image | `SourceWorksheetModel` |
| Skill | `skill/extractor.py` | Source model | `LiteracySkillModel` |
| Adapt | `adapt/engine.py` | Skill + Profile | `AdaptedActivityModel` (single) or `list[AdaptedActivityModel]` (multi) |
| AI Review | `validate/ai_review.py` | Adapted model | Reviewed/fixed `AdaptedActivityModel` |
| Theme | `theme/engine.py` | Adapted model | `ThemedModel` |
| Render | `render/pdf.py` | Themed model | PDF file |
| Validate | `validate/*.py` | All models + PDF | `ValidationResult` |

All pipeline stages communicate through strict Pydantic contracts. The pipeline is idempotent: same inputs always produce the same outputs.

### AI assist boundary

All AI calls go through `extract/adapter.py` behind a `ModelAdapter` protocol. Three providers included:

- **OpenAIAdapter** — GPT-5.4 for text tasks (primary)
- **GeminiAdapter** — Gemini 3.1 Flash Lite for text tasks + Gemini 3.1 Flash Image Preview for asset generation
- **ClaudeAdapter** — Anthropic Claude API
- **NoOpAdapter** — deterministic baseline (default when no keys set)

AI outputs are schema-validated before entering the pipeline. The pipeline produces valid, complete results with or without AI.

### AI vision extraction

Gemini vision is the primary extraction mode. The pipeline sends the worksheet photo directly to Gemini 3.1 Flash Lite, which analyzes the image and returns structured regions (concept labels, word chains, sentences, etc.). OCR (PaddleOCR/Tesseract) is only used as a fallback when no API key is available.

```
Photo → Gemini vision (primary) → SourceWorksheetModel
      → OCR fallback (no API key) → heuristics → SourceWorksheetModel
```

Tested on a real UFLI Lesson 59 phone photo (two-page spread):
- OCR alone: 113 fragments, wrong template, wrong skill, 8-page PDF
- Gemini vision: 10 clean regions, correct template, correct skill, 2-page PDF

### AI quality review

After ADHD adaptation (Stage 5), the pipeline sends the adapted worksheet to AI for iterative quality review (up to 3 iterations). The reviewer checks for structural issues — truncated text, formatting artifacts, ADHD anti-patterns — while preserving the original source content.

```
Adapted model → AI review → fix issues → re-review → ... → final adapted model
```

The review is conservative: it flags structural problems but never substitutes the source words (which are the learning targets from the original worksheet). Review uses Gemini 2.5 Flash (primary) with GPT-5.4 as fallback.

### Multi-worksheet mode

When using a theme with `multi_worksheet: true` (e.g., `roblox_obby`), one lesson is split into 2-3 focused mini-worksheets:

| Worksheet | Title | Activities | Time |
|-----------|-------|-----------|------|
| 1 | Word Discovery | Word-picture matching, letter tracing, word circling | ~5 min |
| 2 | Word Builder | Word chains, fill-in-the-blank, sight word practice | ~5 min |
| 3 | Story Time | Sentence completion, read-aloud passage, comprehension | ~8 min |

Each worksheet ends with a brain break prompt ("Stand up and stretch!", "Do 5 jumping jacks!"). This addresses the key problem where UFLI Lesson 59 produced 15 items across 4 chunks, all with "write" response format — research shows varied multi-sensory activities produce 40% greater gains.

```bash
# Produces 3 PDFs: worksheet_..._1of3.pdf, worksheet_..._2of3.pdf, worksheet_..._3of3.pdf
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output/
```

Single-worksheet mode (`--theme space`) works exactly as before — fully backward compatible.

### Batch processing

Process an entire folder of worksheet photos at once with rate limiting and retry logic:

```bash
# Basic batch run (2 workers, 4 RPM limit)
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/

# Without AI images (fast bulk run, avoids 35 RPD image gen limit)
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme roblox_obby --output ./output/ --no-images

# Dry run — list files without processing
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --dry-run

# Force reprocess already-completed files
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/ --force

# Custom workers and rate limit
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --workers 1 --rpm 3
```

| Option | Default | Description |
|--------|---------|-------------|
| `--workers` | 2 | Concurrent pipeline workers |
| `--max-retries` | 2 | Retries per file on failure (exponential backoff) |
| `--rpm` | 4 | Rate limit: max pipeline runs per minute |
| `--force` | off | Reprocess even if output exists |
| `--dry-run` | off | List files without processing |
| `--no-images` | off | Skip AI image generation (text-only PDFs) |
| `--no-recursive` | off | Don't search subdirectories |

**Rate limiting:** Gemini image generation is capped at 5 RPM / 35 RPD on Tier 1. The default 4 RPM stays safely under the per-minute limit. For 30+ worksheets with images, run `--no-images` first, then selectively regenerate the most important 4 lessons with images (staying under 35 RPD).

**Skip detection:** Batch writes a `batch_manifest.json` in the output directory. Re-runs automatically skip files that already have output PDFs. Use `--force` to override.

**Graceful shutdown:** Press Ctrl+C during a batch run. Running workers finish their current file, pending work is cancelled, and a partial report is generated.

### A/B evaluation (RAG vs no RAG)

Run paired A/B experiments with Stage 1-4 frozen (capture/extraction/skill),
so differences come from adaptation + retrieval instead of OCR/vision drift:

```bash
# Example: hold out IMG_0004.JPG, seed store from other IMG_* files
python ab_eval.py \
  --input-dir ./samples/input \
  --include "IMG_*" \
  --target IMG_0004.JPG \
  --profile profiles/ian.yaml \
  --theme roblox_obby \
  --output-root ./samples/output/ab_eval \
  --db-path vector_store \
  --seed \
  --no-images
```

Outputs include:
- `scorecard.md` and `scorecard.json` with per-target A/B deltas
- Per-variant `artifacts/rag_context.json` showing retrieval provenance
- Frozen `source_model.json` + `skill_model.json` for reproducible reruns

### RAG backfill and evaluation

Phase 7 adds two maintenance/evaluation commands on top of the live RAG path:

```bash
# Backfill previously generated outputs into the vector store
python -m rag.backfill \
  --artifacts-dir ./samples/output \
  --output-dir ./samples/output \
  --db-path vector_store

# Evaluate retrieval quality and baseline-vs-RAG differences
python -m rag.eval \
  --test-dir ./samples/input \
  --profile profiles/ian.yaml \
  --theme roblox_obby \
  --db-path vector_store \
  --output-root ./samples/output/rag_eval \
  --no-images
```

`rag.backfill` scans saved `artifacts/` directories for `source_model.json`,
`skill_model.json`, `adapted_model*.json`, `validation*.json`, and matching
PDFs, then reconstructs indexing payloads using the same `index_run()` path as
live pipeline runs.

`rag.eval` freezes extraction and skill inference per input, measures
`retrieval@3`, compares baseline vs RAG validator pass rate, tracks whether the
RAG variant changes response-format sets, and estimates distractor novelty from
retrieved prior adaptations.

Current RAG operational notes:
- The curriculum store is already populated with 148 indexed UFLI lessons.
- Live embedding currently works via API-key auto-selection from `.env`.
- Vertex fallback remains supported through `RAG_GEMINI_BACKEND=vertex`.

## Companion layer

Beyond worksheet transformation, the companion layer provides:

- **Learner profiles** — grade level, accommodation preferences, YAML storage
- **Avatar customization** — base characters, unlockable items across themes
- **Token economy** — 10 tokens per worksheet, milestone bonuses every 5, effort-based
- **Item catalog** — 15 items across Space, Underwater, Dinosaur themes + universal
- **Caregiver controls** — progress reports, accommodation adjustments

```bash
# Award completion
python complete.py --profile profiles/ian.yaml --lesson 43

# Buy an item
python complete.py --profile profiles/ian.yaml --buy space_helmet

# Adjust accommodations
python complete.py --profile profiles/ian.yaml --set-chunking small
```

## Themes

Four built-in calm themes with functional color coding:

| Theme | Name | Multi-worksheet | Accent |
|-------|------|-----------------|--------|
| `space` | Space Adventure | No | Blue/amber on near-white |
| `underwater` | Ocean Explorer | No | Ocean blue on light blue |
| `dinosaur` | Dino Discovery | No | Green/brown on warm white |
| `roblox_obby` | Roblox Obby Quest | **Yes** | Blue/amber, integrated character scenes |

Themes change only visual elements — content and structure remain identical. Themes with `multi_worksheet: true` produce 2-3 mini-worksheets per lesson with varied activity types. Add custom themes by creating a `config.yaml` in `theme/themes/<name>/`.

## Development

```bash
make lint        # ruff check .
make typecheck   # mypy . (strict mode)
make test        # pytest (214 tests)
make format      # ruff format .
make clean       # rm -rf artifacts/ __pycache__ .mypy_cache
```

### Project layout

```
capture/        Image preprocessing + master storage
extract/        OCR + heuristics + Gemini vision fallback + AI adapter
skill/          K-3 literacy skill taxonomy + extraction
adapt/          ADHD activity adaptation + accommodation rules
theme/          Calm theme engine + 3 built-in themes
companion/      Learner profiles, avatar catalog, token economy, caregiver
render/         ReportLab vector PDF generation + scene planning + AI asset generation
validate/       Skill-parity, ADHD compliance, format variety, print quality, AI quality review
transform.py    CLI: transform worksheets (full pipeline)
complete.py     CLI: mark completion, manage rewards and accommodations
```

### Testing

214 tests covering all pipeline stages:

```
tests/test_capture.py     11 tests — preprocessing, storage, archival PDF
tests/test_extract.py     13 tests — template detection, region classification
tests/test_skill.py       31 tests — taxonomy, extraction (phonics, fluency, generic)
tests/test_adapt.py       40 tests — profile, rules, adaptation engine, multi-worksheet
tests/test_validate.py    25 tests — skill parity, age band, ADHD compliance
tests/test_theme.py       11 tests — theme loading, application
tests/test_render.py      20 tests — PDF rendering, multi-format rendering, print quality
tests/test_companion.py   28 tests — profile CRUD, catalog, rewards, caregiver
tests/test_adapter.py     29 tests — AI adapter contracts, factory, image gen, providers
tests/test_smoke.py        1 test  — all packages importable
```

## Dependencies

### Core (required)

| Package | Purpose |
|---------|---------|
| `opencv-python-headless` | Image preprocessing (deskew, dewarp, denoise) |
| `paddleocr` | Primary OCR engine |
| `pytesseract` | Fallback OCR (requires `tesseract-ocr` binary) |
| `reportlab` | Vector PDF generation |
| `PyMuPDF` | PDF validation and inspection |
| `Pillow` | Image manipulation |
| `pydantic` | Schema validation for all data contracts |
| `click` | CLI framework |
| `PyYAML` | Profile and config storage |

### AI assist (optional)

| Package | Purpose |
|---------|---------|
| `openai` | GPT-5.4 text tasks + gpt-image-1.5 image generation |
| `google-genai` | Gemini 3.1 Flash Lite text + Flash Image Preview generation |
| `python-dotenv` | Load API keys from `.env` file |

### Dev

| Package | Purpose |
|---------|---------|
| `pytest` | Testing |
| `mypy` | Type checking (strict) |
| `ruff` | Linting + formatting |

## Input support

Currently optimized for **UFLI Foundations Home Practice** worksheets:

- **Word Work pages** — concept label, sample words, word chains, chain script, irregular words, practice sentences
- **Decodable Story pages** — story title, decodable passage

The heuristic engine detects template type automatically. Unknown layouts fall back to generic extraction with reduced confidence. The AI adapter can enhance extraction on unfamiliar worksheets.

## License

Private repository. All rights reserved.
