---
name: Pipeline Data Contracts
description: This skill should be used when the user asks to "create a model", "define a schema", "add a field", "modify a data class", "create a Pydantic model", or when code in any schema.py file or data model is being created or modified. It ensures all pipeline stage boundaries use strict Pydantic contracts.
version: 1.0.0
---

# Pipeline Data Contracts

All data flowing between pipeline stages MUST use Pydantic v2 models with strict validation.

## Required Models and Locations

| Model | File | Producer | Consumer |
|-------|------|----------|----------|
| SourceWorksheetModel | extract/schema.py | extract/ocr.py + heuristics.py | skill/extractor.py |
| LiteracySkillModel | skill/schema.py | skill/extractor.py | adapt/engine.py |
| AdaptedActivityModel | adapt/schema.py | adapt/engine.py | theme/engine.py, render/pdf.py |
| LearnerProfile | companion/profile.py | companion/profile.py (CRUD) | adapt/engine.py, render/pdf.py |
| RewardEventModel | adapt/rewards.py | adapt/rewards.py | companion/rewards.py |

## Contract Rules

1. **Every field must have a type annotation** — no `Any` or `dict` without inner types
2. **Use `model_validate()` at every stage boundary** — never pass raw dicts between stages
3. **Required vs Optional must match the plan** — don't make required fields Optional for convenience
4. **Validators for domain constraints:**
   - `grade_level` must be one of: "K", "1", "2", "3"
   - `domain` must be one of: "phonemic_awareness", "phonics", "fluency", "vocabulary", "comprehension", "writing"
   - `confidence` must be 0.0-1.0
   - `chunking_level` must be one of: "small", "medium", "large"
5. **Idempotency fields required:** `source_image_hash`, `pipeline_version`, `learner_profile_hash`, `theme_id`
6. **No sources of non-determinism in models:** no `datetime.now()`, `uuid4()`, or `random` in default values
7. **Serialization roundtrip:** all models must survive `model.model_dump_json()` → `Model.model_validate_json()`

## When creating or modifying models:
- Import from `pydantic import BaseModel, Field, field_validator`
- Use `Field(description=...)` for documentation
- Write a `model_validate` roundtrip test for every new model
- Check that producer output fields match consumer input expectations
