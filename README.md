# Worksheet Builder

A skill-preserving worksheet adaptation engine for children ages 5-8 with ADHD. Transforms physical paper literacy worksheets (phone photos or scans) into ADHD-optimized, themed, print-ready PDF activities.

## What it does

```
Phone photo of worksheet  -->  ADHD-adapted, themed PDF
```

1. **Capture** a worksheet with your phone camera
2. **OCR** extracts text, detects the worksheet template (UFLI word work or decodable story)
3. **Skill extraction** identifies the literacy skill being taught (phonics, fluency, etc.)
4. **ADHD adaptation** chunks content, adds scaffolding, worked examples, and self-assessment
5. **Theme** applies a calm visual theme (Space, Underwater, or Dinosaur)
6. **Render** produces a print-ready PDF with vector text
7. **Validate** checks skill preservation, ADHD compliance, and print quality

The pipeline is fully deterministic — no API keys required. AI assist (Claude, Gemini, or OpenAI) is optional and enhances extraction on unfamiliar layouts.

## Quick start

```bash
# Clone and setup
git clone https://github.com/howardjong/worksheet-builder.git
cd worksheet-builder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Transform a worksheet
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme space --output ./output/

# Mark completion and award tokens
python complete.py --profile profiles/ian.yaml --lesson 5

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

Auto-detection priority: **OpenAI > Gemini > Claude > NoOp**. No keys = deterministic-only mode (works fine).

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
| Text tasks | OpenAI GPT-5.4 | Gemini 3.1 Flash Lite / Claude |
| Image generation | Gemini 3.1 Flash Image Preview | OpenAI gpt-image-1.5 |

## ADHD design principles

The engine follows evidence-consistent ADHD design rules:

- **Game-themed structure, visually calm execution** — levels and XP labels motivate, but the visual field stays clean
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
Paper → [1] Capture → [2] Normalize → [3] Extract → [4] Skill → [5] Adapt → [6] Theme → [7] Render → [8] Validate
```

| Stage | Module | Input | Output |
|-------|--------|-------|--------|
| Capture | `capture/preprocess.py` | Phone photo | Cleaned image |
| Store | `capture/store.py` | Cleaned image | Hash-named master |
| Extract | `extract/ocr.py` + `heuristics.py` + `vision.py` | Image | `SourceWorksheetModel` |
| Skill | `skill/extractor.py` | Source model | `LiteracySkillModel` |
| Adapt | `adapt/engine.py` | Skill + Profile | `AdaptedActivityModel` |
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

### Gemini vision fallback

When OCR produces poor results (>80 fragmented text blocks or low confidence), the pipeline automatically sends the worksheet image to Gemini for vision-based extraction. Gemini analyzes the photo directly and returns structured regions — dramatically improving accuracy on real phone photos.

```
OCR (PaddleOCR/Tesseract) → quality check → if poor → Gemini vision → SourceWorksheetModel
                                           → if good → heuristics    → SourceWorksheetModel
```

Tested on a real UFLI Lesson 59 phone photo (two-page spread):
- OCR alone: 113 fragments, wrong template, wrong skill, 8-page PDF
- With Gemini fallback: 8 clean regions, correct template, correct skill, 2-page PDF

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

Three built-in calm themes with functional color coding:

| Theme | Name | Accent |
|-------|------|--------|
| `space` | Space Adventure | Blue/amber on near-white |
| `underwater` | Ocean Explorer | Ocean blue on light blue |
| `dinosaur` | Dino Discovery | Green/brown on warm white |

Themes change only visual elements — content and structure remain identical. Add custom themes by creating a `config.yaml` in `theme/themes/<name>/`.

## Development

```bash
make lint        # ruff check .
make typecheck   # mypy . (strict mode)
make test        # pytest (189 tests)
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
render/         ReportLab vector PDF generation
validate/       Skill-parity, ADHD compliance, print quality validators
transform.py    CLI: transform worksheets (full pipeline)
complete.py     CLI: mark completion, manage rewards and accommodations
```

### Testing

189 tests covering all pipeline stages:

```
tests/test_capture.py     11 tests — preprocessing, storage, archival PDF
tests/test_extract.py     13 tests — template detection, region classification
tests/test_skill.py       31 tests — taxonomy, extraction (phonics, fluency, generic)
tests/test_adapt.py       28 tests — profile, rules, adaptation engine
tests/test_validate.py    25 tests — skill parity, age band, ADHD compliance
tests/test_theme.py       11 tests — theme loading, application
tests/test_render.py      12 tests — PDF rendering, print quality
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
