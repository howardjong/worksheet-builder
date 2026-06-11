# ImageGenRenderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full-page image-generation renderer (`image_gen`) that produces worksheets at the visual quality of the ChatGPT baseline (`samples/output/ian-worksheet-geo-dash-1.png`), gated by text-fidelity and character-consistency judges, with regeneration on failure and a provider fallback chain (Gemini image → OpenAI gpt-image-2 → deterministic `pdf_classic`).

**Architecture:** A fourth `RenderStrategy` consumes the existing renderer-neutral `WorksheetDesignSpec` (extended with section grouping), assembles a model-agnostic page prompt with ADHD constraints expressed as damping language, calls an image provider chain with the Learning Buddy reference image, validates each generated page with two vision gates (exact-text readback + character judge), regenerates up to 3 times per provider, caches the first gate-passing page by content hash, and wraps the PNG as a US Letter PDF with an invisible searchable text layer. If every provider is exhausted, it falls back to the existing `pdf_classic` renderer.

**Tech Stack:** Python 3.11+, Pydantic v2, `google-genai` SDK (already used in `render/asset_gen.py`), `openai` SDK (already used in `adapt/llm_judge.py`), PyMuPDF/`fitz` (already used in `render/merge.py`), pytest with monkeypatch (no network in tests).

**Owner decisions locked in (2026-06-11):**
- Full-page generation including all instructional text, with OCR/vision readback gates and bounded regeneration. No hybrid text overlay in v1.
- Provider chain: Gemini image first, OpenAI gpt-image-2 second. Seedream is a future registry entry, not v1 code.
- Quality-first regen budget: up to 3 attempts per page per provider.
- Ian-only scope: profile-specific shortcuts stay; multi-child generalization is logged debt.
- `pdf_classic` stays the default render mode until `image_gen` passes the battery (Task 7) and the owner promotes it.

---

## Context for an engineer with zero prior exposure

- **Pipeline:** photo → extract → `LiteracySkillModel` → adapt → `AdaptedActivityModel` (1–3 mini-worksheets) → theme → render → validate. Entry point `transform.py`, orchestration in `run_pipeline_collect_artifacts()`.
- **Renderer seam:** `render/strategies.py` defines `RenderStrategy` (protocol), `RenderContext` (frozen dataclass of inputs), `RenderResult` (Pydantic). `resolve_render_strategy(mode)` maps mode string → strategy. Three strategies exist; you are adding the fourth.
- **Renderer-neutral contract:** `render/design_spec.py` defines `WorksheetDesignSpec` with `VisualBudget` (ADHD limits), `required_text` (exact strings that must appear), `answer_zones`, page geometry. `compile_worksheet_design_spec()` builds it from the adapted model + theme + profile. Today it flattens chunk structure into `required_text`; Task 1 adds `sections` so the image prompt can preserve grouping.
- **Character identity:** `companion/character_identity.py` resolves a `CharacterIdentity` (character description block, canonical/pose reference image paths, fingerprinted `identity_version`) from the learner profile + theme. `render/asset_gen.py:_reference_bytes_from_identity()` loads reference PNG bytes. `companion/character_judge.py:judge_character_consistency(ref_bytes, gen_bytes, criteria)` returns a `CharacterJudgeResult` via Gemini, falling back to OpenAI vision.
- **Print validation:** `validate/print_checks.py` hard-fails PDFs with no extractable text ("vector_text" check). The PDF wrap step therefore embeds an invisible text layer (`render_mode=3`), which also makes the PDF searchable.
- **Env conventions:** `.env` is auto-loaded by `transform.py`. Keys: `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `OPENAI_API_KEY`. `WORKSHEET_SKIP_ASSET_GEN=1` disables all image generation (tests/CI rely on this).
- **Commands:** `make lint` (ruff), `make typecheck` (mypy), `make test` (pytest). Use `.venv/bin/...` binaries. Tests must pass offline with no API keys.
- **Commits:** a pre-commit hook BLOCKS `Co-Authored-By: Claude` trailers — do not add them. Hooks also run ruff, ruff-format, and whitespace fixers on commit.

## File structure

| File | Action | Responsibility |
|---|---|---|
| `.claude/worksheet-project-context.md` | Modify | Decision log entries D26–D28 |
| `AGENTS.md` | Modify | Replace "No AI in critical path" constraint |
| `render/design_spec.py` | Modify | Add `SectionSpec`/`SectionItemSpec`, `sections`, `self_assessment`, `break_prompt`; add `"image_gen"` to `RenderMode` |
| `render/image_prompt_builder.py` | Create | Model-agnostic full-page prompt assembly incl. ADHD damping block |
| `render/image_providers.py` | Create | `ImageProvider` protocol, Gemini + OpenAI adapters, fallback chain resolution |
| `render/page_gates.py` | Create | Text-fidelity readback gate + character gate + combined `PageGateReport` |
| `render/image_gen.py` | Create | `ImageGenRenderer`: cache → generate → gate → regen → fallback; PNG→PDF wrap |
| `render/strategies.py` | Modify | `character_identity` field on `RenderContext`; register `image_gen` |
| `transform.py` | Modify | CLI choice; pass `character_identity` into `RenderContext` |
| `batch.py` | Modify | CLI choice |
| `render_battery.py` | Create | A/B battery CLI: pdf_classic vs image_gen scorecard |
| `tests/test_worksheet_design_spec.py` | Modify | Section grouping test |
| `tests/test_image_prompt_builder.py` | Create | Prompt content tests |
| `tests/test_image_providers.py` | Create | Chain resolution tests |
| `tests/test_page_gates.py` | Create | Gate policy tests |
| `tests/test_image_gen_renderer.py` | Create | Regen loop / fallback / cache tests |
| `tests/test_render_battery.py` | Create | Scorecard builder test |

---

### Task 0: Decision log + constraint updates (docs only)

**Files:**
- Modify: `.claude/worksheet-project-context.md` (Key Decisions Log table, ~line 931 after D25)
- Modify: `AGENTS.md` (~line 48)

- [ ] **Step 1: Append decision rows D26–D28**

Add to the end of the Key Decisions Log table in `.claude/worksheet-project-context.md`:

```markdown
| D26 | AI is allowed in the production path; reliability via provider fallback chains | Image rendering chain: gemini-3.1-flash-image-preview → gpt-image-2-2026-04-21 → (Seedream later) → deterministic pdf_classic. Supersedes D2's "no AI in critical path" for rendering and adaptation. Offline runs still work via deterministic fallbacks. | 2026-06-11 |
| D27 | RAG retrieval removed from the default worksheet path | Direct UFLI lesson input is already well-scoped; corpus + deterministic lesson-number lookup retained (hallucination check, enrichment). Embedding retrieval reserved for a future "describe an objective → find representative UFLI content" entry point. | 2026-06-11 |
| D28 | Audio companion frozen, not deleted | Pilot not ready (pilot_ready=False); orthogonal to the worksheet quality push. Code, data, and evals retained untouched. | 2026-06-11 |
```

- [ ] **Step 2: Replace the AGENTS.md constraint bullet**

Replace this line in `AGENTS.md`:

```markdown
- **No AI in critical path.** AI assist is always behind the `extract/adapter.py` interface and is optional.
```

with:

```markdown
- **AI in the production path, with provider redundancy.** The default render/adapt path may call AI APIs. Reliability comes from provider fallback chains (Gemini → OpenAI → future providers) ending in the deterministic `pdf_classic` renderer — not from removing AI. Offline runs still work via deterministic fallbacks. (Supersedes the old "No AI in critical path" rule; see decision D26.)
```

- [ ] **Step 3: Commit**

```bash
git add .claude/worksheet-project-context.md AGENTS.md
git commit -m "docs: record D26-D28 (AI in production path, RAG default-off, audio freeze)"
```

---

### Task 1: Section grouping on WorksheetDesignSpec + `image_gen` render mode

**Files:**
- Modify: `render/design_spec.py`
- Test: `tests/test_worksheet_design_spec.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_worksheet_design_spec.py`:

```python
def test_design_spec_preserves_section_grouping() -> None:
    from render.design_spec import compile_worksheet_design_spec

    theme = ThemeConfig(name="Geometry Dash Calm")
    profile = LearnerProfile(name="Ian", grade_level="1")

    spec = compile_worksheet_design_spec(_adapted(), theme, profile, render_mode="image_gen")

    assert spec.render_mode == "image_gen"
    assert len(spec.sections) == 1
    section = spec.sections[0]
    assert section.chunk_id == 1
    assert section.micro_goal == "Read vowel team words"
    assert section.instructions == ["Read each word.", "Circle the vowel team."]
    assert section.worked_example_instruction == "Try this first:"
    assert section.worked_example_content == "rain has ai"
    assert section.time_estimate == "About 3 minutes"
    assert [item.content for item in section.items] == ["rain", "play", "tree"]
    assert section.items[1].response_format == "fill_blank"
    assert section.items[1].answer == "ay"
    assert spec.self_assessment == []
    assert spec.break_prompt is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_worksheet_design_spec.py::test_design_spec_preserves_section_grouping -v`
Expected: FAIL — `"image_gen"` is not a valid `RenderMode` literal (ValidationError) or `sections` attribute missing.

- [ ] **Step 3: Implement the schema changes**

In `render/design_spec.py`:

1. Change line 17:

```python
RenderMode = Literal["pdf_classic", "hybrid_shell", "image_prompt", "image_gen"]
```

2. Add after `AnswerZoneSpec` (before `WorksheetDesignSpec`):

```python
class SectionItemSpec(BaseModel):
    """One practice item inside a worksheet section."""

    item_id: int = Field(description="Activity item identifier.")
    content: str = Field(description="Student-facing item text.")
    response_format: str = Field(description="Expected response format.")
    options: list[str] = Field(default_factory=list)
    answer: str | None = Field(default=None, description="Answer when known.")


