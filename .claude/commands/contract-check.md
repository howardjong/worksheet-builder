---
description: Validate Pydantic data contracts between pipeline stages for completeness and consistency
argument-hint: "[module name or 'all']"
---

You are validating data contracts in the worksheet-builder pipeline.

Scope: $ARGUMENTS

Read the data contract definitions from `worksheet-builder-consolidated-plan.md` (section: "Data Contracts") as the specification.

Then inspect the actual Pydantic models in the codebase:

1. **Schema completeness** — for each contract in the plan, check:
   - Does the Pydantic model exist in the expected location?
   - Does it have all fields specified in the plan?
   - Are field types correct (str, List[str], Optional, etc.)?
   - Are validators and constraints present where needed?

2. **Cross-stage consistency** — check that:
   - SourceWorksheetModel output fields match what LiteracySkillModel extraction expects as input
   - LiteracySkillModel output fields match what AdaptedActivityModel adaptation expects
   - LearnerProfile fields are complete for all accommodation rules that reference them
   - RewardEventModel is correctly integrated into AdaptedActivityModel chunks

3. **Idempotency contract** — check that:
   - Hash computation includes all required keys (master_image, profile, theme, pipeline_version)
   - Same inputs produce same model outputs (no randomness, timestamps, or UUIDs in models)

4. **Serialization roundtrip** — check that:
   - Models can serialize to JSON and deserialize back without data loss
   - Schema version field exists for future migrations

Produce a contract validation report:
```
## Data Contract Validation Report

### Models Found: [count] / [expected]

| Contract | Location | Status | Issues |
|----------|----------|--------|--------|
| SourceWorksheetModel | extract/schema.py | VALID/MISSING/INCOMPLETE | ... |
| LiteracySkillModel | skill/schema.py | ... | ... |
| AdaptedActivityModel | adapt/schema.py | ... | ... |
| LearnerProfile | companion/profile.py | ... | ... |
| RewardEventModel | adapt/rewards.py | ... | ... |

### Cross-Stage Issues: [list any mismatches]
### Idempotency Issues: [list any non-determinism]
```
