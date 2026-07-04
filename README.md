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
10. **Package** merges all mini-worksheets into a single lesson PDF with a fun AI-generated cover page, "What's Inside" list, parent info strip, and global page numbering

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

# Renderer modes; default is image_gen (degrades to pdf_classic offline)
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output/ --render-mode pdf_classic
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output-hybrid/ --render-mode hybrid_shell
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output-prompts/ --render-mode image_prompt

# Optional live RAG experiment; default transforms do not retrieve vector context
WORKSHEET_USE_RAG=1 python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output-rag/

# Batch process a folder of worksheets
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme roblox_obby --output ./output-prompts/ --render-mode image_prompt

# Mark completion and award tokens
python complete.py --profile profiles/ian.yaml --lesson 5

# Backfill saved artifacts into the RAG store
python -m rag.backfill --artifacts-dir ./samples/output --output-dir ./samples/output

# Evaluate retrieval and baseline-vs-RAG behavior
python -m experiments.rag.eval --test-dir ./samples/input --profile profiles/ian.yaml

# Build UFLI audio companion lesson bundles (pilot_rep: 6 lessons)
python -m corpus.ufli.ingest build-audio

# Estimate pilot audio generation cost and clip counts without calling ElevenLabs
python -m corpus.ufli.ingest generate-audio --dry-run

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
| Render | `render/pdf.py` + `render/merge.py` | Themed model | PDF file (merged lesson package for multi-worksheet) |
| Validate | `validate/*.py` | All models + PDF | `ValidationResult` |

All pipeline stages communicate through strict Pydantic contracts. The pipeline is idempotent: same inputs always produce the same outputs.

### Renderer modes and image-model readiness

The production default renderer is `image_gen` (decision D29): a full-page
AI-generated worksheet, gated by text-fidelity and character-consistency judges,
cached, and wrapped as a searchable PDF. It degrades to `pdf_classic` whenever no
image provider is available (no API keys or `WORKSHEET_SKIP_ASSET_GEN=1`), so
offline runs still produce a deterministic PDF.

`pdf_classic` remains the explicit opt-out (`--render-mode pdf_classic`): it uses
deterministic ReportLab vector text, existing scene assets, and PDF validation.

Other opt-in renderer modes keep the pipeline ready for improving image models:

- `hybrid_shell` — experimental PDF mode that keeps deterministic text/layout
  while routing through the renderer strategy interface for future visual-shell
  work.
- `image_prompt` — offline prompt-only mode. It writes provider-ready
  `worksheet_image_prompt.md` and `renderer_manifest.json` artifacts, but does
  not call an image-generation API and does not claim to produce a print-ready
  PDF.

All renderers consume the same `WorksheetDesignSpec`, which preserves exact
required text, answer zones, page geometry, learner theme preferences, and the
ADHD visual budget. Future full-page image renderers can plug into the same
interface without changing extraction, skill modeling, adaptation, or validation.

Experimental image renderers must pass the renderer benchmark promotion gates
before they can become production defaults: exact required text present, answer
zones represented, ADHD visual budget respected, and print-ready output
produced. Prompt-only `image_prompt` is useful for model trials but intentionally
fails the print-ready promotion gate until a real provider output is validated.

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

The multi-worksheet pipeline automatically merges all mini-worksheets into a **single lesson PDF** with:
- **AI-generated cover page** — fun thematic illustration (Gemini Flash Image), bold lesson title, "What's Inside" worksheet list for the child, parent/teacher info strip at the bottom
- **Global page numbering** — "Page X of Y" on every content page (not on the cover)

```bash
# Produces a single lesson PDF: lesson_{hash}.pdf (cover + 3 worksheets)
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme roblox_obby --output ./output/
```

Cover image generation is optional — the cover page falls back to a theme-colored placeholder if no API key is set or `WORKSHEET_SKIP_ASSET_GEN=1`.

Single-worksheet mode (`--theme space`) works exactly as before — fully backward compatible.

### Batch processing

Process an entire folder of worksheet photos at once with rate limiting and retry logic:

```bash
# Basic batch run (2 workers, 4 RPM limit)
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space --output ./output/

# Without AI images (fast bulk run, avoids 35 RPD image gen limit)
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme roblox_obby --output ./output/ --no-images

# Prompt-only image model trial artifacts
python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme roblox_obby --output ./output-prompts/ --render-mode image_prompt

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
| `--render-mode` | pdf_classic | Renderer mode: `pdf_classic`, `hybrid_shell`, or `image_prompt` |
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
python -m experiments.batteries.ab_eval \
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

### Optional RAG memory and evaluation

The default transform path does not retrieve vector curriculum context. It relies
on direct worksheet extraction plus corpus lookup enrichment from the skill and
adaptation stages. Live RAG retrieval is available only for experiments:

```bash
WORKSHEET_USE_RAG=1 python transform.py \
  --input photo.jpg \
  --profile profiles/ian.yaml \
  --theme roblox_obby \
  --output ./output-rag/
```

RAG remains useful as optional memory and eval tooling:

```bash
# Backfill previously generated outputs into the vector store
python -m rag.backfill \
  --artifacts-dir ./samples/output \
  --output-dir ./samples/output \
  --db-path vector_store