class SectionSpec(BaseModel):
    """One activity section, preserving chunk grouping for renderers."""

    chunk_id: int = Field(description="Activity chunk identifier.")
    micro_goal: str = Field(description="Section header text.")
    instructions: list[str] = Field(default_factory=list)
    worked_example_instruction: str | None = None
    worked_example_content: str | None = None
    time_estimate: str | None = None
    response_format: str = Field(description="Dominant response format.")
    items: list[SectionItemSpec] = Field(default_factory=list)
```

3. Add three fields to `WorksheetDesignSpec` after `answer_zones`:

```python
    sections: list[SectionSpec] = Field(default_factory=list)
    self_assessment: list[str] = Field(default_factory=list)
    break_prompt: str | None = None
```

4. In `compile_worksheet_design_spec()`, add to the constructor call after `answer_zones=_answer_zones(adapted),`:

```python
        sections=_sections(adapted),
        self_assessment=list(adapted.self_assessment or []),
        break_prompt=adapted.break_prompt,
```

5. Add the helper after `_answer_zones`:

```python
def _sections(adapted: AdaptedActivityModel) -> list[SectionSpec]:
    sections: list[SectionSpec] = []
    for chunk in adapted.chunks:
        sections.append(
            SectionSpec(
                chunk_id=chunk.chunk_id,
                micro_goal=chunk.micro_goal,
                instructions=[step.text for step in chunk.instructions],
                worked_example_instruction=(
                    chunk.worked_example.instruction if chunk.worked_example else None
                ),
                worked_example_content=(
                    chunk.worked_example.content if chunk.worked_example else None
                ),
                time_estimate=chunk.time_estimate,
                response_format=chunk.response_format,
                items=[
                    SectionItemSpec(
                        item_id=item.item_id,
                        content=item.content,
                        response_format=item.response_format,
                        options=list(item.options or []),
                        answer=item.answer,
                    )
                    for item in chunk.items
                ],
            )
        )
    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_worksheet_design_spec.py -v`
Expected: all PASS (new test + existing three).

- [ ] **Step 5: Lint, typecheck, commit**

```bash
.venv/bin/ruff check render/design_spec.py tests/test_worksheet_design_spec.py
.venv/bin/mypy render/design_spec.py
git add render/design_spec.py tests/test_worksheet_design_spec.py
git commit -m "feat: add section grouping and image_gen mode to WorksheetDesignSpec"
```

---

### Task 2: Page prompt builder with ADHD damping block

**Files:**
- Create: `render/image_prompt_builder.py`
- Test: `tests/test_image_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_image_prompt_builder.py`:

```python
"""Tests for full-page image prompt assembly."""

from __future__ import annotations

from render.design_spec import (
    PageSpec,
    SectionItemSpec,
    SectionSpec,
    VisualBudget,
    WorksheetDesignSpec,
)


def _spec(**overrides: object) -> WorksheetDesignSpec:
    base: dict = {
        "render_mode": "image_gen",
        "source_hash": "src",
        "skill_model_hash": "skill",
        "learner_profile_hash": "prof",
        "theme_id": "roblox_obby",
        "theme_name": "Roblox Obby Quest",
        "learner_name": "Ian",
        "learner_grade_level": "1",
        "worksheet_title": "Word Work",
        "worksheet_number": 1,
        "worksheet_count": 2,
        "domain": "phonics",
        "specific_skill": "vowel teams ai ay",
        "page": PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        "visual_budget": VisualBudget(
            style="calm", intensity="low", max_decorative_elements=2, max_colors=4
        ),
        "required_text": ["Word Work", "rain", "play"],
        "sections": [
            SectionSpec(
                chunk_id=1,
                micro_goal="Build 3 new words",
                instructions=["Read the starting word.", "Write the new word."],
                worked_example_instruction="Watch how the letters change:",
                worked_example_content="rain -> main",
                time_estimate="About 2 minutes",
                response_format="write",
                items=[
                    SectionItemSpec(
                        item_id=1, content="rain", response_format="write", answer="main"
                    ),
                    SectionItemSpec(
                        item_id=2,
                        content="play",
                        response_format="circle",
                        options=["play", "tray", "plop"],
                    ),
                ],
            )
        ],
        "self_assessment": ["I can read ai words"],
        "break_prompt": "Stand up and stretch!",
    }
    base.update(overrides)
    return WorksheetDesignSpec(**base)


def test_prompt_includes_sections_items_and_exact_text_rules() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())

    assert "Word Work" in prompt
    assert 'Section 1 banner text: "Build 3 new words"' in prompt
    assert 'Numbered instruction 1: "Read the starting word."' in prompt
    assert '"rain -> main"' in prompt
    assert 'Item 1: "rain"' in prompt
    assert "play, tray, plop" in prompt
    assert "EXACTLY as written" in prompt
    assert "I can read ai words" in prompt
    assert "Stand up and stretch!" in prompt


def test_prompt_damping_block_uses_visual_budget_numbers() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())

    assert "at most 4 accent colors" in prompt
    assert "Exactly 2 small purely decorative accents" in prompt
    assert "calm and tidy" in prompt
    assert "never put patterns, gradients, or scene art behind text" in prompt


def test_prompt_zero_decorations_branch() -> None:
    from render.image_prompt_builder import build_page_prompt

    spec = _spec(
        visual_budget=VisualBudget(
            style="calm", intensity="medium", max_decorative_elements=0, max_colors=3
        )
    )
    prompt = build_page_prompt(spec)

    assert "No purely decorative elements" in prompt
    assert "at most 3 accent colors" in prompt


