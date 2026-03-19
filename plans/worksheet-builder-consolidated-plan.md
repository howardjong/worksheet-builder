# Worksheet Builder: Skill-Preserving ADHD Worksheet Adaptation Engine

## STATUS: PLANNING

**Repository:** `https://github.com/howardjong/worksheet-builder.git`
**Branch:** `main` (initial build)
**Language:** Python 3.11+
**Target Users:** Parents/caregivers of children ages 5-8 with ADHD; teachers supporting ADHD learners
**Primary Goal:** Build a deterministic pipeline that transforms physical paper literacy worksheets into ADHD-optimized, themed, print-ready activities with progressive avatar engagement
**Primary input family:** UFLI Foundations Home Practice worksheets — two known page templates:
  - **Word Work page** (left side): New Concept & Sample Words, Word Work Chains, Word Chain Script, New Irregular Words, Sentences
  - **Decodable Story page** (right side): illustration box + decodable passage with target-pattern words
**Constraint:** No proprietary curriculum content redistributed in outputs; system reads UFLI as input signal but produces original, skill-preserving adapted activities. UFLI pages may be used as private, user-supplied inputs for local transformation, but must not be committed as repo fixtures or redistributed in example outputs unless rights are explicitly cleared.

> **Design Principle:** This is a skill-preserving worksheet adaptation engine, NOT a page-faithful restyling tool. Source worksheets are curriculum signals. The system preserves literacy skill and pedagogical intent, not original wording or layout.

---

## Product Shape

- **Primary experience:** Print-first worksheets (physical paper output) plus a lightweight digital companion
- **Companion handles:** Avatar customization, progress tracking, caregiver/teacher visibility
- **Target cohort:** Children ages 5-8, Kindergarten through Grade 3, Ontario and British Columbia school systems
- **Adaptation range:** High — output may significantly differ from source in wording, ordering, item count, response format, and layout, as long as the targeted literacy skill is preserved and the output is developmentally appropriate
- **Curriculum alignment:** Ontario Language Curriculum 2023 (Strand B/C); supports foundational literacy skills aligned at a high level with BC English Language Arts K-3 expectations; informed by structured literacy and Science of Reading principles

---

## Architecture

### Pipeline: Capture → Normalize → Extract → Skill Model → Adapt → Theme → Render → Validate

```
Physical Paper
    │
    ▼
[1. CAPTURE]              Phone camera / flatbed scanner → master page images
    │                     Store originals for future reprocessing
    ▼
[2. NORMALIZE]            Deskew, dewarp, denoise, contrast normalize (OpenCV)
    │                     Deterministic, versioned preprocessing
    ▼
[3. SOURCE EXTRACTION]    Deterministic OCR (PaddleOCR / Tesseract)
    │                     → text + bounding boxes + confidence scores
    │                     → SourceWorksheetModel (what's on the page)
    │
    ├──── [AI ASSIST]     Optional: semantic tagging, skill inference,
    │     (bounded)       unknown layout fallback, low-confidence review
    ▼
[4. LITERACY SKILL        Extract the targeted literacy skill + pedagogical intent
    MODEL]                → LiteracySkillModel (what skill is being taught)
    │                     Grade level, domain, specific objectives, word lists
    ▼
[5. ADHD ACTIVITY         Redesign activity for ADHD delivery
    ADAPTATION]           Chunking, instruction simplification, scaffolding,
    │                     alternate response formats, progress cues
    │                     Inputs: LiteracySkillModel + LearnerProfile +
    │                             AccommodationRules + RewardState
    │                     → AdaptedActivityModel
    ▼
[6. THEME]                Apply calm theme tokens + child preferences
    │                     Avatar companion placement
    │                     Curated assets or preference-driven generative assets
    ▼
[7. RENDER]               Vector-first PDF output (ReportLab)
    │                     Text as vector, illustrations as embedded raster
    │
    ├──── [PREVIEW]       Quick preview → child/parent feedback → re-adapt/re-theme
    ▼
[8. VALIDATE]             Skill-parity, age-band, print, collision, accessibility
    │                     Human review for low-confidence or major rewrites
    ▼
Print-Ready Worksheet + Companion Progress Update
```

### Deterministic vs AI-Assisted — Clear Boundary

**Must be deterministic (no AI dependency):**
- Page preprocessing (deskew, dewarp, denoise, contrast)
- OCR baseline and confidence gating
- Schema validation (all models)
- Skill taxonomy mapping and age-band guardrails
- Activity assembly rules (chunking, scaffolding, response formats)
- Layout geometry and theme placement rules
- Print rendering
- Skill-parity checks, accessibility, and collision validation

**Benefits from AI assist (optional, bounded, structured output required):**
- Semantic tagging of worksheet regions and response types
- Fallback understanding for unknown or noisy layouts
- Extraction of likely literacy skill targets from messy scans
- Review of low-confidence OCR segments
- Suggestion of ADHD-friendly alternative activity forms
- Non-authoritative QA on semantic drift, age-band mismatch, or missing elements

**All model outputs must land in strict structured JSON contracts before they can influence the deterministic pipeline.**

---

## Data Contracts

> **Implementation note:** All data contracts are implemented as **Pydantic `BaseModel`** classes (not `@dataclass`). Pydantic is the single contract layer for schema validation, serialization, and type enforcement across all pipeline stages. The examples below use `@dataclass` notation for readability but the actual implementation uses `class Foo(BaseModel)`.

### SourceWorksheetModel (Stage 3 output)

```python
@dataclass
class SourceRegion:
    type: str           # Generic: "title", "instruction", "question", "answer_blank",
                        #          "word_list", "illustration", "table", "divider"
                        # UFLI Word Work: "concept_label", "sample_words", "word_chain",
                        #                 "chain_script", "sight_word_list", "practice_sentences"
                        # UFLI Decodable: "story_title", "illustration_box", "decodable_passage"
    content: str        # extracted text
    bbox: Tuple[float, float, float, float]  # x0, y0, x1, y1
    confidence: float   # OCR confidence 0-1
    metadata: dict      # font_size, bold, etc.

@dataclass
class SourceWorksheetModel:
    source_image_hash: str
    pipeline_version: str
    template_type: str  # "ufli_word_work" | "ufli_decodable_story" | "unknown"
    regions: List[SourceRegion]
    raw_text: str
    ocr_engine: str     # "paddleocr" | "tesseract"
    low_confidence_flags: List[int]  # region indices needing review
```

### LiteracySkillModel (Stage 4 output)

```python
@dataclass
class LiteracySkillModel:
    grade_level: str                    # "K" | "1" | "2" | "3"
    domain: str                         # "phonemic_awareness" | "phonics" | "fluency" |
                                        # "vocabulary" | "comprehension" | "writing"
    specific_skill: str                 # e.g., "CVC blending", "digraph sh/ch/th"
    learning_objectives: List[str]
    target_words: List[str]             # word lists, sight words, spelling patterns
    response_types: List[str]           # "circle", "write", "match", "read_aloud", "trace"
    source_items: List[SourceItem]      # extracted questions/activities
    extraction_confidence: float        # overall confidence in skill extraction
```

### AdaptedActivityModel (Stage 5 output)

```python
@dataclass
class ActivityChunk:
    micro_goal: str                     # "Find the 'sh' words (4 items)"
    instructions: List[Step]            # numbered, bold-verb, concise
    worked_example: Optional[Example]   # shown before independent items
    items: List[ActivityItem]           # the actual practice items
    response_format: str                # "circle", "write", "match", "verbal"
    time_estimate: str                  # "About 3 minutes"
    reward_event: Optional[RewardEvent] # tokens/unlock on completion (None for MVP)

@dataclass
class AdaptedActivityModel:
    source_hash: str                    # links back to source
    skill_model_hash: str               # links back to skill extraction
    learner_profile_hash: str           # links back to profile used
    chunks: List[ActivityChunk]
    scaffolding: ScaffoldConfig         # fade supports across chunks
    theme_id: str
    decoration_zones: List[BBox]        # safe areas for theme illustrations
    avatar_prompts: Optional[List[str]] # coach phrases (None for MVP, populated by companion)
    self_assessment: Optional[List[str]] # "I can..." checklist items for end of worksheet
```

