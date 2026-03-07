---
description: Validate current code against the implementation plan architecture and design decisions
argument-hint: "[focus area or 'full']"
---

You are validating the worksheet-builder codebase against its implementation plan.

Focus area: $ARGUMENTS

Read `worksheet-builder-consolidated-plan.md` and `.claude/worksheet-project-context.md`, then evaluate the codebase:

1. **Pipeline integrity:**
   - Are all 8 stages implemented (or stubbed) in the correct order?
   - Does data flow through the correct models at each stage?
   - Is the pipeline wired correctly in `transform.py`?

2. **Decision compliance** — check each decision from the Key Decisions Log:
   - D1: No PaperBanana code or architecture
   - D2: Deterministic core works without AI/API calls
   - D3: Image-native input (master images as authoritative, PDFs derived)
   - D4: Skill-preserving, not page-faithful (LiteracySkillModel is the preservation target)
   - D5: Vector-first PDF rendering (ReportLab, text as vector)
   - D6: PaddleOCR primary, Tesseract fallback
   - D7: Pydantic for all data contracts
   - D8: Curated theme assets (no on-demand generation in MVP)
   - D9: CLI-only companion
   - D10: ADHD anti-patterns are hard constraints (no loot boxes, etc.)
   - D11: K-3 Ontario/BC curriculum scope
   - D12: Open-licensed content only

3. **Module boundaries:**
   - Are imports between modules following the dependency direction (capture → extract → skill → adapt → theme → render → validate)?
   - Is there any circular dependency?
   - Is the AI assist layer properly isolated behind `extract/adapter.py`?

4. **Determinism:**
   - Are there any sources of non-determinism in the critical path? (random, datetime.now, UUIDs, network calls)
   - Is idempotency maintained? (same inputs → same outputs)

5. **Missing pieces:**
   - What's in the plan but not yet in the code?
   - What's in the code but not in the plan? (scope creep)

Produce a structured report:
```
## Architecture Compliance Report

### Overall: [ALIGNED / DRIFT DETECTED]

### Decision Compliance
| Decision | Status | Notes |
|----------|--------|-------|
| D1-D12 | ... | ... |

### Pipeline Integrity: [OK / ISSUES]
### Module Boundaries: [OK / ISSUES]
### Determinism: [OK / ISSUES]
### Missing: [list]
### Out of Scope: [list]
```