def test_prompt_includes_character_and_theme_blocks_when_provided() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(
        _spec(),
        character_block="a blocky boy avatar with rainbow spiky hair",
        scene_guidelines="Compose scenes like calm printable learning panels.",
        theme_environment="light blue walls and simple geometric platforms",
        theme_palette="bright avatar colors, pale backgrounds",
        art_style="roblox_2d_comic_avatar",
    )

    assert "rainbow spiky hair" in prompt
    assert "matching the attached reference image" in prompt
    assert "light blue walls" in prompt
    assert "roblox_2d_comic_avatar" in prompt


def test_prompt_omits_character_section_without_character_block() -> None:
    from render.image_prompt_builder import build_page_prompt

    prompt = build_page_prompt(_spec())

    assert "Learning Buddy" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_image_prompt_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'render.image_prompt_builder'`.

- [ ] **Step 3: Implement the prompt builder**

Create `render/image_prompt_builder.py`:

```python
"""Full-page worksheet image prompt assembly.

Everything in this module is model-agnostic: it builds prompt text only.
Provider-specific details (reference-image conditioning, sizes, API calls)
live in render/image_providers.py. ADHD constraints from VisualBudget are
expressed here as damping language ("start rich, damp to ADHD-safe"), not
as code-enforced prohibitions.
"""

from __future__ import annotations

from render.design_spec import SectionSpec, WorksheetDesignSpec

# Bump when prompt structure changes — part of the page cache key.
PROMPT_VERSION = "page_prompt_v1"

_FORMAT_AFFORDANCES: dict[str, str] = {
    "write": "a blank handwriting line wide enough for a child to print the answer",
    "fill_blank": "the text with a clearly visible blank plus a handwriting line below",
    "trace": "the word in light dotted outline letters ready to trace",
    "circle": (
        "the option words spread out with space around each so a child can circle them"
    ),
    "match": (
        "two columns: words on the left, small simple pictures on the right, "
        "with room to draw connecting lines"
    ),
    "read_aloud": "the text inside a soft reading box with a small read-aloud icon",
    "sound_box": "one empty square box per sound (Elkonin boxes) under the word",
    "verbal": "a small speech icon next to the prompt",
}


def build_page_prompt(
    spec: WorksheetDesignSpec,
    *,
    character_block: str = "",
    scene_guidelines: str = "",
    theme_environment: str = "",
    theme_palette: str = "",
    art_style: str = "",
) -> str:
    """Build the full-page generation prompt from the design spec."""

    parts: list[str] = [
        (
            "Create ONE complete, print-ready children's literacy worksheet page "
            "as a single image."
        ),
        (
            "Portrait orientation, US Letter proportions (8.5 x 11), "
            "plain white page background."
        ),
        f'Worksheet title banner text: "{spec.worksheet_title}"',
        f"Theme: {spec.theme_name}. Skill focus: {spec.specific_skill} ({spec.domain}).",
        f"This is worksheet {spec.worksheet_number} of {spec.worksheet_count} for the lesson.",
        "## Visual style",
    ]
    if art_style:
        parts.append(f"Art style: {art_style}.")
    if theme_environment:
        parts.append(f"Environment styling for headers and accents: {theme_environment}")
    if theme_palette:
        parts.append(f"Palette guidance: {theme_palette}")
    parts.append(
        "Design the page like a polished, cohesive game-UI worksheet: a themed "
        "title banner, one numbered banner per activity section, and a small "
        "progress strip. Section chrome supports the learning content and never "
        "competes with it."
    )

    if character_block:
        parts.append("## Learning Buddy")
        parts.append(
            "Include the Learning Buddy exactly once, matching the attached "
            f"reference image: {character_block}"
        )
        if scene_guidelines:
            parts.append(scene_guidelines)

    parts.append("## Activity sections (render in this order)")
    for section in spec.sections:
        parts.append(_section_text(section))

    if spec.self_assessment:
        checks = "; ".join(spec.self_assessment)
        parts.append(
            "Final section: a short 'How did I do?' checklist with one empty "
            f"checkbox per line, exact text: {checks}"
        )
    if spec.break_prompt:
        parts.append(
            "After the last activity, a small calm 'Take a Break!' box that "
            f'says: "{spec.break_prompt}"'
        )

    parts.append("## Exact text rules")
    parts.append(
        "Render every quoted string above EXACTLY as written: same spelling, "
        "same words, same punctuation. Do not add, remove, rewrite, or decorate "
        "any instructional text. All text must be dark, legible, high contrast, "
        "and inside safe page margins."
    )

    parts.append("## Calm-focus rules (required)")
    parts.append(_damping_block(spec))

    return "\n\n".join(parts)


def _section_text(section: SectionSpec) -> str:
    lines: list[str] = [f'Section {section.chunk_id} banner text: "{section.micro_goal}"']
    if section.time_estimate:
        lines.append(f'Small time cue next to the banner: "{section.time_estimate}"')
    for number, instruction in enumerate(section.instructions, start=1):
        lines.append(f'Numbered instruction {number}: "{instruction}"')
    if section.worked_example_content:
        intro = section.worked_example_instruction or "Watch how I do the first one:"
        lines.append(
            f'Worked example in a soft tinted box: "{intro}" then '
            f'"{section.worked_example_content}"'
        )
    for item in section.items:
        affordance = _FORMAT_AFFORDANCES.get(
            item.response_format, "clear space for the child's answer"
        )
        item_line = f'Item {item.item_id}: "{item.content}" with {affordance}'
        if item.options and item.response_format in {"circle", "fill_blank", "match"}:
            item_line += f" (options, exact text: {', '.join(item.options)})"
        lines.append(item_line)
    return "\n".join(lines)


def _damping_block(spec: WorksheetDesignSpec) -> str:
    budget = spec.visual_budget
    if budget.max_decorative_elements > 0:
        decoration_rule = (
            f"Exactly {budget.max_decorative_elements} small purely decorative "
            "accents on the whole page, placed only in the header or footer "
            "corners — never between activities."
        )
    else:
        decoration_rule = (
            "No purely decorative elements; only the section chrome described above."
        )

    rules = [
        (
            "Plain white or near-white behind ALL instructional text and ALL answer "
            "areas; never put patterns, gradients, or scene art behind text or "
            "writing lines."
        ),
        (
            f"Use at most {budget.max_colors} accent colors (plus black text on "
            "white) and keep them consistent: one color for section banners, one "
            "for example boxes, one for rewards."
        ),
        decoration_rule,
        "One clearly boxed activity per section with generous white space between sections.",
        (
            "The Learning Buddy appears at most once and stays visually subordinate "
            "to the activities."
        ),
        (
            "No flashing effects, no crowding, no dense text blocks, no score "
            "displays or leaderboards."
        ),
    ]
    if budget.intensity == "low":
        rules.append(
            "Overall mood: calm and tidy. Saturate the banners gently; keep large "
            "areas white."
        )
    elif budget.intensity == "medium":
        rules.append(
            "Overall mood: lively but tidy; banners may be bolder, backgrounds "
            "stay quiet."
        )
    return "\n".join(f"- {rule}" for rule in rules)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_image_prompt_builder.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
.venv/bin/ruff check render/image_prompt_builder.py tests/test_image_prompt_builder.py
.venv/bin/mypy render/image_prompt_builder.py
git add render/image_prompt_builder.py tests/test_image_prompt_builder.py
git commit -m "feat: full-page image prompt builder with ADHD damping block"
```

---

### Task 3: Image provider adapters + fallback chain

**Files:**
- Create: `render/image_providers.py`
- Test: `tests/test_image_providers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_image_providers.py`:

```python
"""Tests for image provider chain resolution (offline; no API calls)."""

from __future__ import annotations

import pytest


def test_chain_default_order_with_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)

    chain = resolve_provider_chain()

    assert [provider.provider_id for provider in chain] == ["gemini", "openai"]