### LearnerProfile

```yaml
LearnerProfile:
  # --- Required for MVP (core engine) ---
  name: string
  grade_level: K | 1 | 2 | 3
  accommodations:
    chunking_level: small | medium | large
    response_format_prefs: [string]     # "circle", "write", "match", "verbal"
    font_size_override: int | null
    show_time_estimates: bool
    show_self_check_boxes: bool

  # --- Optional: added by companion layer (post-core) ---
  avatar:                               # default: null (no avatar on worksheet)
    base_character: string              # "robot", "unicorn", "astronaut"
    base_colors: { primary, secondary, accent }
    equipped_items: [item_id]
    unlocked_items: [item_id]
  preferences:                          # default: empty (uses theme defaults)
    favorite_themes: [string]
    color_preferences: [string]
    visual_style: string                # "cute_cartoon", "comic_book", "pixel_art"
  progress:                             # default: zeros
    worksheets_completed: int
    current_lesson: int
    tokens_available: int
    milestones_reached: [int]
    completion_history: [CompletionRecord]
  operational_signals:                  # default: zeros
    avg_session_duration: float
    avg_chunks_per_session: float
    hint_usage_rate: float
    skip_rate: float
```

### RewardEventModel

```python
@dataclass
class RewardEventModel:
    trigger: str        # "worksheet_completion" | "milestone" | "bonus_challenge"
    tokens_awarded: int
    items_unlocked: List[str]
    message: str        # "You earned the space helmet!"
```

### Idempotency

Every pipeline run is keyed by: `hash(master_image) + learner_profile_hash + theme_id + pipeline_version`

Same inputs → same outputs, always. All intermediate artifacts are persisted for debugging and reprocessing.

---

## ADHD-Optimized Worksheet Design