# Evaluate retrieval quality and baseline-vs-RAG differences
python -m experiments.rag.eval \
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

`experiments.rag.eval` and `experiments.batteries.ab_eval` call `retrieve_context()` directly and do not depend
on `WORKSHEET_USE_RAG`. `experiments.rag.eval` freezes extraction and skill inference per input, measures
`retrieval@3`, compares baseline vs RAG validator pass rate, tracks whether the
RAG variant changes response-format sets, and estimates distractor novelty from
retrieved prior adaptations.

Current RAG operational notes:
- The curriculum store is already populated with 148 indexed UFLI lessons.
- Live transform retrieval requires `WORKSHEET_USE_RAG=1`.
- Eval/backfill embedding currently works via API-key auto-selection from `.env`.
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

### UFLI audio companion

The repo includes a pilot-first audio companion pipeline for numeric UFLI lessons
`1-128`. Audio is designed as support for explicit reading instruction, not a
replacement for decoding instruction.

**Current scope (Stage 2 — representative pilot):**
- Pilot lessons: `1`, `14`, `34`, `64`, `95`, `128`
- Winning voice: `dorothy` (ElevenLabs `eleven_multilingual_v2`)
- Indexed clip taxonomy:
  - `lesson_instruction`
  - `phoneme_model`
  - `word_model`
  - `passage_sentence`
  - `passage_full`
  - `review`
- Two Chroma collections: `audio_companion_clips` (per-clip) and `audio_companion_lessons` (per-lesson aggregate)
- `encouragement` is not indexed as lesson content
- Generation stays offline by default unless `--live` is passed

Committed companion config lives under `data/ufli/companion/`:
- `pronunciation_lexicon.yaml`
- `voice_profiles.yaml`
- `pilot_lessons.yaml`

Core commands:

```bash
# Build voice-neutral lesson bundles (defaults to pilot_rep: 6 lessons)
python -m corpus.ufli.ingest build-audio

# Validate built bundles
python -m corpus.ufli.ingest validate-audio

# Dry-run estimation for pilot voices
python -m corpus.ufli.ingest generate-audio --dry-run

# Live-generate with Dorothy
python -m corpus.ufli.ingest generate-audio \
  --voice-profile dorothy \
  --live \
  --review-packet

# Index into both clip-level and lesson-level collections
python -m corpus.ufli.ingest index-audio \
  --voice-profile dorothy \
  --granularity both

# Judge generated clips with Gemini
python -m corpus.ufli.ingest judge-audio \
  --voice-profile dorothy

# Run controlled diagnostic probes on hard clips
python -m corpus.ufli.ingest diagnose-audio \
  --voice-profile dorothy
```

`generate-audio --review-packet` writes a timestamped packet under
`data/ufli/companion/pilots/<timestamp>/` containing:
- `review.md`
- `review.csv`
- `clips.json`
- `playlist.m3u`
- generated audio files

### UFLI audio MVP test packet

The smallest evaluation packet for checking whether the TTS companion is better
than no TTS lives under `data/ufli/companion/mvp_test/`:

- `facilitator_script.md`
- `child_score_sheet.csv`
- `adult_observation_rubric.md`
- `summary_template.md`

This packet is structured around a `No TTS` vs `TTS Companion` crossover test
and explicitly preserves decoding-first instruction.

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
make test        # pytest (418 tests)
make format      # ruff format .
make clean       # rm -rf artifacts/ __pycache__ .mypy_cache
```

### Quality gates

Before merging worksheet quality changes, run:

```bash
make lint
make typecheck
make test
make test-golden
```

Fixture-backed quality cases must report no blocking issues: content coverage,
ADHD compliance, skill parity, Learning Buddy identity checks when required,
and print quality all need to pass.

Renderer benchmark reports must also pass before promoting an experimental
renderer. The promotion gates are intentionally stricter for full-page image
models: they must preserve exact worksheet text and answer affordances while
meeting ADHD visual-budget and print-readiness requirements.

### Project layout

```
capture/        Image preprocessing + master storage
extract/        OCR + heuristics + Gemini vision fallback + AI adapter
skill/          K-3 literacy skill taxonomy + extraction
adapt/          ADHD activity adaptation + accommodation rules
theme/          Calm theme engine + 3 built-in themes
companion/      Learner profiles, avatar catalog, token economy, caregiver
render/         ReportLab vector PDF generation + scene planning + AI asset generation + PDF merge
validate/       Skill-parity, ADHD compliance, format variety, print quality, AI quality review
transform.py    CLI: transform worksheets (full pipeline)
complete.py     CLI: mark completion, manage rewards and accommodations
```

### Testing

418 tests covering all pipeline stages:

```
tests/test_capture.py     11 tests — preprocessing, storage, archival PDF
tests/test_extract.py     13 tests — template detection, region classification
tests/test_skill.py       31 tests — taxonomy, extraction (phonics, fluency, generic)
tests/test_adapt.py       40 tests — profile, rules, adaptation engine, multi-worksheet
tests/test_validate.py    25 tests — skill parity, age band, ADHD compliance
tests/test_theme.py       11 tests — theme loading, application
tests/test_render.py      21 tests — PDF rendering, cover page, multi-format rendering, print quality
tests/test_merge.py        4 tests — PDF merge, page stamping, cleanup
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