def test_chain_skips_unavailable_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)

    chain = resolve_provider_chain()

    assert [provider.provider_id for provider in chain] == ["openai"]


def test_chain_respects_env_order_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.setenv("WORKSHEET_IMAGE_PROVIDERS", "openai,gemini")

    chain = resolve_provider_chain()

    assert [provider.provider_id for provider in chain] == ["openai", "gemini"]


def test_chain_empty_without_any_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)

    assert resolve_provider_chain() == []


def test_generate_returns_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import GeminiImageProvider, OpenAIImageProvider

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert GeminiImageProvider().generate("prompt", None) is None
    assert OpenAIImageProvider().generate("prompt", None) is None


def test_openai_model_id_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import OpenAIImageProvider

    monkeypatch.setenv("WORKSHEET_OPENAI_IMAGE_MODEL", "gpt-image-3-future")

    assert OpenAIImageProvider().model_id == "gpt-image-3-future"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_image_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'render.image_providers'`.

- [ ] **Step 3: Implement the providers**

Create `render/image_providers.py`:

```python
"""Image generation provider adapters with a configurable fallback chain.

Adding a provider (e.g., Seedream via fal.ai/Replicate/ARK) is one adapter
class plus one registry entry in resolve_provider_chain(). Everything
upstream (prompt) and downstream (gates, PDF wrap) is provider-agnostic.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)

GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2-2026-04-21"
DEFAULT_PROVIDER_ORDER = "gemini,openai"


class ImageProvider(Protocol):
    """A single image-generation backend."""

    provider_id: str
    model_id: str

    def available(self) -> bool:
        """Whether this provider has credentials configured."""

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        """Generate one page image. Returns PNG bytes or None on failure."""


class GeminiImageProvider:
    """Gemini image generation (same pattern as render/asset_gen._generate_scene)."""

    provider_id = "gemini"

    def __init__(self) -> None:
        self.model_id = os.environ.get("WORKSHEET_GEMINI_IMAGE_MODEL", GEMINI_IMAGE_MODEL)

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            contents: list[types.Part] = [types.Part(text=prompt)]
            if reference_png:
                contents.append(
                    types.Part(
                        inline_data=types.Blob(mime_type="image/png", data=reference_png),
                    ),
                )
            response = client.models.generate_content(
                model=self.model_id,
                contents=contents,  # type: ignore[arg-type]
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
            for part in response.candidates[0].content.parts:  # type: ignore[index,union-attr]
                if part.inline_data and part.inline_data.data:
                    return bytes(part.inline_data.data)
            logger.warning("Gemini image response contained no image part")
            return None
        except Exception as exc:
            logger.warning("Gemini image generation failed: %s", exc)
            return None


class OpenAIImageProvider:
    """OpenAI gpt-image generation with reference conditioning via images.edit.

    Note: gpt-image models return b64_json by default and reject the
    response_format param (see gotcha G8 in the project context doc).
    """

    provider_id = "openai"

    def __init__(self) -> None:
        self.model_id = os.environ.get(
            "WORKSHEET_OPENAI_IMAGE_MODEL", DEFAULT_OPENAI_IMAGE_MODEL
        )

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            if reference_png:
                result = client.images.edit(
                    model=self.model_id,
                    image=[("reference.png", io.BytesIO(reference_png), "image/png")],
                    prompt=prompt,
                    size="1024x1536",
                )
            else:
                result = client.images.generate(
                    model=self.model_id,
                    prompt=prompt,
                    size="1024x1536",
                )
            b64 = result.data[0].b64_json if result.data else None
            if not b64:
                logger.warning("OpenAI image response contained no b64_json payload")
                return None
            return base64.b64decode(b64)
        except Exception as exc:
            logger.warning("OpenAI image generation failed: %s", exc)
            return None


def resolve_provider_chain() -> list[ImageProvider]:
    """Resolve the configured provider fallback chain, available providers only.

    Order comes from WORKSHEET_IMAGE_PROVIDERS (comma-separated), default
    "gemini,openai". Unknown names are ignored.
    """
    order = os.environ.get("WORKSHEET_IMAGE_PROVIDERS", DEFAULT_PROVIDER_ORDER)
    registry: dict[str, ImageProvider] = {
        "gemini": GeminiImageProvider(),
        "openai": OpenAIImageProvider(),
    }
    chain: list[ImageProvider] = []
    for name in order.split(","):
        provider = registry.get(name.strip().lower())
        if provider is not None and provider.available():
            chain.append(provider)
    return chain
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_image_providers.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
.venv/bin/ruff check render/image_providers.py tests/test_image_providers.py
.venv/bin/mypy render/image_providers.py
git add render/image_providers.py tests/test_image_providers.py
git commit -m "feat: image provider adapters with configurable fallback chain"
```

---

### Task 4: Page gates (text readback + character consistency)

**Files:**
- Create: `render/page_gates.py`
- Test: `tests/test_page_gates.py`

Gate policy (locked): a page ships only if the text gate ran and passed AND (no reference image was provided OR the character judge ran and approved). Unavailable judges fail closed — an unvalidated full-text page never reaches a child.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_page_gates.py`:

```python
"""Tests for full-page gates (offline; judges stubbed)."""

from __future__ import annotations

import pytest

from companion.character_judge import CharacterJudgeResult


def _text_report(**overrides: object):
    from render.page_gates import TextGateReport

    base: dict = {
        "available": True,
        "passed": True,
        "missing_text": [],
        "misspelled_text": [],
        "judge": "gemini",
    }
    base.update(overrides)
    return TextGateReport(**base)


def test_coerce_text_report_passes_when_nothing_missing() -> None:
    from render.page_gates import _coerce_text_report

    report = _coerce_text_report({"missing": [], "misspelled": []}, judge="gemini")

    assert report.available is True
    assert report.passed is True
    assert report.judge == "gemini"


def test_coerce_text_report_fails_on_missing_or_misspelled() -> None:
    from render.page_gates import _coerce_text_report

    missing = _coerce_text_report({"missing": ["rain"], "misspelled": []}, judge="gemini")
    garbled = _coerce_text_report({"missing": [], "misspelled": ["pluy"]}, judge="gemini")

    assert missing.passed is False
    assert missing.missing_text == ["rain"]
    assert garbled.passed is False
    assert garbled.misspelled_text == ["pluy"]


def test_evaluate_page_passes_with_both_gates_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(
            available=True, approved=True, score=9
        ),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", ["criteria"])

    assert report.passed is True


def test_evaluate_page_fails_when_text_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(
        page_gates,
        "evaluate_page_text",
        lambda png, req: _text_report(passed=False, missing_text=["rain"]),
    )
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(
            available=True, approved=True, score=9
        ),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [])

    assert report.passed is False


def test_evaluate_page_fails_closed_when_text_gate_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(
        page_gates,
        "evaluate_page_text",
        lambda png, req: _text_report(available=False, passed=False),
    )
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(
            available=True, approved=True, score=9
        ),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [])

    assert report.passed is False


def test_evaluate_page_character_gate_vacuous_without_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())

    report = page_gates.evaluate_page(b"png", ["rain"], None, [])

    assert report.passed is True
    assert report.character.available is False


def test_evaluate_page_fails_when_character_judge_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import render.page_gates as page_gates

    monkeypatch.setattr(page_gates, "evaluate_page_text", lambda png, req: _text_report())
    monkeypatch.setattr(
        page_gates,
        "judge_character_consistency",
        lambda ref, gen, criteria: CharacterJudgeResult(
            available=True, approved=False, score=3, issues=["wrong hair"]
        ),
    )

    report = page_gates.evaluate_page(b"png", ["rain"], b"ref", [])

    assert report.passed is False
    assert report.character.issues == ["wrong hair"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_page_gates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'render.page_gates'`.

- [ ] **Step 3: Implement the gates**

Create `render/page_gates.py`:

```python
"""Full-page worksheet gates: exact-text readback + character consistency.

