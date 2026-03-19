# Plan: Add Missing Critical Literacy Activities to Worksheet Pipeline

**Status:** Ready for implementation
**Created:** 2026-03-18
**Priority:** High — addresses core pedagogical gaps in worksheet output

## Context

Lesson 73 worksheets were generated without any reading/passage section. The UFLI corpus has a full decodable passage ("Plane Race", ~150 words) and a "Roll and Read" fluency word list for lesson 73, but neither made it into the worksheets because:

1. The home practice PDF is correctly classified as `ufli_word_work` — but that template extractor never looks up corpus passages
2. `adapt_lesson()` only builds the Story Time read-aloud section when `passages` exist in the skill model — they're always empty for word work extractions
3. The corpus data (`data/ufli/normalized.jsonl`) has the content but isn't consulted during skill extraction

### Research Basis

Research (PMC7518569, PMC8862114, PMC5902514, UFLI's 8-step lesson routine) identifies **6 essential activities** for ADHD literacy (ages 5-8). Current coverage:

| Activity | UFLI Step | Status | Notes |
|----------|-----------|--------|-------|
| Word Building/Work | 4-6 | Implemented | Word chains, sorts |
| Heart Word Practice | 7 | Implemented | Sight word trace/write |
| Blending/Decoding | 5-6 | Partial | Trace, match, circle |
| Phonemic Awareness Warm-Up | 1-2 | **MISSING** | Sound boxes needed |
| Connected Text / Fluency | 8 | **MISSING** | Code exists but never triggers |
| Roll and Read Fluency | 8 | **MISSING** | Corpus data exists but unused |

Key research findings:
- Tamm et al. (2017): intensive reading intervention alone produces equivalent decoding fluency gains to intervention + ADHD medication combined
- Optimal session: 3-5 varied activity types, each 3-5 min, total 20-30 min
- UFLI's "predictable structure, novel content" approach is ideal for ADHD
- Connected text reading supports transfer from word-level to meaningful contexts
- Repeated reading builds automaticity disrupted by ADHD-related processing speed challenges

### Root Cause Analysis

The `_extract_word_work()` function in `skill/extractor.py` extracts these item types from the home practice PDF:
- `word_list`, `word_chain`, `chain_script`, `sight_words`, `sentence`

It does NOT extract `passage` items because the home practice PDF doesn't contain the decodable story. The story lives in:
- The decodable passage PDF (separate file, classified as word work due to OCR issues)
- `data/ufli/normalized.jsonl` field `decodable_text` (reliably extracted from PPTX)
- `data/ufli/normalized.jsonl` field `additional_text` (Roll and Read word lists)

The fix: enrich the skill model from the corpus after OCR extraction.

---

## Implementation Plan

### Phase 1: Carry `lesson_number` through the pipeline

**Files:** `skill/schema.py`, `skill/extractor.py`

- Add `lesson_number: int | None = None` field to `LiteracySkillModel` (after `template_type`)
- Pass `lesson_number` in `_extract_word_work()`, `_extract_decodable_story()`, `_extract_generic()` constructors
- Non-breaking: optional field with default `None`

### Phase 2: Corpus lookup module

**New file:** `corpus/ufli/lookup.py`

- `CorpusLookupResult` dataclass with fields: `lesson_id`, `decodable_text`, `additional_text`, `concept`
- `lookup_lesson(lesson_number: int, data_dir: str = "data/ufli") -> CorpusLookupResult | None`
  - Reads `normalized.jsonl`, finds matching lesson
  - Caches parsed JSONL in module-level dict for batch mode
- Deterministic file lookup, no API calls (consistent with "AI is optional assist only" principle)

### Phase 3: Enrich skill model from corpus

**File:** `skill/extractor.py`

- After building `LiteracySkillModel` in `_extract_word_work()`, call `_enrich_from_corpus(model, lesson_number)`
- `_enrich_from_corpus()`:
  - Looks up corpus via Phase 2 module
  - If `decodable_text` exists and model has no passage items:
    - Add `SourceItem(item_type="passage", content=cleaned_text, source_region_index=-1, metadata={"source": "corpus"})`
  - If `additional_text` exists:
    - Add `SourceItem(item_type="roll_and_read", content=text, source_region_index=-1, metadata={"source": "corpus"})`
- `_clean_corpus_passage(text: str) -> str` helper:
  - Strips copyright lines (`(c) 20\d\d University of Florida`)
  - Strips "Lesson NN: pattern" headers
  - Strips "Illustrate the story here:" boilerplate
  - Extracts just story title + narrative text
  - Trims to ~200 words for worksheet display

**Result:** Story Time worksheet automatically gets the passage. Existing `_build_story_chunks()` (adapt/engine.py:584) already handles `passage` items with read-aloud rendering and comprehension questions. Existing `_draw_read_aloud_item()` (render/pdf.py:817) already renders passage text in styled blue box. No adapt/engine.py or render/pdf.py changes needed for this phase.

### Phase 4: Add phonemic awareness warm-up (sound boxes)

**Files:** `adapt/engine.py`, `render/pdf.py`

**adapt/engine.py:**
- New `_build_warmup_chunk(target_words, skill, rules) -> ActivityChunk | None`:
  - Select 3 target words
  - Create items with `response_format="sound_box"`
  - `options` = phoneme segments (e.g., `["s", "k", "y"]` for "sky")
  - `metadata={"display": "elkonin", "phoneme_count": N}`
  - Instructions: "Say the word. Tap each sound. Write the sounds in the boxes."
  - Time estimate: "About 1 minute"
  - Returns `None` for grade levels "2" and "3" (phonemic awareness is K-1)
- In `adapt_lesson()` (~line 189): prepend warmup chunk to Word Discovery chunks
- New `_segment_phonemes(word: str) -> list[str]` helper for phoneme segmentation

**render/pdf.py:**
- New `_draw_sound_box_item()` renderer:
  - Target word above in large type
  - Row of empty boxes (one per phoneme, ~0.8" square, rounded corners)
  - Uses existing `examples` color for box borders
- New `_estimate_sound_box_height()` for layout calculation
- Add case in `_estimate_item_height()` and rendering dispatch (~line 521)

### Phase 5: Add Roll and Read fluency chunk

**File:** `adapt/engine.py`

- In categorization loop (~line 145), add `roll_and_read` item type handling:
  ```python
  elif si.item_type == "roll_and_read":
      roll_words = _parse_roll_and_read(si.content)
      roll_and_read_items.extend(roll_words)
  ```
- New `_parse_roll_and_read(text: str) -> list[str]`:
  - Parse newline-separated word list
  - Filter out copyright lines, lesson headers
  - Return clean word list
- New `_build_roll_and_read_chunk(words, skill, rules) -> ActivityChunk | None`:
  - Select 5 words (mix of base + inflected forms, respecting ADHD chunk limit)
  - Items with `response_format="read_aloud"` (reuses existing renderer)
  - Micro goal: "Read these words fast!"
  - Instructions: "Read each word out loud. Try to read them faster each time!"
  - Time estimate: "About 1 minute"
- Appended to Word Builder worksheet chunks (~line 244)

### Phase 6: Time budget validation

**File:** `validate/adhd_compliance.py`

- Add cross-worksheet total time check for multi-worksheet mode
- Warn if total estimated time > 20 minutes
- New budget: Word Discovery ~6 min (+1 warmup) + Word Builder ~6 min (+1 roll-and-read) + Story Time ~7 min = **~19 min total**

### Phase 7: Tests

- `tests/test_skill.py`: lesson_number propagation, corpus enrichment, passage cleaning
- `tests/test_adapt.py`: warmup chunk generation, roll-and-read chunk, Story Time with passages, time budget ≤ 20 min
- `tests/test_render.py`: sound_box rendering

---

## Implementation Order

```
Phase 1 (skill/schema.py, skill/extractor.py)  ──┐
                                                   ├── Phase 3 (skill/extractor.py) ──┐
Phase 2 (corpus/ufli/lookup.py)               ──┘                                     │
                                                                                       ├── Phase 6 ── Phase 7
Phase 4 (adapt/engine.py, render/pdf.py)      ─────────────────────────────────────────┤
                                                                                       │
Phase 5 (adapt/engine.py)                     ─────────────────────────────────────────┘
```

Phases 1+2 can run in parallel. Phases 4+5 can run in parallel (independent features). Phase 3 depends on 1+2. Phases 6+7 depend on all prior phases.

---

## Verification

1. Re-run lesson 73 pipeline:
   ```bash
   python transform.py --input data/ufli/raw/73/home_practice_pdf.pdf \
     --profile profiles/ian.yaml --theme roblox_obby \
     --output ./output/lesson73_test/
   ```

2. Verify adapted_model JSON contains:
   - `passage` source items with `metadata.source = "corpus"`
   - `roll_and_read` source items
   - `sound_box` response format in Word Discovery chunks

3. Open generated PDFs and confirm:
   - Word Discovery has sound box warm-up section with Elkonin boxes
   - Word Builder has Roll and Read section with fluency words
   - Story Time has "Read the story" section with "Plane Race" passage + comprehension questions

4. Run `make test` — all existing + new tests pass

5. Check total time estimates across worksheets ≤ 20 minutes

---

## Key Files Reference

| File | Role |
|------|------|
| `skill/schema.py` | Add `lesson_number` field |
| `skill/extractor.py` | Corpus enrichment, lesson_number propagation |
| `corpus/ufli/lookup.py` | New: corpus data lookup |
| `data/ufli/normalized.jsonl` | Corpus source (decodable_text, additional_text) |
| `adapt/engine.py` | Warmup chunk, Roll and Read chunk, item type routing |
| `render/pdf.py` | Sound box renderer |
| `validate/adhd_compliance.py` | Time budget validation |
| `adapt/engine.py:584` | Existing `_build_story_chunks()` — handles passages already |
| `render/pdf.py:817` | Existing `_draw_read_aloud_item()` — renders passages already |
| `adapt/engine.py:836` | Existing `_generate_comprehension_questions()` — generates questions from passages |
