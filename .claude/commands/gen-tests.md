---
description: Generate pytest tests for a pipeline stage module with project-specific patterns
argument-hint: "[module path, e.g. capture/preprocess.py or adapt/engine.py]"
---

You are generating pytest tests for a module in the worksheet-builder project.

Target module: $ARGUMENTS

Read the module and its associated schema (if any), then generate comprehensive tests following these project conventions:

**Test structure:**
- Test file goes in `tests/test_<module_name>.py`
- Use `pytest` with plain functions (not unittest classes)
- Use `tmp_path` fixture for any file I/O
- Use `@pytest.fixture` for reusable test data (sample images, models, profiles)
- Use `@pytest.mark.parametrize` for testing across grade levels (K, 1, 2, 3)

**What to test for each pipeline stage:**

- **capture/preprocess.py:** image loads, deskew corrects skew, denoise reduces noise, same input → same output (deterministic), handles missing file gracefully
- **extract/ocr.py:** text extraction accuracy, bounding box localization, confidence scores present, low-confidence flagging works
- **extract/heuristics.py:** region classification (title, instruction, question, answer_blank), schema validation of output
- **skill/extractor.py:** domain identification, grade level inference, target word extraction, parametrize across grade levels
- **skill/taxonomy.py:** all domains have valid skills, grade ranges are consistent, no orphaned skills
- **adapt/engine.py:** chunking respects grade limits, instructions are numbered with bold verbs, worked examples present, response format substitutions are skill-aware, reward events generated, time estimates reasonable
- **adapt/rules.py:** accommodation rules build correctly from profile, chunking tables are complete for all grades × levels
- **theme/engine.py:** theme applies fonts/colors from config, decoration zones respected, avatar placed in correct position
- **render/pdf.py:** output is valid PDF, correct page dimensions, text is vector (not rasterized), fonts embedded, content within margins
- **validate/skill_parity.py:** catches missing target words, catches domain drift, catches age-band violations, passes valid adaptations
- **validate/adhd_compliance.py:** catches each ADHD rule violation, catches each anti-pattern, passes compliant output
- **companion/profile.py:** CRUD operations, YAML serialization roundtrip, accommodation updates
- **companion/avatar.py:** layered composition, equipped items render, color tinting works
- **companion/rewards.py:** tokens award correctly, milestone detection, purchase with sufficient/insufficient tokens

**Test data conventions:**
- Use inline fixtures for small data (don't create separate fixture files for simple cases)
- For image tests, create minimal synthetic images with OpenCV in fixtures (don't require real worksheet photos)
- For model tests, create minimal valid Pydantic model instances
- For golden tests (test_e2e.py), reference `tests/golden/` directory

Generate the test file with clear comments explaining what each test validates.
