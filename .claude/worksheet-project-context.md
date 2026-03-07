# Worksheet Builder — Running Context

> This is the running context document for session-to-session handoffs and multi-agent coordination.
> **Read this first** when starting a new session or picking up work.
> **Update this** at the end of every session with current state, decisions, and next steps.

---

## Current State

**Status:** Pre-implementation — planning complete, repo initialized, no code written yet.
**Branch:** `main`
**Last Updated:** 2026-03-07

### Milestone Progress

| Milestone | Status | Checkpoints |
|-----------|--------|-------------|
| M1: Foundation + Source Extraction | **Not started** | 1.1, 1.2, 1.3, 1.4 |
| M2: Skill Extraction + ADHD Adaptation | Not started | 2.1, 2.2, 2.3, 2.4 |
| M3: Theme + Render + Validate | Not started | 3.1, 3.2, 3.3 |
| M4: Companion + Avatar + E2E | Not started | 4.1, 4.2, 4.3, 4.4 |
| M5: AI Assist + Generative (post-MVP) | Not started | 5.1, 5.2, 5.3 |

### What Exists Now
- `worksheet-builder-consolidated-plan.md` — full implementation plan with 11 checkpoints
- `CLAUDE.md` — project guidance for Claude Code
- `.gitignore` — excludes data dirs, python artifacts, IDE files
- `.claude/worksheet-project-context.md` — this file

### What's Next
**Start with Checkpoint 1.1: Repository Scaffold + CI**
- Create `pyproject.toml` with project metadata, ruff/mypy config
- Create `requirements.txt` with pinned dependencies
- Create `Makefile` with lint/typecheck/test targets
- Create `.github/workflows/ci.yml`
- Create all package directories with `__init__.py` files
- Create empty test files
- Verify: `make lint && make typecheck && make test` all pass

---

## Key Decisions Log

Decisions made during planning that implementers must respect:

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| D1 | PaperBanana dropped as architecture | It generates academic illustrations, not worksheet adaptations | 2026-03-07 |
| D2 | Deterministic core, AI as optional assist | Pipeline must work offline without API calls | 2026-03-07 |
| D3 | Physical paper as image-native input | Master images are the authoritative artifact, PDFs are derived | 2026-03-07 |
| D4 | Skill-preserving, not page-faithful | Preserve literacy skill and pedagogical intent, not exact layout/wording | 2026-03-07 |
| D5 | ReportLab for vector-first PDF rendering | Text stays vector (searchable, sharp), raster only for illustrations | 2026-03-07 |
| D6 | PaddleOCR primary, Tesseract fallback | PaddleOCR better on camera photos; Tesseract as offline fallback | 2026-03-07 |
| D7 | Pydantic for all data contracts | Strict schema validation between every pipeline stage | 2026-03-07 |
| D8 | Curated theme assets for MVP | No on-demand image generation; pre-made asset packs per theme | 2026-03-07 |
| D9 | CLI-only companion for MVP | Web/mobile companion deferred to post-MVP | 2026-03-07 |
| D10 | ADHD anti-patterns are hard constraints | No loot boxes, streak punishment, leaderboards, variable-ratio rewards — ever | 2026-03-07 |
| D11 | K-3 Ontario/BC curriculum scope | Ages 5-8, aligned with Science of Reading / Right to Read | 2026-03-07 |
| D12 | Open-licensed content only for MVP | No proprietary curriculum (UFLI etc.) until rights are clarified | 2026-03-07 |

---

## Architecture Quick Reference

### Pipeline Stages & Data Flow
```
[1] Capture    → master page image (PNG)
[2] Normalize  → preprocessed image (OpenCV)
[3] Extract    → SourceWorksheetModel (Pydantic)
[4] Skill      → LiteracySkillModel (Pydantic)
[5] Adapt      → AdaptedActivityModel (Pydantic)
[6] Theme      → themed model with avatar + decoration zones
[7] Render     → PDF (ReportLab, vector text)
[8] Validate   → skill-parity, age-band, print, ADHD compliance
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
companion/  → Checkpoints 4.1, 4.2, 4.3
transform.py + complete.py → Checkpoint 4.4
extract/adapter.py → Checkpoint 5.1 (post-MVP)
```

### Key Files (once created)
| File | Purpose |
|------|---------|
| `transform.py` | CLI: transform worksheets (full pipeline) |
| `complete.py` | CLI: mark completion, award tokens, show unlocks |
| `extract/adapter.py` | Model adapter interface (swap AI providers by config) |
| `adapt/rules.py` | ADHD accommodation rules (chunking tables, substitutions) |
| `skill/taxonomy.py` | K-3 literacy skill taxonomy |
| `validate/skill_parity.py` | Skill-preservation validation |
| `validate/adhd_compliance.py` | ADHD design rules enforcement |

---

## Open Questions

| # | Question | Context | Status |
|---|----------|---------|--------|
| Q1 | Which specific worksheet family to use for MVP? | Need original/open-licensed K-3 literacy worksheets | Open |
| Q2 | OpenDyslexic font licensing for embedded PDF? | Listed as option for ADHD-friendly sans-serif | Open |
| Q3 | PaddleOCR vs Tesseract: which is easier to install cross-platform? | Affects developer setup friction | Open |

---

## Gotchas Discovered

_None yet — add here as implementation reveals issues._

---

## Session Log

### Session 1 — 2026-03-07 (Planning)
**Participants:** User + Claude Opus 4.6
**Duration:** Full planning session
**What happened:**
- Reviewed original worksheet-builder-plan.md (PaperBanana-based)
- Conducted deep research via Perplexity on: PaperBanana architecture, nano-banana-pro, PDF transformation approaches, multimodal OCR models, ADHD worksheet design, avatar engagement mechanics, Ontario/BC K-3 curriculum
- Incorporated multiple rounds of external feedback
- Evolved plan through 7 versions (0.1.0 → 1.0.0)
- Key pivots: dropped PaperBanana, added physical paper input, added ADHD design, added avatar progression, added skill-preserving adaptation model, added companion layer with caregiver controls
- Produced final implementation plan with 11 checkpoints, acceptance criteria, risk assessment
- Initialized git repo, set remote to howardjong/worksheet-builder, made first commit

**What's next:** Checkpoint 1.1 — Repository scaffold + CI