> **Evidence context:** Recommendations below are aligned with ADHD accommodation guidance drawn from UDL research, classroom-design studies, clinical self-management programs (Longwood Pediatrics, Boston Children's), token-economy literature, and cognitive-load theory. Direct research on printed worksheet aesthetics for 5-8 ADHD learners is sparse. Most design rules below are evidence-consistent inferences, not directly proven claims. See PMC10453933, PMC5280087, and Longwood/BCH Guided Self-Management Tools for ADHD (ages 6-12) for key sources.

### Visual Design Rules (enforced in rendering)

**Principle: Game-themed structure with visually calm execution.** Use game framing (levels, XP, challenges) to motivate, but keep the visual field clean so the activity content — not the decoration — commands attention.

- **One main task per page** (or clearly separated sections with visible borders/boxes)
- **Generous white space** — especially around activity items and answer areas
- **Sans-serif font**, 12-14pt minimum (e.g., Arial, Verdana, Nunito)
- **High contrast** — dark text on light/white background only; no gradients, patterns, or images behind text or answer areas
- **Consistent layout** — instructions always top-left, examples in shaded box below, answer spaces in same position across all worksheets

**Decoration budget per page:**
- **0-2 purely decorative elements** (theme-flavor only: a small rocket, a border accent)
- **Unlimited functional visuals** that directly support the task (worked-example annotations, arrows showing word chains, icons marking step numbers) — these are instructional, not decorative
- Place decorative elements in **consistent, low-competition zones** (page header/footer, fixed corner) — never between activity items or behind text
- Theme art should be **consistent across a workbook** (same style, same character) to reduce novelty load

**Color system (2-4 functional colors + black, consistent across all pages):**
- **Blue** — directions and section headings
- **Green** — worked examples and model answers
- **Gold/amber** — rewards, progress indicators, XP/stars
- **Black/dark gray** — student activity items, answer lines, body text
- **White/near-white** — background (always)
- Richer palettes may vary **across themed units** (space theme vs. underwater theme) but each individual page maintains the functional color code above

### Content Restructuring (applied during adaptation)

**Chunking (evidence-consistent: ADHD accommodation guidelines, cognitive-load theory):**
- **Chunk content** into small, visually boxed sections — each designed for **~3-7 minutes** of focused work
- **Label each chunk** as a game level with a micro-goal: "Level 1: Sound Warm-Up (10 XP)" instead of "Exercise A"
- Each chunk has its own **mini-instruction, worked example, activity items, and completion marker**

**Instructions and modeling (evidence-consistent: ADHD teaching strategies emphasize explicit instruction and guided practice):**
- **Numbered step instructions** with bold action verbs: "1) **Read** the word. 2) **Circle** the silent e."
- **Worked example first** — large, uncluttered, visually guided (arrows, highlighted parts). This is **especially critical for ADHD learners** who have working-memory and executive-function weaknesses (more so than neurotypical peers)
- Consider **partially worked examples** as a bridge: "cube → c u b _ (fill in the missing letter)"

**Time estimates (evidence-consistent: ADHD time-management interventions support time awareness; rigid deadlines may increase anxiety):**
- Use **soft, supportive time cues**: "About 3 minutes" with a small clock icon
- Frame as information, not performance criteria — never "beat the clock"
- Omit or de-emphasize for children with comorbid anxiety (configurable in learner profile)

**Progress and completion:**
- **Self-check boxes** next to each item (child marks completion)
- **Mini progress indicator** per page (stars or circles to color as chunks complete)
- **Alternate response formats** when helpful: circling, matching, short writing, guided verbal

### Engagement Elements (ADHD-safe)

**Game framing (evidence-consistent: token economies and visible completion cues are supported for ADHD; gamification labels are motivational scaffolding, not proven independently):**
- **Level labels**: each chunk may use a simple label like "Level 1" or "Part 1" — but the label must be **visually subordinate** to the activity content (smaller font, muted color). The child should focus on the literacy task, not on game mechanics
- **Boss challenge**: an optional harder section — "Challenge: Try this if you have time!" Keep the framing brief; do not introduce extra rules or mechanics the child must learn beyond the literacy skill
- **Effort-based XP/points**: earned for completing chunks, **not for accuracy or speed**. A simple star or checkmark per section is sufficient. Avoid accumulating complex point totals that become a parallel tracking task
- **Completion acknowledgment**: brief, calm — "You did it!" with a small badge or star. Not a high-stimulation victory screen. The reward should take less visual space than any single activity chunk

**Choice (evidence-consistent: bounded choice supports intrinsic motivation; excessive choice can overwhelm ADHD learners):**
- **2-3 options** for younger/more dysregulated children; up to 5 for Grade 3
- All options must address the **same learning target**
- Example: "Choose any 3 of these 5 words to use in a sentence"

**Avatar companion (evidence-consistent: consistent, predictable visual cues support ADHD learners; multiple characters or scattered appearances become competing stimuli):**
- **1-2 instances per page**, always in the **same zones** (e.g., top-left instruction area + bottom-right encouragement)
- **One consistent character** across the entire workbook (same look, same name) — reduces novelty load
- Avatar delivers **short, concrete guidance** ("Remember to underline the key word!") or brief encouragement — not jokes or unrelated speech
- Speech bubbles are **visually subordinate** to main instructions (smaller font, lighter color)
- Never embed avatar between individual activity items

**Self-assessment (evidence-consistent: self-monitoring checklists appear in ADHD self-management programs and support emerging metacognition):**
- End each worksheet with a **short self-assessment checklist**: "I can build words with silent-u ☐ / I'm still learning ☐"
- Use **simple, concrete language** and optionally **pictorial scales** (thumbs up/sideways) for K-1
- Include one open prompt: "One thing that helped me was ___"
- Adults briefly review and tie to **effort-based praise** (not accuracy)

### Explicit Anti-Patterns (NEVER do these)
- Dense text blocks or crowded pages
- Patterned/gradient/image backgrounds behind text or answer areas
- Multiple different characters on the same page
- Avatar or decorative elements scattered between individual activity items
- Accuracy-based or speed-based scoring ("7/10", "beat the clock")
- Leaderboards or competitive/comparative elements
- Streak punishment ("you lost your streak!")
- Randomized/variable-ratio reward mechanics (loot boxes, rarity systems)
- Monetized cosmetics
- Complex menus or inventories that invite long diversion from learning
- Flashing or highly animated stimuli (in companion app)
- Many simultaneous mini-goals or frequent theme shifts within one worksheet

### Grade-Level Adaptations (K-3)

| Grade | Ages | Font | Items/Chunk | Target Chunk Time | Literacy Focus | Key Design |
|-------|------|------|-------------|-------------------|----------------|------------|
| K | 5-6 | 16-18pt | 2-3 | ~3 min | Phonemic awareness, letter-sound, CVC, concepts of print | Pictorial instruction cues, maximum white space, pictorial self-assessment |
| 1 | 6-7 | 14-16pt | 3-5 | ~5 min | Phonics (digraphs, blends), high-frequency words, fluency | Worked examples with arrows/highlights, numbered steps |
| 2 | 7-8 | 12-14pt | 4-6 | ~5-7 min | Vowel teams, r-controlled, prefixes/suffixes, comprehension | Self-check boxes, soft time estimates, partially worked examples |
| 3 | 8-9 | 12-14pt | 5-8 | ~7 min | Multi-syllable, morphology, comprehension strategies | Structured response frames, choice items (choose 3 of 5), text self-assessment |

---

## Companion Layer & Progressive Avatar System

### Product Shape
Print-first worksheets + lightweight digital companion. The worksheets are the primary learning experience (printed paper). The companion is the engagement and tracking layer (CLI initially, simple web/mobile app later).

### Progressive Avatar Customization
1. **Starting avatar:** child picks a base character and basic colors during profile setup
2. **Worksheet completion = tokens:** completing each worksheet earns customization tokens
3. **Cosmetic-only catalog:** tokens unlock clothing, accessories, expressions, theme-specific items
4. **Avatar on worksheets:** current avatar appears as coach companion on each worksheet
5. **Milestone rewards:** every 5th/10th worksheet unlocks a special item
6. **Grows with child:** swap items freely from earned collection as interests change

### ADHD-Specific Rules for Rewards
> Evidence basis: Token economies with frequent, immediate, predictable, effort-based reinforcement are strongly supported for ADHD (PMC5280087). Variable-ratio and accuracy-based scoring are contraindicated.

- Rewards are **predictable, effort-linked, cosmetic only** — earned for completing chunks and using strategies, not for accuracy or speed
- XP/tokens are framed as **"points for trying and finishing"**, never as grades or comparative scores
- Customization **gated to break points** — before/after sessions only, never during
- Keep customization **quick** — target <2 minutes per session
- **No** loot boxes, rarity systems, monetized cosmetics, variable-ratio rewards, streak punishment
- Avatar renders as **clean, flat-color illustration** on white/light background
- Celebration is **brief** (2-3 seconds), calm, then routes back — not high-stimulation

### Caregiver/Teacher Controls
- **Pacing:** worksheets per session, breaks
- **Reward visibility:** what's earned, what's next
- **Accommodation settings:** chunking level, response format prefs, font size, time estimates
- **Progress review:** completion history, skill progression
- **Transformation review:** source vs adapted worksheet side-by-side

### Operational Signals (tracked by companion)
- Task completion, chunks per session
- Time-on-task (session duration, not surveillance)
- Hint usage, skip rate
- These inform accommodation adjustments, not scores or grades

---

## Reference Samples

`samples/` contains real-world input and output examples for design reference:

**Inputs** (`samples/input/`) — 6 phone photos of UFLI Foundations Home Practice worksheets:
- Lessons 43, 58, 59 (word work pages): -all/-oll/-ull, u_e, a_e patterns
- Decodable story pages: Ross/mall (-all words), Beth/pets (ch/ck digraphs), June's Flute (u_e)
- One already-adapted output (Mission OLL) photographed from screen
- Photos exhibit typical challenges: skew, perspective distortion, spiral binding, bleed-through, uneven lighting

**Outputs** (`samples/output/`) — 3 examples of adapted worksheets (created manually, pre-engine):
- Mission OLL Word Power: clean numbered sections, Roblox character + owl companion
- Roblox Phonics Quest (u_e): multi-level game format with XP, coins, boss level, victory screen
- Roblox Phonics Quest (Silent-U): time estimates per level, self-assessment checklist, final score

> **Design note:** The output samples demonstrate excellent structural ideas (levels, chunking, XP, boss challenges, self-assessment) but are more visually dense than ADHD evidence supports. The engine should adopt their game-themed *structure* while using visually *calmer execution* per the evidence-based design rules above: clean backgrounds, limited decoration, functional color coding, avatar in fixed zones only.

---

## Project Structure

```
worksheet-builder/                     # https://github.com/howardjong/worksheet-builder.git
├── capture/
│   ├── __init__.py
│   ├── preprocess.py                  # OpenCV: deskew, dewarp, denoise, normalize
│   └── store.py                       # Master image storage + derived PDF generation
├── extract/
│   ├── __init__.py
│   ├── ocr.py                         # Deterministic OCR (PaddleOCR/Tesseract)
│   ├── heuristics.py                  # Rule-based source structure mapping
│   ├── ai_assist.py                   # Optional Vision LLM semantic tagging
│   ├── adapter.py                     # Model adapter interface (swap providers)
│   └── schema.py                      # SourceWorksheetModel schema + validation
├── skill/
│   ├── __init__.py
│   ├── extractor.py                   # Source → LiteracySkillModel extraction
│   ├── taxonomy.py                    # Literacy skill taxonomy (K-3 domains)
│   └── schema.py                      # LiteracySkillModel schema + validation
├── adapt/
│   ├── __init__.py
│   ├── engine.py                      # ADHD activity adaptation
│   ├── rules.py                       # Accommodation rules (chunking, scaffolding)
│   ├── rewards.py                     # RewardEventModel generation per activity
│   └── schema.py                      # AdaptedActivityModel schema + validation
├── theme/
│   ├── __init__.py
│   ├── engine.py                      # Apply calm theme tokens + child preferences
│   ├── assets.py                      # Asset resolution: curated → generative fallback
│   └── themes/
│       ├── space/                     # config.yaml + curated assets/
│       ├── underwater/
│       └── dinosaur/
├── companion/
│   ├── __init__.py
│   ├── profile.py                     # LearnerProfile CRUD (YAML/JSON storage)
│   ├── avatar.py                      # Avatar composition (layered PNG/SVG)
│   ├── catalog.py                     # Unlockable item catalog
│   ├── rewards.py                     # Token economy + unlock logic
│   ├── signals.py                     # Operational signal tracking
│   ├── caregiver.py                   # Caregiver/teacher view + controls
│   └── generate.py                    # Preference-driven asset generation via API
├── render/
│   ├── __init__.py
│   ├── pdf.py                         # ReportLab vector PDF generation
│   └── preview.py                     # Quick preview for child/parent feedback
├── validate/
│   ├── __init__.py
│   ├── skill_parity.py                # Skill-preservation + age-band validation
│   ├── print_checks.py                # Print quality, collision, accessibility
│   └── adhd_compliance.py             # ADHD design rules compliance
├── transform.py                       # CLI entry point (transform worksheets)
├── complete.py                        # CLI entry point (mark completion, award tokens)
├── profiles/                          # Learner profiles (gitignored)
├── masters/                           # Master page images (gitignored, persistent)
├── artifacts/                         # Intermediate outputs per job (gitignored)
├── asset_cache/                       # Approved generated assets (gitignored)
├── tests/
│   ├── test_capture.py
│   ├── test_extract.py
│   ├── test_skill.py
│   ├── test_adapt.py
│   ├── test_theme.py
│   ├── test_companion.py
│   ├── test_render.py
│   ├── test_validate.py
│   ├── test_e2e.py                    # Golden end-to-end tests
│   └── golden/                        # 3-5 reference worksheets + expected output
│       ├── phonics-cvc/
│       │   ├── source.png
│       │   ├── expected_source_model.json
│       │   ├── expected_skill_model.json
│       │   ├── expected_adapted_model.json
│       │   └── expected_output.pdf
│       └── sight-words-gr1/
│           └── ...
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml                     # Lint + type-check + unit tests
├── pyproject.toml                     # Project config, dependencies
├── requirements.txt                   # Pinned dependencies
├── Makefile                           # Common targets
└── README.md
```

---

## Dependencies

| Dependency | Purpose | Version |
|------------|---------|---------|
| Python | Runtime | 3.11+ |
| OpenCV (opencv-python-headless) | Image preprocessing: deskew, dewarp, denoise | 4.x |
| PaddleOCR | Primary OCR engine | Latest |
| pytesseract | Fallback OCR engine (Python wrapper; requires native `tesseract-ocr` binary installed separately) | Latest |
| ReportLab | Vector PDF generation | Latest |
| PyMuPDF (fitz) | PDF utility layer (read/manipulate when needed) | Latest |
| Pillow | Image manipulation, avatar compositing | Latest |
| pydantic | Schema validation for all data contracts | 2.x |
| click | CLI framework | 8.x |
| PyYAML | Profile and config storage | Latest |
| pytest | Testing | Latest |
| mypy | Type checking | Latest |
| ruff | Linting | Latest |

---

## Success Criteria

### Must Have — Core Engine (MVP)

The MVP proves the core transform: photo of a worksheet in → ADHD-adapted, print-ready PDF out. Avatar, tokens, and caregiver controls are valuable but depend on the engine working first.

- [ ] `python transform.py --input photo.jpg --profile ian.yaml --theme space` produces print-ready PDF
- [ ] Pipeline runs deterministically without any API calls (no AI in critical path)
- [ ] Same inputs → same outputs (idempotent, keyed by image hash + profile + theme + version)
- [ ] Source OCR extracts text with >95% accuracy on clean scans of target worksheet family
- [ ] LiteracySkillModel correctly identifies domain, grade level, and target words for known layouts
- [ ] AdaptedActivityModel produces chunked, scaffolded activities compliant with all ADHD design rules
- [ ] Output PDF: vector text, embedded fonts, 300 DPI raster assets, letter size, margin-safe
- [ ] Skill-parity validation blocks drift outside the learning target or age band
- [ ] All ADHD anti-patterns are absent from output (no clutter, no dense text, no noisy backgrounds)
- [ ] Golden test set (3-5 worksheets) passes without network access
- [ ] All tests pass: `make test`

### Must Have — Companion Layer (post-core, pre-launch)

These features ship before public release but are built only after the core engine is proven on real worksheets.

- [ ] `python complete.py --profile ian.yaml --lesson 5` awards tokens and shows unlocks
- [ ] Avatar companion renders correctly with equipped items on each worksheet
- [ ] Token economy awards predictable, skill-linked cosmetic rewards
- [ ] Caregiver can view progress and adjust accommodation settings

### Nice to Have

- [ ] AI assist layer for unknown worksheet layouts (model adapter interface)
- [ ] Preference-driven generative asset creation with approval caching
- [ ] Operational signal tracking (time-on-task, hint usage, skip rate)
- [ ] `--preview` flag produces quick low-res render for child feedback
- [ ] Multiple worksheet families beyond initial target
- [ ] Web/mobile companion app (beyond CLI)

---

## Working-State Guardrails

**Per-milestone checklist (required before merge):**

```bash
# Clone and setup
git clone https://github.com/howardjong/worksheet-builder.git
cd worksheet-builder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Lint + type check
make lint        # ruff check .
make typecheck   # mypy .

# Unit tests
make test        # pytest tests/ -v

# Golden E2E tests (no network required)
make test-golden # pytest tests/test_e2e.py -v

# Smoke test (requires sample worksheet photo)
python transform.py --input tests/golden/phonics-cvc/source.png --profile tests/fixtures/test_profile.yaml --theme space --output /tmp/test_output/
```

**Regression-minimization policy:**
- All changes must be additive or behind flags
- Existing CLI behavior must not change without new flags
- Schema changes must be backwards-compatible (new optional fields only)
- Every data contract change requires schema version bump
- No AI dependency in the deterministic pipeline path

**Makefile targets:**

```makefile
lint:           ruff check .
typecheck:      mypy .
test:           pytest tests/ -v --ignore=tests/test_e2e.py
test-golden:    pytest tests/test_e2e.py -v
test-all:       pytest tests/ -v
format:         ruff format .
clean:          rm -rf artifacts/ __pycache__ .mypy_cache
```

---

## Milestones

### Milestone 1: Foundation + Source Extraction (Checkpoints 1.1-1.4) — MVP
**Goal:** Repository scaffold, image preprocessing, OCR pipeline, and SourceWorksheetModel.
**Days:** 1-5

### Milestone 2: Skill Extraction + ADHD Adaptation (Checkpoints 2.1-2.4) — MVP
**Goal:** LiteracySkillModel extraction, ADHD activity adapter, and AdaptedActivityModel.
**Days:** 6-12

### Milestone 3: Theme + Render + Validate + E2E (Checkpoints 3.1-3.3, 4.4) — MVP
**Goal:** Calm themed rendering, vector PDF output, validation suite, and end-to-end golden tests. This milestone proves the core engine: photo in → adapted PDF out.
**Days:** 13-19

### Milestone 4: Companion + Avatar (Checkpoints 4.1-4.3) — Post-Core, Pre-Launch
**Goal:** Learner profiles, avatar system, token economy, caregiver controls. Built after the core engine is proven on real worksheets.
**Days:** 20-24

### Milestone 5: AI Assist + Generative Assets (Checkpoints 5.1-5.3) — Post-Launch
**Goal:** Model adapter interface, bounded AI assist, preference-driven asset generation.
**Days:** 25+

---

## Checkpoint Details

### Checkpoint 1.1: Repository Scaffold + CI

**Goal:** Initialize the repository with project structure, dependencies, linting, type checking, and CI pipeline.

**Implementation:**

```bash
# Initialize repository
git clone https://github.com/howardjong/worksheet-builder.git
cd worksheet-builder

# Create project structure (all __init__.py files, empty modules)
# Create pyproject.toml with project metadata
# Create requirements.txt with pinned dependencies
# Create Makefile with lint/typecheck/test targets
# Create .github/workflows/ci.yml
# Create .gitignore (profiles/, masters/, artifacts/, asset_cache/, .venv/, __pycache__/)
```

**CI workflow** (`.github/workflows/ci.yml`):
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: sudo apt-get update && sudo apt-get install -y tesseract-ocr
      - run: pip install -r requirements.txt
      - run: make lint
      - run: make typecheck
      - run: make test
```

**Files:**
- `pyproject.toml` — project config, ruff/mypy settings
- `requirements.txt` — pinned dependencies
- `Makefile` — common targets
- `.github/workflows/ci.yml` — CI pipeline
- `.gitignore` — exclude data dirs
- All `__init__.py` files for package structure

**Acceptance Criteria:**
- [ ] `git clone && pip install -r requirements.txt` works cleanly
- [ ] `make lint` passes (ruff)
- [ ] `make typecheck` passes (mypy)
- [ ] `make test` passes (empty test suite, no errors)
- [ ] CI runs on push and PR

---

### Checkpoint 1.2: Image Capture + Preprocessing

**Goal:** OpenCV pipeline that takes a phone photo or scan of a worksheet and produces a clean, normalized page image.

**Implementation:**

```python
# capture/preprocess.py
def preprocess_page(image_path: str, output_path: str) -> PreprocessResult:
    """
    Full preprocessing pipeline:
    1. Load image
    2. Detect page contour (for phone photos with background)
    3. Perspective warp to rectangular page
    4. Deskew (Hough transform for skew angle)
    5. Denoise (fastNlMeansDenoising)
    6. Contrast normalize (CLAHE)
    7. Page-boundary cleanup (trim margins)
    8. Save normalized image
    Returns: PreprocessResult with image_hash, dimensions, skew_angle
    """
```

```python
# capture/store.py
def store_master(image_path: str, masters_dir: str) -> MasterRecord:
    """Store original image with hash-based filename for permanence."""

def derive_archival_pdf(master_path: str, output_path: str) -> str:
    """Generate a PDF wrapping the master image for archival storage.
    Note: this is NOT a searchable/OCR PDF — OCR happens later in
    the extract stage. True PDF/A compliance requires ocrmypdf or
    similar post-OCR tooling and is a post-MVP concern."""
```

**Files:**
- `capture/preprocess.py` — OpenCV preprocessing pipeline
- `capture/store.py` — master image storage
- `tests/test_capture.py` — unit tests with sample images

**Acceptance Criteria:**
- [ ] Phone photo with skew + perspective → clean, deskewed, cropped page image
- [ ] Flatbed scan → normalized page image
- [ ] Same input → same output (deterministic)
- [ ] Master image stored with hash-based filename
- [ ] Archival PDF generated from master (image-wrapped; searchable PDF/A is post-MVP)
- [ ] Preprocessing handles: skew up to 15°, perspective distortion, uneven lighting

---

### Checkpoint 1.3: OCR + Source Extraction

**Goal:** Deterministic OCR extracts text with bounding boxes and maps to SourceWorksheetModel.

**Implementation:**

```python
# extract/ocr.py
def extract_text(image_path: str, engine: str = "paddleocr") -> OCRResult:
    """
    Run OCR on preprocessed image.
    Returns: text blocks with bounding boxes and confidence scores.
    Engine: "paddleocr" (primary) or "tesseract" (fallback).
    """

# extract/heuristics.py
def detect_ufli_template(ocr_result: OCRResult) -> str:
    """
    Classify a UFLI page as one of two known templates:
    - "word_work": keyword match on "New Concept", "Word Work Chains",
      "Sample Words", "Irregular Words", "Sentences"
    - "decodable_story": large text block with illustration box region,
      no structured sections
    Returns: "word_work" | "decodable_story" | "unknown"
    """

def map_to_source_model(ocr_result: OCRResult, layout_family: str = "ufli") -> SourceWorksheetModel:
    """
    Rule-based mapping from OCR output to source worksheet structure.

    UFLI Word Work template heuristics:
    - Top region with "Home Practice / Lesson N" → title/header
    - "New Concept and Sample Words" box → word_list + concept label
    - "Word Work Chains" box → word_chain items
    - "Sample Word Work Chain Script" → scripted activity steps
    - "New Irregular Words" box → sight_word_list
    - "Sentences" box → practice_sentences

    UFLI Decodable Story template heuristics:
    - Top bordered rectangle (no text) → illustration_box
    - Large continuous text block below → decodable_passage
    - Title line above passage → story_title

    Generic fallback:
    - Top 15% of page → title/header
    - Numbered items → questions
    - Underscored areas → answer blanks
    - Boxed areas → word lists or examples
    """

# extract/schema.py
class SourceWorksheetModel(BaseModel):
    """Pydantic model with strict validation."""
    source_image_hash: str
    pipeline_version: str
    template_type: str              # "ufli_word_work" | "ufli_decodable_story" | "unknown"
    regions: List[SourceRegion]
    raw_text: str
    ocr_engine: str
    low_confidence_flags: List[int]
```

**Confidence gating:**
```python
LOW_CONFIDENCE_THRESHOLD = 0.7

def flag_low_confidence(regions: List[SourceRegion]) -> List[int]:
    """Return indices of regions below confidence threshold for human review."""
```

**Files:**
- `extract/ocr.py` — OCR integration
- `extract/heuristics.py` — rule-based structure mapping
- `extract/schema.py` — SourceWorksheetModel with Pydantic validation
- `tests/test_extract.py` — unit tests

**Acceptance Criteria:**
- [ ] PaddleOCR extracts text with >95% character accuracy on clean scans
- [ ] Tesseract fallback works when PaddleOCR unavailable
- [ ] Bounding boxes correctly localize text regions
- [ ] `detect_ufli_template()` correctly classifies word work vs decodable story pages
- [ ] UFLI Word Work heuristics identify: concept_label, sample_words, word_chain, chain_script, sight_word_list, practice_sentences
- [ ] UFLI Decodable Story heuristics identify: story_title, illustration_box, decodable_passage
- [ ] Unknown layouts produce `template_type: "unknown"` (not silent garbage)
- [ ] Low-confidence regions (< 0.7) flagged for human review
- [ ] SourceWorksheetModel validates against Pydantic schema (including `template_type`)
- [ ] Same image → same SourceWorksheetModel (deterministic)

---

### Checkpoint 1.4: Skill Taxonomy + Extraction

**Goal:** Define K-3 literacy skill taxonomy and extract LiteracySkillModel from SourceWorksheetModel.

**Implementation:**

```python
# skill/taxonomy.py
LITERACY_DOMAINS = {
    "phonemic_awareness": {
        "skills": ["rhyme_identification", "syllable_counting", "phoneme_segmentation",
                   "phoneme_blending", "phoneme_manipulation"],
        "grade_range": ["K", "1"]
    },
    "phonics": {
        "skills": ["letter_sound", "cvc_blending", "cvce", "digraphs", "blends",
                   "vowel_teams", "r_controlled", "multisyllable"],
        "grade_range": ["K", "1", "2", "3"]
    },
    "fluency": {
        "skills": ["decodable_text", "sight_words", "passage_reading", "timed_reading"],
        "grade_range": ["1", "2", "3"]
    },
    "vocabulary": {
        "skills": ["context_clues", "word_parts", "academic_vocabulary"],
        "grade_range": ["2", "3"]
    },
    "comprehension": {
        "skills": ["literal_questions", "inference", "main_idea", "text_evidence",
                   "summarizing", "comparing_texts"],
        "grade_range": ["1", "2", "3"]
    },
    "writing": {
        "skills": ["letter_formation", "sentence_writing", "paragraph_organization"],
        "grade_range": ["K", "1", "2", "3"]
    }
}

# skill/extractor.py
def extract_skill(source: SourceWorksheetModel) -> LiteracySkillModel:
    """
    Rule-based skill extraction from known worksheet layouts.
    Dispatches based on source.template_type:

    UFLI Word Work → rich skill signals:
    1. concept_label region gives explicit pattern (e.g., "-all, -oll, -ull")
    2. sample_words region gives target word list
    3. word_chain region gives manipulation sequence
    4. Domain is almost always "phonics"; specific_skill from concept label
    5. Grade level inferred from lesson number and word complexity

    UFLI Decodable Story → fluency + embedded pattern:
    1. Primary domain is "fluency" (decodable_text)
    2. Target pattern extracted from story_title or passage word frequency
    3. Target words = high-frequency pattern words in passage
    4. Response types = ["read_aloud", "comprehension_questions"]

    Generic fallback:
    1. Identify keywords in title/instructions that map to domains
    2. Analyze item structure to determine response types
    3. Extract target words from word lists and questions
    4. Infer grade level from vocabulary complexity and item count
    """
```

**Files:**
- `skill/taxonomy.py` — K-3 literacy skill definitions
- `skill/extractor.py` — rule-based skill extraction
- `skill/schema.py` — LiteracySkillModel with Pydantic validation
- `tests/test_skill.py` — unit tests

**Acceptance Criteria:**
- [ ] Taxonomy covers all 6 domains with grade-appropriate specific skills
- [ ] UFLI Word Work → extracts phonics domain, specific pattern from concept label, target words from sample words
- [ ] UFLI Decodable Story → extracts fluency domain, target pattern from title/passage, target words from passage
- [ ] `extraction_confidence` reflects quality of match
- [ ] Low-confidence extractions flagged for human review
- [ ] Schema validates against Pydantic model

---

### Checkpoint 2.1: ADHD Activity Adapter

**Goal:** Transform LiteracySkillModel into ADHD-optimized AdaptedActivityModel.

**Implementation:**

```python
# adapt/engine.py
def adapt_activity(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    reward_state: Optional[RewardState] = None  # None for MVP (companion not yet built)
) -> AdaptedActivityModel:
    """
    1. Determine chunk size from profile.accommodations.chunking_level + grade
    2. Split source_items into chunks
    3. Generate instructions per chunk (numbered, bold verbs, grade-appropriate)
    4. Add worked example per chunk (from source items or generated)
    5. Set response format per chunk (from profile prefs or skill defaults)
    6. Calculate time estimates per chunk
    7. Generate reward events (tokens per chunk, milestone checks)
    8. Generate avatar coach prompts
    9. Define decoration zones (safe areas for theme illustrations)
    """

# adapt/rules.py
CHUNKING_RULES = {
    "K":  {"small": 2, "medium": 2, "large": 3},
    "1":  {"small": 3, "medium": 4, "large": 5},
    "2":  {"small": 4, "medium": 5, "large": 6},
    "3":  {"small": 5, "medium": 6, "large": 8},
}

RESPONSE_FORMAT_SUBSTITUTIONS = {
    # When a child prefers not to write, substitute equivalent formats
    "write": ["circle", "match", "verbal"],
    "fill_blank": ["circle", "match"],
}
```

**Files:**
- `adapt/engine.py` — core adaptation logic
- `adapt/rules.py` — accommodation rules, chunking tables, substitutions
- `adapt/rewards.py` — reward event generation
- `adapt/schema.py` — AdaptedActivityModel with Pydantic validation
- `tests/test_adapt.py` — unit tests

**Acceptance Criteria:**
- [ ] Chunks respect grade-level size limits from profile
- [ ] Instructions are numbered, use bold action verbs, grade-appropriate vocabulary
- [ ] Worked examples generated before independent items
- [ ] Response format substitutions work (e.g., circle instead of write)
- [ ] Time estimates reasonable for grade level
- [ ] Reward events generated per chunk
- [ ] Avatar prompts are simple, encouraging, age-appropriate
- [ ] Decoration zones don't overlap content areas

---

### Checkpoint 2.2: Accommodation Rules Engine

**Goal:** Configurable rules that drive all ADHD adaptations.

**Implementation:**

```python
# adapt/rules.py
@dataclass
class AccommodationRules:
    max_items_per_chunk: int             # from grade + chunking_level
    instruction_max_words: int           # grade-dependent
    instruction_max_steps: int           # grade-dependent
    require_worked_example: bool         # True for all grades
    require_time_estimate: bool          # from profile
    require_self_check: bool             # from profile
    allowed_response_formats: List[str]  # from profile prefs
    font_size_min: int                   # from grade or profile override
    max_decorative_elements: int         # always 1-2
    color_system: ColorSystem            # consistent color mapping

def build_rules(profile: LearnerProfile) -> AccommodationRules:
    """Build accommodation rules from learner profile and grade level."""
```

**Acceptance Criteria:**
- [ ] Rules correctly derive from grade level + profile accommodations
- [ ] All ADHD design rules are encoded as testable constraints
- [ ] Rules engine is data-driven (change rules via config, not code)

---

### Checkpoint 2.3: Skill-Parity Validation

**Goal:** Validate that adapted output preserves the targeted literacy skill.

**Implementation:**

```python
# validate/skill_parity.py
def validate_skill_parity(
    source_skill: LiteracySkillModel,
    adapted: AdaptedActivityModel
) -> ValidationResult:
    """
    Validates that the adapted activity preserves the instructional intent
    of the source, NOT that it reproduces the original word list verbatim.
    Valid adaptations may use different words, orderings, or item counts
    as long as they exercise the same literacy skill.

    Checks:
    1. Domain preserved (same literacy domain)
    2. Instructional intent preserved (learning objectives covered;
       adapted items exercise the same skill pattern — e.g., CVC blending,
       digraph identification — even if specific words differ)
    3. Grade level appropriate (adapted items within age band)
    4. Response types compatible (adapted formats still test the skill)
    5. No skill drift (adapted activity does not inadvertently test
       a different skill, e.g., phonics → comprehension)
    """

def validate_age_band(
    adapted: AdaptedActivityModel,
    grade_level: str
) -> ValidationResult:
    """Ensure output is developmentally appropriate for target grade."""
```

**Acceptance Criteria:**
- [ ] Catches domain drift (e.g., phonics worksheet adapted into comprehension)
- [ ] Catches skill-pattern drift (e.g., CVC blending adapted into sight-word memorization)
- [ ] Catches age-band violations (Grade 3 content in Kindergarten format)
- [ ] Passes valid adaptations that use different words but exercise the same skill
- [ ] Passes valid adaptations that significantly restructured content

---

### Checkpoint 2.4: ADHD Compliance Validation

**Goal:** Automated checking of all ADHD design rules.

**Implementation:**

```python
# validate/adhd_compliance.py
def validate_adhd_compliance(adapted: AdaptedActivityModel) -> ValidationResult:
    """
    Checks against every visual design rule and anti-pattern:
    - Items per chunk within limits
    - Instructions use numbered steps with bold verbs
    - Decorative elements <= 2 per page
    - No dense text blocks
    - Font size meets minimum
    - Color usage is consistent and sparse
    - Avatar placement is consistent (same position every page)
    """
```

**Acceptance Criteria:**
- [ ] Every ADHD design rule from the spec is a testable check
- [ ] Every anti-pattern is a testable check
- [ ] Returns structured list of violations with severity

---

### Checkpoint 3.1: Theme Engine

**Goal:** Apply calm visual themes to AdaptedActivityModel.

**Implementation:**

Theme config structure (`theme/themes/space/config.yaml`):
```yaml
name: "Space Adventure"
style: calm
fonts:
  primary: "Nunito"
  heading: "Nunito Bold"
colors:
  directions: "#2563EB"     # blue
  examples: "#059669"       # green
  key_words: "#D97706"      # amber
  background: "#FAFAFA"     # near-white
  text: "#1F2937"           # dark gray
avatar_position: "bottom-right"
decorative_elements:
  max_per_page: 2
  assets:
    - "rocket.svg"
    - "planet.svg"
    - "stars.svg"
    - "astronaut.svg"
```

**Files:**
- `theme/engine.py` — theme application logic
- `theme/assets.py` — asset resolution (curated lookup → generative fallback)
- `theme/themes/space/` — space theme config + assets
- `theme/themes/underwater/` — underwater theme config + assets
- `theme/themes/dinosaur/` — dinosaur theme config + assets
- `tests/test_theme.py`

**Acceptance Criteria:**
- [ ] Theme correctly applies fonts, colors, spacing from config
- [ ] Decoration zones from AdaptedActivityModel respected
- [ ] Assets placed within decoration zones only
- [ ] Avatar companion placed in configured position
- [ ] Theme swap (space → dinosaur) changes only visual elements, not content
- [ ] Works without any API calls (curated assets only for MVP)

---

### Checkpoint 3.2: Vector PDF Renderer

**Goal:** ReportLab-based renderer that produces print-ready PDFs from themed AdaptedActivityModel.

**Implementation:**

```python
# render/pdf.py
def render_worksheet(
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    output_path: str,
    avatar_image: Optional[Image] = None  # None for MVP (companion not yet built)
) -> RenderResult:
    """
    ReportLab rendering:
    1. Create letter-size canvas (8.5x11", 612x792 points)
    2. Define margin-safe area (0.75" margins)
    3. Render each chunk:
       - Micro-goal header
       - Instructions (numbered, bold verbs)
       - Worked example (shaded box)
       - Activity items with response areas
       - Self-check boxes (if enabled)
    4. Render progress indicator
    5. Place avatar companion
    6. Place theme decorative elements in decoration zones
    7. Embed fonts
    8. Output PDF
    """
```

**Print specs:**
- Letter size: 8.5 x 11" (612 x 792 points)
- Margins: 0.75" safe area
- Fonts: embedded, fallback stack
- Raster assets: 300 DPI
- Text: vector (searchable, sharp at any zoom)
- PDF/A archival format is a post-MVP goal (requires ocrmypdf or equivalent tooling)

**Files:**
- `render/pdf.py` — ReportLab rendering
- `render/preview.py` — quick low-res preview
- `tests/test_render.py`

**Acceptance Criteria:**
- [ ] Output is valid PDF with correct dimensions
- [ ] Text is vector (searchable, not rasterized)
- [ ] Fonts embedded
- [ ] Content within margin-safe area
- [ ] No text clipping or overflow
- [ ] Avatar and decorative elements render in correct positions
- [ ] No visual collisions between text and illustrations
- [ ] Prints correctly on standard printer

---

### Checkpoint 3.3: Print Quality Validation

**Goal:** Automated checks for print readiness.

**Implementation:**

```python
# validate/print_checks.py
def validate_print_quality(pdf_path: str) -> ValidationResult:
    """
    Checks:
    1. Page dimensions are letter size
    2. All content within margin-safe area
    3. Raster assets are >= 300 DPI
    4. Fonts are embedded
    5. No overlapping text/image bounding boxes
    6. Minimum font size met
    7. Color contrast meets WCAG AA thresholds
    """
```

**Acceptance Criteria:**
- [ ] Catches margin violations
- [ ] Catches low-DPI assets
- [ ] Catches missing embedded fonts
- [ ] Catches visual collisions
- [ ] Catches contrast violations

---

### Checkpoint 4.1: Learner Profile + Avatar Composition

**Goal:** Profile management and avatar rendering from layered assets.

**Implementation:**

```python
# companion/profile.py
def create_profile(name: str, grade_level: str, base_character: str) -> LearnerProfile:
def load_profile(path: str) -> LearnerProfile:
def save_profile(profile: LearnerProfile, path: str) -> None:
def update_accommodations(profile: LearnerProfile, **kwargs) -> LearnerProfile:

# companion/avatar.py
def compose_avatar(profile: LearnerProfile, size: str = "companion") -> Image:
    """
    Layer composition:
    1. Load base character PNG/SVG
    2. Apply base colors (tint/colorize)
    3. Layer equipped items in z-order (body → clothing → accessories → hat)
    4. Render at requested size ("companion" = 150px, "profile" = 400px)
    """
```

**Avatar asset structure:**
```
theme/themes/space/assets/avatar/
├── bases/
│   ├── robot.svg
│   ├── astronaut.svg
│   └── alien.svg
├── clothing/
│   ├── space_suit.svg
│   ├── cape.svg
│   └── jacket.svg
├── accessories/
│   ├── jetpack.svg
│   ├── ray_gun.svg
│   └── antenna.svg
└── hats/
    ├── space_helmet.svg
    ├── star_crown.svg
    └── rocket_hat.svg
```

**Files:**
- `companion/profile.py` — CRUD operations
- `companion/avatar.py` — layered composition
- `companion/catalog.py` — item catalog definition
- `tests/test_companion.py`

**Acceptance Criteria:**
- [ ] Profile creates, saves, loads correctly (YAML/JSON)
- [ ] Avatar renders with base character + equipped items
- [ ] Equipped items layer correctly (no z-order issues)
- [ ] Color tinting works
- [ ] Two sizes render correctly (companion + profile view)
- [ ] Profile persists across sessions

---

### Checkpoint 4.2: Token Economy + Rewards

**Goal:** Predictable reward system tied to worksheet completion.

**Implementation:**

```python
# companion/rewards.py
TOKENS_PER_WORKSHEET = 10
MILESTONE_INTERVAL = 5
MILESTONE_BONUS = 25

def award_completion(profile: LearnerProfile, lesson: int) -> RewardResult:
    """
    1. Award TOKENS_PER_WORKSHEET tokens
    2. Check for milestone (every 5th worksheet)
    3. If milestone: award bonus tokens + unlock milestone item
    4. Update profile progress
    5. Return RewardResult with message and newly unlocked items
    """

def get_affordable_items(profile: LearnerProfile) -> List[CatalogItem]:
    """Return items the child can currently afford."""

def purchase_item(profile: LearnerProfile, item_id: str) -> PurchaseResult:
    """Deduct tokens and add item to unlocked_items."""
```

**Acceptance Criteria:**
- [ ] Tokens awarded correctly per worksheet
- [ ] Milestones trigger at correct intervals
- [ ] Items unlock when purchased with sufficient tokens
- [ ] Cannot purchase without sufficient tokens
- [ ] Progress persists in profile

---

### Checkpoint 4.3: Caregiver Controls

**Goal:** Caregiver/teacher can view progress and adjust accommodations.

**Implementation:**

```python
# companion/caregiver.py
def view_progress(profile: LearnerProfile) -> ProgressReport:
    """Summary of worksheets completed, skills covered, tokens earned."""

def adjust_accommodations(profile: LearnerProfile, **kwargs) -> LearnerProfile:
    """Update chunking level, response format prefs, font size, etc."""

def review_transformation(source_path: str, adapted_path: str) -> ComparisonView:
    """Side-by-side view of source vs adapted worksheet for skill-preservation review."""
```

**CLI:**
```bash
python complete.py --profile ian.yaml --progress           # View progress
python complete.py --profile ian.yaml --set-chunking small # Adjust accommodation
python complete.py --profile ian.yaml --review lesson-5    # Review transformation
```

**Acceptance Criteria:**
- [ ] Progress report shows completion history and skill progression
- [ ] Accommodation changes take effect on next worksheet generation
- [ ] Transformation review shows source and adapted side-by-side

---

### Checkpoint 4.4: End-to-End Pipeline + Golden Tests

> **Note:** This checkpoint is part of **Milestone 3 (MVP)**, not Milestone 4. It is numbered 4.4 for historical reasons but must be completed before the companion layer.

**Goal:** Wire complete pipeline and create golden regression tests.

**Implementation:**

```python
# transform.py (CLI entry point)
@click.command()
@click.option("--input", required=True, help="Path to worksheet photo/scan")
@click.option("--profile", required=True, help="Path to learner profile YAML")
@click.option("--theme", default="space", help="Theme name")
@click.option("--output", default="./output", help="Output directory")
@click.option("--preview", is_flag=True, help="Quick preview instead of print-quality")
def transform(input, profile, theme, output, preview):
    """
    Full pipeline:
    1. Preprocess image → clean page
    2. OCR → SourceWorksheetModel
    3. Extract skill → LiteracySkillModel
    4. Adapt for ADHD → AdaptedActivityModel
    5. Apply theme + avatar → ThemedModel
    6. Render → PDF
    7. Validate → skill-parity, print quality, ADHD compliance
    8. Persist all artifacts
    """
```

**Golden test structure:**
```
tests/golden/
├── phonics-cvc/
│   ├── source.png                    # Synthetic test image (NOT UFLI — original content)
│   ├── test_profile.yaml             # Test learner profile (MVP fields only)
│   ├── expected_source_model.json    # Expected OCR output
│   ├── expected_skill_model.json     # Expected skill extraction
│   ├── expected_adapted_model.json   # Expected ADHD adaptation
│   └── validation_checks.json        # Expected validation results
└── sight-words-gr1/
    └── ...
```

> **Test fixture note:** Golden test images must be original/synthetic worksheets that mimic UFLI layout structure (same region arrangement) but use original word lists and content. UFLI copyrighted pages must not be committed to the repository. Create test fixtures by generating simple worksheets that match the UFLI word-work and decodable-story templates.

**Golden test implementation:**
```python
# tests/test_e2e.py
@pytest.mark.parametrize("case", ["phonics-cvc", "sight-words-gr1"])
def test_golden_pipeline(case):
    """
    Run full pipeline on golden input, compare intermediate models.
    Don't compare exact PDF output (layout may vary).
    Compare: SourceWorksheetModel, LiteracySkillModel, AdaptedActivityModel structure.
    Verify: all validations pass.
    """
```

**Acceptance Criteria:**
- [ ] `python transform.py` runs complete pipeline end-to-end
- [ ] All intermediate artifacts persisted (source model, skill model, adapted model, PDF)
- [ ] Golden tests pass without network access
- [ ] Golden tests catch regressions in extraction, skill mapping, and adaptation
- [ ] Output PDF prints correctly on standard printer

---

### Checkpoint 5.1: Model Adapter Interface (Post-MVP)

**Goal:** Pluggable AI assist layer behind a provider interface.

**Implementation:**

```python
# extract/adapter.py
class ModelAdapter(Protocol):
    def tag_regions(self, image_path: str) -> List[RegionTag]: ...
    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference: ...
    def review_ocr(self, regions: List[SourceRegion]) -> List[OCRCorrection]: ...
    def suggest_adaptations(self, skill: LiteracySkillModel) -> List[AdaptationSuggestion]: ...

class ClaudeAdapter(ModelAdapter): ...
class GeminiAdapter(ModelAdapter): ...
class OpenAIAdapter(ModelAdapter): ...
class LocalVLMAdapter(ModelAdapter): ...  # Qwen2.5-VL, InternVL 2.5

# Config-driven selection
def get_adapter(config: dict) -> ModelAdapter:
    providers = {"claude": ClaudeAdapter, "gemini": GeminiAdapter, ...}
    return providers[config["ai_provider"]](**config["ai_settings"])
```

**Contract enforcement:**
```python
# All model outputs must validate against Pydantic schemas before use
def validated_tag_regions(adapter: ModelAdapter, image: str) -> List[RegionTag]:
    raw = adapter.tag_regions(image)
    return [RegionTag.model_validate(r) for r in raw]  # Strict validation
```

**Acceptance Criteria:**
- [ ] Swap providers by changing config, not code
- [ ] All model outputs validated against strict schemas
- [ ] Pipeline is fully functional and deterministic without AI (no degraded mode, no missing features)
- [ ] When AI is enabled, its contributions are bounded, schema-validated, and auditable (logged with before/after)
- [ ] Output may differ with AI on vs off (AI genuinely helps), but both paths produce valid, complete results
- [ ] Tiered strategy: deterministic OCR → specialized VLM → frontier model

---

### Checkpoint 5.2: Bounded AI Assist Integration (Post-MVP)

**Goal:** AI assists extraction and adaptation without entering the critical path.

**Acceptance Criteria:**
- [ ] AI semantic tagging improves region classification on unknown layouts
- [ ] AI skill inference helps with unfamiliar worksheet families
- [ ] AI OCR review catches errors missed by confidence gating
- [ ] All AI outputs go through schema validation before affecting pipeline
- [ ] All AI contributions are logged with before/after state for auditability
- [ ] Pipeline remains fully functional and produces valid output when AI is disabled (deterministic baseline)

---

### Checkpoint 5.3: Preference-Driven Asset Generation (Post-MVP)

**Goal:** Generate custom theme assets based on child preferences.

**Implementation:**
- Image generation API (nano-banana-pro / DALL-E 3 / Flux) for custom characters/items
- Generate once per preference set → parent approves → cache and reuse forever
- Character consistency via multi-image reference prompting

**Acceptance Criteria:**
- [ ] Generated assets match child's preference profile
- [ ] Parent approval required before assets enter library
- [ ] Approved assets cached and reused (no re-generation)
- [ ] Fallback to curated assets if generation fails or is unavailable

---

## Gotchas, Edge Cases, and Error States

- **Phone photo quality variance:** Preprocessing must handle skew up to 15°, uneven lighting, partial shadows, and background clutter. Fail gracefully with clear error if page cannot be detected.
- **OCR on handwritten worksheets:** PaddleOCR handles printed text well but handwriting recognition is unreliable. Flag handwritten regions as low-confidence for human review.
- **Worksheet layout diversity:** Rule-based heuristics are tuned to one worksheet family for MVP. Unknown layouts should produce a clear "unsupported layout" error, not silent garbage output.
- **Skill extraction ambiguity:** Some worksheets blend skills (e.g., phonics + comprehension). Extract the primary skill based on majority of items; flag for human review if ambiguous.
- **Response format substitution limits:** Not all substitutions preserve the skill. "Circle the correct spelling" → "match the correct spelling" is valid; "write the word from memory" → "circle the word" is NOT (tests different skills). Substitution rules must be skill-aware.
- **Avatar asset layering:** Z-order conflicts when multiple accessories overlap. Define strict layering order in catalog metadata.
- **Profile corruption:** YAML/JSON profiles can be manually edited and broken. Validate on load, provide clear error messages, and keep backups.
- **Print quality on different printers:** Margins and DPI may render differently. Use conservative margin-safe area (0.75") to accommodate printer variance.
- **Rights and derivative works:** Do not include any proprietary curriculum content in the repository or test fixtures. Use only original or clearly open-licensed worksheets.
- **Reward inflation:** If token economy is too generous, child runs out of items to unlock. Design catalog with enough items for the full curriculum (~50 worksheets × 10 tokens = 500 tokens to distribute).

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OCR accuracy insufficient on phone photos | Medium | High | Require 300+ DPI scans for MVP; preprocessing pipeline handles common distortions; confidence gating flags bad extractions |
| ADHD design rules conflict with theme engagement | Medium | Medium | "Calm themes" constraint; every decorative element must pass ADHD compliance check; user testing with target audience |
| Skill-parity validation too strict (blocks valid adaptations) | Medium | Medium | Start permissive, tighten based on observed errors; human review as fallback |
| Skill-parity validation too loose (allows drift) | Low | High | Conservative defaults; require human review for low-confidence extractions and major rewrites |
| Avatar asset creation bottleneck | Medium | Low | Start with curated packs (20-30 items per theme); generative assets are post-MVP |
| Profile data loss | Low | High | YAML files are human-readable and recoverable; auto-backup on write |
| Child loses interest in avatar customization | Low | Medium | Test early with target audience; adjust reward cadence based on engagement signals |
| ReportLab rendering limitations for complex layouts | Low | Medium | Worksheets are structurally simple; if needed, supplement with Pillow for specific elements |

---

## Model Strategy: Future-Proofing for AI Improvement

1. **Model adapter boundary:** `extract/adapter.py` wraps all AI calls behind a Protocol interface. Swap providers by config.
2. **Master image permanence:** original captures stored forever for reprocessing with better models.
3. **Tiered extraction:** deterministic OCR (free, offline) → specialized OCR-VLMs → frontier multimodal models.
4. **Prompt versioning:** extraction/tagging prompts versioned separately. New model → update prompt → pipeline benefits.
5. **Evaluation harness:** golden test set measures quality improvements before switching models.
6. **Graceful expansion:** today (single-page, one family, curated assets) → better models unlock (multi-page, diverse layouts, handwriting, generative assets).

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-03-07 | Initial plan based on PaperBanana architecture |
| 0.2.0 | 2026-03-07 | Dropped PaperBanana; deterministic pipeline with AI assist layer |
| 0.3.0 | 2026-03-07 | Added physical paper input, image-native capture |
| 0.4.0 | 2026-03-07 | Added ADHD-optimized design and progressive avatar system |
| 0.5.0 | 2026-03-07 | Added K-3 grade levels, Ontario/BC curriculum alignment |
| 0.6.0 | 2026-03-07 | Reframed as skill-preserving adaptation engine; added LiteracySkillModel and ADHD Activity Adapter stages |
| 0.7.0 | 2026-03-07 | Added companion layer, caregiver controls, operational signals, explicit anti-patterns |
| 1.0.0 | 2026-03-07 | Full implementation plan with detailed checkpoints, acceptance criteria, risk assessment, and git repo integration |
| 1.1.0 | 2026-03-07 | Review feedback: narrowed MVP to core engine (companion post-core); fixed skill-parity validator to preserve instructional intent not word lists; resolved AI-assist contradiction (deterministic baseline, bounded auditable AI); fixed CI Tesseract dependency and PDF/A stage misalignment; softened BC curriculum claims; corrected ADHD evidence (removed OpenDyslexic, fixed reward language); clarified Pydantic as single contract layer |
| 1.2.0 | 2026-03-07 | Evidence-consistent ADHD design overhaul: rewrote Visual Design Rules, Content Restructuring, and Engagement Elements sections citing PMC10453933, PMC5280087, Longwood/BCH ADHD tools; established "game-themed structure, visually calm execution" principle; added decoration budget, chunking targets, effort-based rewards, self-assessment, bounded choice, avatar placement rules; identified UFLI Foundations as primary input family |
| 1.3.0 | 2026-03-07 | Split UFLI into two known templates (word work + decodable story) with distinct heuristics; added UFLI rights boundary (private input only, not repo fixtures); restrained game framing (labels visually subordinate, no extra mechanics to learn); softened research language throughout to "evidence-consistent" where claims are inferred |
| 1.4.0 | 2026-03-07 | Accuracy pass for clean build: added template_type to SourceWorksheetModel and Pydantic schema; added UFLI-specific region types to SourceRegion enum; split skill extractor logic by template type; made companion-dependent fields Optional (reward_event, avatar_prompts, avatar_image, reward_state) so MVP builds without companion; separated LearnerProfile into MVP-required vs companion-optional fields; noted golden test fixtures must be synthetic (not UFLI); added self_assessment field to AdaptedActivityModel; updated acceptance criteria for both UFLI templates; noted Checkpoint 4.4 is in Milestone 3 |