Policy: fail closed. A generated page ships only when the text gate ran and
passed, and — when a character reference exists — the character judge ran
and approved. When no reference image is provided the character gate is
vacuously satisfied (there is no buddy identity to verify).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from companion.character_judge import (
    CharacterJudgeResult,
    _extract_json,
    judge_character_consistency,
)

logger = logging.getLogger(__name__)

_TEXT_GATE_MODEL_GEMINI = "gemini-3-flash-preview"
_TEXT_GATE_MODEL_OPENAI = "gpt-5.4"


class TextGateReport(BaseModel):
    """Result of the exact-text readback gate."""

    available: bool = False
    passed: bool = False
    missing_text: list[str] = Field(default_factory=list)
    misspelled_text: list[str] = Field(default_factory=list)
    judge: str | None = None


class PageGateReport(BaseModel):
    """Combined verdict for one generated page attempt."""

    passed: bool
    text: TextGateReport
    character: CharacterJudgeResult
    provider_id: str = ""
    attempt: int = 0


def evaluate_page(
    page_png: bytes,
    required_text: list[str],
    reference_png: bytes | None,
    character_criteria: list[str],
) -> PageGateReport:
    """Run both gates against a generated page image."""
    text_report = evaluate_page_text(page_png, required_text)

    if reference_png:
        character_report = judge_character_consistency(
            reference_png, page_png, character_criteria
        )
        character_ok = character_report.available and character_report.approved
    else:
        character_report = CharacterJudgeResult(
            available=False,
            approved=False,
            issues=["no reference image; character gate skipped"],
        )
        character_ok = True

    passed = text_report.available and text_report.passed and character_ok
    return PageGateReport(passed=passed, text=text_report, character=character_report)


def evaluate_page_text(page_png: bytes, required_text: list[str]) -> TextGateReport:
    """Vision readback: verify every required string appears, spelled exactly."""
    report = _text_gate_with_gemini(page_png, required_text)
    if report is not None:
        return report
    report = _text_gate_with_openai(page_png, required_text)
    if report is not None:
        return report
    return TextGateReport(available=False, passed=False)


def _build_text_gate_prompt(required_text: list[str]) -> str:
    checklist = "\n".join(f"- {text}" for text in required_text)
    return (
        "You are checking a generated children's worksheet image for text "
        "fidelity.\n"
        "For each required string below, verify it appears in the image, spelled "
        "EXACTLY as written (case-insensitive; ignore minor punctuation spacing).\n\n"
        f"Required strings:\n{checklist}\n\n"
        "Also flag any visible word on the page that is misspelled or garbled, "
        "even if it is not in the list.\n\n"
        "Respond with ONLY JSON (no markdown fences):\n"
        '{"missing": ["required strings not found"], '
        '"misspelled": ["garbled or misspelled visible words"]}'
    )


def _coerce_text_report(raw: Mapping[str, Any], judge: str) -> TextGateReport:
    raw_missing = raw.get("missing", [])
    raw_misspelled = raw.get("misspelled", [])
    missing = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
    misspelled = (
        [str(item) for item in raw_misspelled] if isinstance(raw_misspelled, list) else []
    )
    return TextGateReport(
        available=True,
        passed=not missing and not misspelled,
        missing_text=missing,
        misspelled_text=misspelled,
        judge=judge,
    )


def _text_gate_with_gemini(
    page_png: bytes, required_text: list[str]
) -> TextGateReport | None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_TEXT_GATE_MODEL_GEMINI,
            contents=[
                types.Part(text=_build_text_gate_prompt(required_text)),
                types.Part(
                    inline_data=types.Blob(mime_type="image/png", data=page_png),
                ),
            ],  # type: ignore[arg-type]
        )
        raw = json.loads(_extract_json(response.text or ""))
        if not isinstance(raw, dict):
            raise ValueError("text gate response must be a JSON object")
        return _coerce_text_report(raw, judge="gemini")
    except Exception as exc:
        logger.warning("Gemini text gate failed: %s", exc)
        return None


def _text_gate_with_openai(
    page_png: bytes, required_text: list[str]
) -> TextGateReport | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import base64

        import openai

        client = openai.OpenAI(api_key=api_key)
        page_b64 = base64.b64encode(page_png).decode("utf-8")
        response = client.chat.completions.create(
            model=_TEXT_GATE_MODEL_OPENAI,
            max_completion_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_text_gate_prompt(required_text)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{page_b64}"},
                        },
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        raw = json.loads(_extract_json(text))
        if not isinstance(raw, dict):
            raise ValueError("text gate response must be a JSON object")
        return _coerce_text_report(raw, judge="openai")
    except Exception as exc:
        logger.warning("OpenAI text gate failed: %s", exc)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_page_gates.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
.venv/bin/ruff check render/page_gates.py tests/test_page_gates.py
.venv/bin/mypy render/page_gates.py
git add render/page_gates.py tests/test_page_gates.py
git commit -m "feat: page gates for text fidelity and character consistency"
```

---

### Task 5: ImageGenRenderer with regen loop, cache, and PDF wrap

**Files:**
- Create: `render/image_gen.py`
- Modify: `render/strategies.py` (RenderContext field + registration)
- Test: `tests/test_image_gen_renderer.py`

Import direction (avoid a cycle): `render/image_gen.py` imports `RenderContext`/`RenderResult`/`PdfClassicRenderer` from `render.strategies` at module level; `render/strategies.py` imports `ImageGenRenderer` lazily inside `resolve_render_strategy()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_image_gen_renderer.py`:

```python
"""Tests for the full-page image generation renderer (offline; stubs only)."""

from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest

from companion.character_judge import CharacterJudgeResult
from render.design_spec import (
    PageSpec,
    SectionItemSpec,
    SectionSpec,
    VisualBudget,
    WorksheetDesignSpec,
)


def _png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (64, 96), "#FFFFFF")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _spec() -> WorksheetDesignSpec:
    return WorksheetDesignSpec(
        render_mode="image_gen",
        source_hash="src",
        skill_model_hash="skill",
        learner_profile_hash="prof",
        theme_id="roblox_obby",
        theme_name="Roblox Obby Quest",
        learner_name="Ian",
        learner_grade_level="1",
        worksheet_title="Word Work",
        worksheet_number=1,
        worksheet_count=1,
        domain="phonics",
        specific_skill="vowel teams",
        page=PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        visual_budget=VisualBudget(
            style="calm", intensity="low", max_decorative_elements=2, max_colors=4
        ),
        required_text=["Word Work", "rain"],
        sections=[
            SectionSpec(
                chunk_id=1,
                micro_goal="Read the words",
                instructions=["Read each word."],
                response_format="write",
                items=[
                    SectionItemSpec(item_id=1, content="rain", response_format="write")
                ],
            )
        ],
    )


class _StubProvider:
    def __init__(self, provider_id: str, results: list[bytes | None]) -> None:
        self.provider_id = provider_id
        self.model_id = f"{provider_id}-model"
        self._results = list(results)
        self.calls = 0

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        self.calls += 1
        if not self._results:
            return None
        return self._results.pop(0)


def _gate_report(passed: bool):
    from render.page_gates import PageGateReport, TextGateReport

    return PageGateReport(
        passed=passed,
        text=TextGateReport(available=True, passed=passed),
        character=CharacterJudgeResult(available=True, approved=passed, score=8),
    )


def _context(tmp_path: Path):
    from render.strategies import RenderContext
    from theme.schema import ThemeConfig

    return RenderContext(
        design_spec=_spec(),
        adapted=object(),
        theme=ThemeConfig(name="Roblox Obby Quest"),
        output_path=tmp_path / "worksheet.pdf",
        artifacts_dir=tmp_path / "artifacts",
    )


