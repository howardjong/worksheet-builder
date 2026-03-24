---
name: Pipeline Stage Implementation
description: This skill should be used when the user asks to "implement a stage", "build the pipeline", "wire the stages", "create the extractor", "build the adapter", "implement capture", "implement OCR", or when working on transform.py or any pipeline stage module (capture/, extract/, skill/, adapt/, theme/, render/, validate/).
version: 1.0.0
---

# Pipeline Stage Implementation Guide

The worksheet-builder has 8 pipeline stages. Each stage has strict input/output contracts and determinism requirements.

## Stage Order and Data Flow

```
[1] capture/preprocess.py    → preprocessed image (PNG file path)
[2] capture/store.py         → master image record (MasterRecord)
[3] extract/ocr.py           → OCR result (text + bboxes + confidence)
    extract/heuristics.py    → SourceWorksheetModel
[4] skill/extractor.py       → LiteracySkillModel
[5] adapt/engine.py          → AdaptedActivityModel
[6] theme/engine.py          → themed model (with avatar + decoration assets)
[7] render/pdf.py            → PDF file path
[8] validate/skill_parity.py → ValidationResult
    validate/print_checks.py → ValidationResult
    validate/adhd_compliance.py → ValidationResult
```

## Determinism Rules (Critical)

These MUST be in the deterministic core (no AI dependency):
- All preprocessing operations (OpenCV)
- OCR baseline (PaddleOCR / Tesseract)
- Schema validation
- Skill taxonomy mapping
- Age-band guardrails
- Activity assembly rules (chunking, scaffolding)
- Layout geometry and placement
- PDF rendering
- All validation checks

These may OPTIONALLY use AI (behind extract/adapter.py):
- Semantic tagging of regions
- Skill inference from unknown layouts
- Low-confidence OCR review
- Activity form suggestions
- QA on semantic drift

## AI Adapter Boundary

All AI calls MUST go through `extract/adapter.py`:
```python
class ModelAdapter(Protocol):
    def tag_regions(self, image_path: str) -> List[RegionTag]: ...
    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference: ...
```

AI outputs MUST validate against Pydantic schemas before entering the pipeline.
The pipeline MUST produce identical output with AI disabled.

## Implementation Checklist for Each Stage
1. Input: accept the correct Pydantic model (or file path for stage 1)
2. Process: deterministic logic with no network calls
3. Output: return the correct Pydantic model, validated
4. Persist: save intermediate artifact to `artifacts/` directory
5. Test: unit tests in `tests/test_<module>.py`
6. Idempotent: same inputs → same outputs, always
