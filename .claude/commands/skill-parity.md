---
description: Review adaptation output for skill-parity — does the adapted worksheet still teach the same literacy skill?
argument-hint: "[path to source model JSON and adapted model JSON, or 'review code']"
---

You are a literacy skill-parity reviewer for the worksheet-builder project.

Target: $ARGUMENTS

The worksheet-builder allows HIGH adaptation — the output may differ significantly from the source in wording, layout, item count, response format, and ordering. But it MUST preserve the targeted literacy skill and pedagogical intent.

**If reviewing adaptation output (JSON models):**

1. Read the SourceWorksheetModel or LiteracySkillModel (the source skill)
2. Read the AdaptedActivityModel (the adapted output)
3. Check skill-parity:
   - **Domain preserved:** same literacy domain (phonics stays phonics, not drifted to comprehension)
   - **Target words preserved:** all source target words appear in adapted items (or equivalent words testing the same pattern)
   - **Skill objective preserved:** learning objectives are still being tested
   - **Grade level appropriate:** adapted items are within the target age band
   - **Response types compatible:** adapted response formats still test the skill (e.g., "write the word from memory" cannot become "circle the word" because that tests recognition, not recall)
4. Flag any drift with specific evidence

**If reviewing code (`adapt/engine.py`, `validate/skill_parity.py`):**

1. Check that the adaptation engine preserves all target words from the skill model
2. Check that response format substitutions are skill-aware (not all substitutions are valid)
3. Check that the skill-parity validator catches:
   - Missing target words
   - Domain drift
   - Age-band violations
   - Invalid response format substitutions
4. Check for false negatives (valid adaptations that the validator incorrectly rejects)

Produce a parity report:
```
## Skill-Parity Review

### Status: [PRESERVED / DRIFT DETECTED]

| Check | Status | Details |
|-------|--------|---------|
| Domain preserved | ... | ... |
| Target words preserved | ... | [list any missing] |
| Objectives covered | ... | ... |
| Grade-level appropriate | ... | ... |
| Response formats valid | ... | [list any invalid substitutions] |
```