def _renderer(providers, cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    import render.image_gen as image_gen

    monkeypatch.setattr(image_gen, "_CACHE_DIR", cache_dir)
    return image_gen.ImageGenRenderer(providers=providers)


def test_accepts_first_gate_passing_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes()])
    monkeypatch.setattr(
        image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True)
    )
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "image_gen"
    assert result.pdf_path is not None and Path(result.pdf_path).exists()
    doc = fitz.open(result.pdf_path)
    assert doc.page_count == 1
    assert abs(doc[0].rect.width - 612) < 2
    assert "rain" in doc[0].get_text()  # invisible text layer is searchable
    doc.close()


def test_regenerates_after_failed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes(), _png_bytes()])
    verdicts = iter([_gate_report(False), _gate_report(True)])
    monkeypatch.setattr(
        image_gen, "evaluate_page", lambda *args, **kwargs: next(verdicts)
    )
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "image_gen"
    assert provider.calls == 2


def test_falls_through_to_next_provider_on_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen

    broken = _StubProvider("broken", [None])
    working = _StubProvider("working", [_png_bytes()])
    monkeypatch.setattr(
        image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True)
    )
    renderer = _renderer([broken, working], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "image_gen"
    assert broken.calls == 1
    assert working.calls == 1


def test_falls_back_to_pdf_classic_when_all_attempts_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen
    from render.strategies import RenderResult

    provider = _StubProvider("stub", [_png_bytes()] * 3)
    monkeypatch.setattr(
        image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(False)
    )

    class _StubClassic:
        renderer_id = "pdf_classic"
        produces_pdf = True
        experimental = False

        def render(self, context):
            return RenderResult(
                renderer_id="pdf_classic",
                pdf_path=str(context.output_path),
                artifact_paths=[str(context.output_path)],
                produces_pdf=True,
                experimental=False,
            )

    monkeypatch.setattr(image_gen, "PdfClassicRenderer", _StubClassic)
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "pdf_classic"
    assert provider.calls == 3  # quality-first budget: 3 attempts per provider
    fallback_marker = tmp_path / "artifacts" / "image_gen_fallback.json"
    assert fallback_marker.exists()


def test_cache_hit_skips_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes()])
    monkeypatch.setattr(
        image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True)
    )
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    renderer.render(_context(tmp_path))
    assert provider.calls == 1

    renderer.render(_context(tmp_path))
    assert provider.calls == 1  # second render served from cache


def test_resolve_render_strategy_knows_image_gen() -> None:
    from render.strategies import resolve_render_strategy

    strategy = resolve_render_strategy("image_gen")

    assert strategy.renderer_id == "image_gen"
    assert strategy.produces_pdf is True
    assert strategy.experimental is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_image_gen_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'render.image_gen'`.

- [ ] **Step 3: Add `character_identity` to RenderContext and register the mode**

In `render/strategies.py`:

1. Add a field to `RenderContext` (after `asset_manifest`, before `extra_artifacts`):

```python
    character_identity: object | None = None
```

2. Replace `resolve_render_strategy` with:

```python
def resolve_render_strategy(mode: str | None) -> RenderStrategy:
    """Resolve a render strategy by mode."""

    selected = mode or default_render_mode()
    if selected == "image_gen":
        from render.image_gen import ImageGenRenderer

        return ImageGenRenderer()
    strategies: dict[str, RenderStrategy] = {
        "hybrid_shell": HybridShellRenderer(),
        "image_prompt": ImagePromptRenderer(),
        "pdf_classic": PdfClassicRenderer(),
    }
    strategy = strategies.get(selected)
    if strategy is None:
        known = ", ".join(sorted([*strategies, "image_gen"]))
        raise ValueError(f"Unknown render mode '{selected}'. Expected one of: {known}")
    return strategy
```

- [ ] **Step 4: Implement the renderer**

Create `render/image_gen.py`:

```python
"""Full-page image-generation renderer: generate, gate, regenerate, fall back.

Flow per worksheet page:
1. Cache check (content hash of design spec + identity version + prompt version).
2. For each provider in the chain, up to MAX_ATTEMPTS_PER_PROVIDER attempts:
   generate -> run page gates -> accept on pass, regenerate on fail.
3. Accepted PNG is cached and wrapped as a US Letter PDF with an invisible
   searchable text layer (satisfies validate/print_checks.py vector-text gate).
4. If everything fails, delegate to the deterministic PdfClassicRenderer and
   write an image_gen_fallback.json marker into the artifacts directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import fitz  # PyMuPDF

from render.design_spec import WorksheetDesignSpec
from render.image_prompt_builder import PROMPT_VERSION, build_page_prompt
from render.image_providers import ImageProvider, resolve_provider_chain
from render.page_gates import evaluate_page
from render.strategies import PdfClassicRenderer, RenderContext, RenderResult

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "cache"

# Owner decision 2026-06-11: quality-first regen budget.
MAX_ATTEMPTS_PER_PROVIDER = 3

PAGE_WIDTH_PT = 612
PAGE_HEIGHT_PT = 792


class ImageGenRenderer:
    """Renders the whole worksheet page with an image model, gated and cached."""

    renderer_id = "image_gen"
    produces_pdf = True
    experimental = True

    def __init__(
        self,
        providers: list[ImageProvider] | None = None,
        max_attempts_per_provider: int = MAX_ATTEMPTS_PER_PROVIDER,
    ) -> None:
        self._providers = providers
        self._max_attempts = max_attempts_per_provider

    def render(self, context: RenderContext) -> RenderResult:
        from companion.character_identity import CharacterIdentity
        from render.asset_gen import _reference_bytes_from_identity, _scene_judge_criteria

        if os.environ.get("WORKSHEET_SKIP_ASSET_GEN"):
            return self._fallback(context, reason="WORKSHEET_SKIP_ASSET_GEN set")

        spec = context.design_spec
        identity = (
            context.character_identity
            if isinstance(context.character_identity, CharacterIdentity)
            else None
        )
        ref_bytes = _reference_bytes_from_identity(identity) if identity else None
        character_spec = getattr(context.theme, "character_spec", None)

        prompt = build_page_prompt(
            spec,
            character_block=identity.character_block if identity else "",
            scene_guidelines=identity.scene_guidelines if identity else "",
            theme_environment=(
                character_spec.scene_environment if character_spec else ""
            ),
            theme_palette=character_spec.color_palette if character_spec else "",
            art_style=character_spec.art_style if character_spec else "",
        )
        criteria = _scene_judge_criteria(identity, character_spec)

        context.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (context.artifacts_dir / "page_prompt.md").write_text(prompt)

        cache_key = self._cache_key(spec, identity)
        cache_dir = _CACHE_DIR / f"page_{cache_key}"
        cached_png = cache_dir / "page.png"
        if cached_png.exists():
            logger.info("  Page cache hit: %s", cached_png)
            _write_page_pdf(
                cached_png.read_bytes(), context.output_path, spec.required_text
            )
            return self._success_result(context, cached_png)

        providers = (
            self._providers if self._providers is not None else resolve_provider_chain()
        )
        if not providers:
            return self._fallback(context, reason="no image providers available")

        for provider in providers:
            for attempt in range(1, self._max_attempts + 1):
                logger.info(
                    "  Page gen: provider=%s model=%s attempt=%d/%d",
                    provider.provider_id,
                    provider.model_id,
                    attempt,
                    self._max_attempts,
                )
                png = provider.generate(prompt, ref_bytes)
                if png is None:
                    logger.warning(
                        "  Provider %s failed to return an image; trying next provider",
                        provider.provider_id,
                    )
                    break

                report = evaluate_page(png, spec.required_text, ref_bytes, criteria)
                report.provider_id = provider.provider_id
                report.attempt = attempt
                self._write_attempt_diagnostics(
                    context.artifacts_dir, provider.provider_id, attempt, png, report
                )

                if report.passed:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cached_png.write_bytes(png)
                    (cache_dir / "gate_report.json").write_text(
                        report.model_dump_json(indent=2)
                    )
                    _write_page_pdf(png, context.output_path, spec.required_text)
                    return self._success_result(context, cached_png)

                logger.warning(
                    "  Page rejected (provider=%s attempt=%d): missing=%s "
                    "misspelled=%s character_issues=%s",
                    provider.provider_id,
                    attempt,
                    report.text.missing_text,
                    report.text.misspelled_text,
                    report.character.issues,
                )

        return self._fallback(
            context, reason="all providers exhausted without a gate-passing page"
        )

    def _cache_key(self, spec: WorksheetDesignSpec, identity: object | None) -> str:
        identity_version = (
            getattr(identity, "identity_version", "no_identity")
            if identity
            else "no_identity"
        )
        payload = f"{spec.model_dump_json()}|{identity_version}|{PROMPT_VERSION}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _success_result(self, context: RenderContext, cached_png: Path) -> RenderResult:
        return RenderResult(
            renderer_id=self.renderer_id,
            pdf_path=str(context.output_path),
            artifact_paths=[
                str(context.output_path),
                str(cached_png),
                str(context.artifacts_dir / "page_prompt.md"),
            ],
            produces_pdf=self.produces_pdf,
            experimental=self.experimental,
        )

    def _write_attempt_diagnostics(
        self,
        artifacts_dir: Path,
        provider_id: str,
        attempt: int,
        png: bytes,
        report: object,
    ) -> None:
        stem = f"page_attempt_{provider_id}_{attempt}"
        (artifacts_dir / f"{stem}.png").write_bytes(png)
        report_json = report.model_dump_json(indent=2)  # type: ignore[attr-defined]
        (artifacts_dir / f"{stem}_gates.json").write_text(report_json)

    def _fallback(self, context: RenderContext, *, reason: str) -> RenderResult:
        logger.warning("  ImageGenRenderer falling back to pdf_classic: %s", reason)
        context.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (context.artifacts_dir / "image_gen_fallback.json").write_text(
            json.dumps({"fallback": True, "reason": reason}, indent=2)
        )
        return PdfClassicRenderer().render(context)


def _write_page_pdf(
    png_bytes: bytes, output_path: Path, required_text: list[str]
) -> None:
    """Wrap a page PNG as a US Letter PDF with an invisible searchable text layer."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH_PT, height=PAGE_HEIGHT_PT)
    page.insert_image(
        fitz.Rect(0, 0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT),
        stream=png_bytes,
        keep_proportion=True,
    )
    # render_mode=3 = invisible text. Keeps the PDF searchable and satisfies
    # the vector-text check in validate/print_checks.py for raster pages.
    page.insert_textbox(
        fitz.Rect(0, 0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT),
        " ".join(required_text),
        fontsize=2,
        fontname="helv",
        render_mode=3,
    )
    doc.save(str(output_path))
    doc.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_image_gen_renderer.py tests/test_render_strategies.py -v`
Expected: all PASS (new tests + existing strategy tests unaffected).

- [ ] **Step 6: Lint, typecheck, commit**

```bash
.venv/bin/ruff check render/image_gen.py render/strategies.py tests/test_image_gen_renderer.py
.venv/bin/mypy render/image_gen.py render/strategies.py
git add render/image_gen.py render/strategies.py tests/test_image_gen_renderer.py
git commit -m "feat: ImageGenRenderer with regen gates, provider fallback, and cached pages"
```

---

### Task 6: Pipeline wiring (transform.py, batch.py)

**Files:**
- Modify: `transform.py` (CLI choice ~line 84; multi-worksheet RenderContext ~line 639)
- Modify: `batch.py` (CLI choice — locate with grep)

- [ ] **Step 1: Add `image_gen` to the transform CLI**

In `transform.py`, change the `--render-mode` option:

```python
@click.option(
    "--render-mode",
    default="pdf_classic",
    type=click.Choice(["pdf_classic", "hybrid_shell", "image_prompt", "image_gen"]),
    help="Renderer mode. Defaults to production-safe pdf_classic.",
)
```

- [ ] **Step 2: Pass character identity into the multi-worksheet RenderContext**

In `transform.py` `_run_multi_worksheet_pipeline`, the per-worksheet loop already resolves `identity` (the `resolve_character_identity(...)` call inside the asset-generation `try` block, ~line 594). Move that resolution OUT of the `try` block so it always runs, directly above the `try`:

```python
        identity = resolve_character_identity(
            profile,
            theme_id,
            character_spec=char_spec,
        )
        asset_manifest = None
        try:
            scenes = plan_scenes(adapted, character_spec=char_spec)
```

(delete the now-duplicate `identity = resolve_character_identity(...)` inside the `try`), then add the field to the `RenderContext` construction (~line 639):

```python
        render_result = strategy.render(
            RenderContext(
                design_spec=design_spec,
                adapted=adapted,
                theme=theme,
                output_path=Path(pdf_path),
                artifacts_dir=render_artifacts_dir,
                asset_manifest=asset_manifest,
                character_identity=identity,
            )
        )
```

The single-worksheet pipeline needs no change (`character_identity` defaults to `None`; the renderer degrades to a buddy-less page).

- [ ] **Step 3: Add `image_gen` to the batch CLI**

Run: `grep -n "render-mode\|render_mode" batch.py | head -20` to find the `click.Choice` list, then apply the same change as Step 1:

```python
    type=click.Choice(["pdf_classic", "hybrid_shell", "image_prompt", "image_gen"]),
```

- [ ] **Step 4: Run the full offline suite**

Run: `.venv/bin/pytest tests/ -v --ignore=tests/test_e2e.py`
Expected: all PASS (432 baseline + new tests). Then:

```bash
make lint
make typecheck
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add transform.py batch.py
git commit -m "feat: wire image_gen render mode through transform and batch CLIs"
```

---

### Task 7: Render battery (pdf_classic vs image_gen scorecard)

**Files:**
- Create: `render_battery.py`
- Test: `tests/test_render_battery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_battery.py`:

```python
"""Tests for the render battery scorecard builder (no pipeline runs)."""

from __future__ import annotations


def test_scorecard_table_includes_rows_and_verdicts() -> None:
    from render_battery import BatteryRow, build_scorecard

    rows = [
        BatteryRow(
            input_name="IMG_0004.JPG",
            classic_all_pass=True,
            image_all_pass=True,
            image_fell_back=False,
            image_pdf_paths=["out/b/worksheet_1.pdf"],
            classic_pdf_paths=["out/a/worksheet_1.pdf"],
        ),
        BatteryRow(
            input_name="IMG_0007.JPG",
            classic_all_pass=True,
            image_all_pass=False,
            image_fell_back=True,
            image_pdf_paths=[],
            classic_pdf_paths=["out/a/worksheet_2.pdf"],
        ),
    ]

    scorecard = build_scorecard(rows)

    assert "IMG_0004.JPG" in scorecard
    assert "IMG_0007.JPG" in scorecard
    assert "| input | classic all-pass | image_gen all-pass | fell back |" in scorecard
    assert "image_gen fallbacks: 1/2" in scorecard
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_render_battery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'render_battery'`.

- [ ] **Step 3: Implement the battery CLI**

Create `render_battery.py`:

```python
"""A/B render battery: run inputs through pdf_classic and image_gen, score both.

Usage:
    python render_battery.py --input samples/input/IMG_0004.JPG \
        --profile profiles/ian.yaml --theme roblox_obby

Writes <output>/<timestamp>/scorecard.md plus per-variant pipeline outputs.
The owner reviews the side-by-side PDFs against the ChatGPT reference at
samples/output/ian-worksheet-geo-dash-1.png to make the promotion decision.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import click
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class BatteryRow(BaseModel):
    """One input's A/B outcome."""

    input_name: str
    classic_all_pass: bool
    image_all_pass: bool
    image_fell_back: bool
    classic_pdf_paths: list[str] = Field(default_factory=list)
    image_pdf_paths: list[str] = Field(default_factory=list)


def build_scorecard(rows: list[BatteryRow]) -> str:
    lines = [
        "# Render battery scorecard",
        "",
        "| input | classic all-pass | image_gen all-pass | fell back |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.input_name} | {row.classic_all_pass} | "
            f"{row.image_all_pass} | {row.image_fell_back} |"
        )
    fallbacks = sum(1 for row in rows if row.image_fell_back)
    lines.append("")
    lines.append(f"image_gen fallbacks: {fallbacks}/{len(rows)}")
    lines.append("")
    lines.append("## Review checklist (owner)")
    lines.append("- Compare each image_gen PDF against the classic PDF side by side.")
    lines.append(
        "- Compare against samples/output/ian-worksheet-geo-dash-1.png for richness."
    )
    lines.append("- Check Buddy likeness, text legibility, and calm-focus rules.")
    return "\n".join(lines)


def _run_variant(
    input_path: Path, profile: str, theme: str, out_dir: Path, render_mode: str
) -> tuple[bool, bool, list[str]]:
    """Run one pipeline variant. Returns (all_pass, fell_back, pdf_paths)."""
    from transform import run_pipeline_collect_artifacts

    artifacts_dir = out_dir / "artifacts"
    run = run_pipeline_collect_artifacts(
        input_path=str(input_path),
        profile_path=profile,
        theme_id=theme,
        output_dir=str(out_dir),
        artifacts_dir=str(artifacts_dir),
        index_results=False,
        render_mode=render_mode,
    )
    all_pass = bool(run.validation_results.get("all_validators_passed", False))
    fell_back = render_mode == "image_gen" and run.renderer_id != "image_gen"
    return all_pass, fell_back, list(run.pdf_paths)


@click.command()
@click.option(
    "--input",
    "input_paths",
    multiple=True,
    required=True,
    help="Worksheet photo path. Repeat for multiple inputs.",
)
@click.option("--profile", "profile_path", required=True)
@click.option("--theme", "theme_id", default="roblox_obby")
@click.option("--output", "output_dir", default="./samples/output/render_battery")
def battery(
    input_paths: tuple[str, ...], profile_path: str, theme_id: str, output_dir: str
) -> None:
    """Run each input through pdf_classic and image_gen; write a scorecard."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    root = Path(output_dir) / stamp
    rows: list[BatteryRow] = []

    for raw_path in input_paths:
        input_path = Path(raw_path)
        name = input_path.name
        logger.info("Battery input: %s", name)

        classic_pass, _, classic_pdfs = _run_variant(
            input_path, profile_path, theme_id, root / f"{input_path.stem}_classic",
            "pdf_classic",
        )
        image_pass, fell_back, image_pdfs = _run_variant(
            input_path, profile_path, theme_id, root / f"{input_path.stem}_image",
            "image_gen",
        )
        rows.append(
            BatteryRow(
                input_name=name,
                classic_all_pass=classic_pass,
                image_all_pass=image_pass,
                image_fell_back=fell_back,
                classic_pdf_paths=classic_pdfs,
                image_pdf_paths=image_pdfs,
            )
        )

    root.mkdir(parents=True, exist_ok=True)
    scorecard_path = root / "scorecard.md"
    scorecard_path.write_text(build_scorecard(rows))
    logger.info("Scorecard: %s", scorecard_path)


if __name__ == "__main__":
    battery()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_render_battery.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
.venv/bin/ruff check render_battery.py tests/test_render_battery.py
.venv/bin/mypy render_battery.py
git add render_battery.py tests/test_render_battery.py
git commit -m "feat: A/B render battery CLI with promotion scorecard"
```

---

### Task 8: Live smoke run + battery + handoff (manual; requires API keys)

**Files:**
- Modify: `.claude/worksheet-project-context.md` (session handoff entry)

- [ ] **Step 1: Single-lesson live smoke**

```bash
WORKSHEET_LLM_ADAPT=1 .venv/bin/python transform.py \
  --input samples/input/IMG_0004.JPG \
  --profile profiles/ian.yaml \
  --theme roblox_obby \
  --output ./samples/output/image_gen_smoke \
  --render-mode image_gen
```

Inspect `samples/output/image_gen_smoke/artifacts/`:
- `page_prompt.md` reads as a coherent, sectioned prompt.
- `page_attempt_*_gates.json` shows gate verdicts per attempt.
- Final PDFs open, look like cohesive themed pages, Buddy matches `assets/style_sheets/ian_roblox_buddy/`, all instructional text legible and correctly spelled.
- If `image_gen_fallback.json` appears, read the reason and the rejected attempt PNGs before tuning anything (systematic-debugging: find the failing gate first, then adjust prompt or budget).

- [ ] **Step 2: Run the battery on 3–5 inputs**

```bash
WORKSHEET_LLM_ADAPT=1 .venv/bin/python render_battery.py \
  --input samples/input/IMG_0004.JPG \
  --profile profiles/ian.yaml \
  --theme roblox_obby
```

Add `--input` flags for each additional sample in `samples/input/`. Review `scorecard.md` and the side-by-side PDFs against `samples/output/ian-worksheet-geo-dash-1.png`. The owner makes the promotion call; `pdf_classic` stays the default until then.

- [ ] **Step 3: Update the handoff context doc**

Add a dated entry to `.claude/worksheet-project-context.md` Current State covering: what shipped (Tasks 0–7), live smoke/battery results (attempt counts, fallback rate, gate failure reasons), the promotion decision status, and known debt (Ian-only scope; `_draw_ian_action_character` hardcoded fallback art; Seedream provider slot empty; letterboxing if provider aspect ratio ≠ 8.5:11).

- [ ] **Step 4: Final verification + commit**

```bash
make lint && make typecheck && make test
git add .claude/worksheet-project-context.md
git commit -m "docs: record image_gen smoke + battery results and promotion status"
```

---

## Follow-up plans (separate documents, after this ships)

1. **Planner simplification** — one frontier planning call with full source + corpus lesson text; judge once, advisory; delete the retry/takeover loop in `adapt/llm_orchestrator.py`; widen `ActivityPlan` so the model authors items; stop `_log_performance` writing to the global `logs/` file under pytest and archive the polluted log.
2. **Multi-theme rotation** — `--theme auto` resolves from `profile.preferences.favorite_themes` via deterministic rotation keyed by source hash; verify Buddy identity across themes with the existing character judge.

## Known risks

- **Provider SDK drift:** the exact `images.edit` reference-conditioning signature for `gpt-image-2-2026-04-21` should be verified against current OpenAI docs at execution time; the adapter isolates any correction to `OpenAIImageProvider.generate()`.
- **Aspect ratio:** providers return fixed ratios (e.g., 1024x1536 ≈ 2:3) vs Letter (~0.77); `keep_proportion=True` letterboxes with white margins, acceptable for print. Revisit if margins look unbalanced.
- **Gate cost:** each attempt costs one generation + up to two judge calls. Quality-first budget caps this at 3 attempts/provider; the cache makes reruns free.
- **Invisible-text overlap warning:** `print_checks._check_text_image_overlap` may emit a `text_image_overlap` warning (severity: warning, non-blocking) because the invisible layer sits over the page image. Accept the warning; do not weaken the check.
