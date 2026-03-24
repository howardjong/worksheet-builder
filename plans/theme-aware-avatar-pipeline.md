# Plan: Theme-Aware Avatar Creation & Consistency Pipeline

## Problem

The current avatar/character system produces worksheet characters that look generically "cartoon blocky" rather than authentically matching the child's chosen theme. For Ian's Roblox Obby theme, characters should look like actual Roblox characters (R15 rig proportions, flat cell-shading, 2D decal face, blocky geometry) but the pipeline uses a hardcoded `_CHARACTER_DESC` string that was written by hand without researching what Roblox characters actually look like.

### Root Causes

1. **Hardcoded character description** — `_CHARACTER_DESC` is duplicated in `companion/generate_overlays.py` and `render/asset_gen.py` as a static string that doesn't change per theme
2. **No theme visual research** — When a profile is created or theme is set, nothing researches the theme's authentic visual language
3. **Scene prompts are theme-agnostic** — `render/pose_planner.py` generates "A friendly cartoon character pointing at word signs" regardless of theme
4. **Judge doesn't evaluate theme fidelity** — The Gemini judge checks character consistency against the reference image but not whether the result looks like it belongs in the theme's universe
5. **Profile has no character style sheet** — `AvatarConfig` stores a filename and colors but no rich style description

## Architecture: "Research Once, Enforce Cheap"

### Phase 1: Avatar Creation (expensive, one-time per theme change)

```
Child picks theme "roblox_obby"
  |
  v
MCP Research (perplexity-ask / exa)
  "What do Roblox characters and obby environments look like?"
  |
  v
Theme Visual DNA (structured YAML)
  - art_style, body proportions, face style, environment, palette
  - stored in theme/themes/roblox_obby/character_spec.yaml
  |
  v
Gemini: Generate Character Style Sheet
  - Frozen "character block" prompt (replaces _CHARACTER_DESC)
  - 3-5 reference images (front, side, expressions, in-scene)
  - Scene/environment guidelines
  - stored on profile + assets/style_sheets/<profile>_<theme>/
  |
  v
CharacterStyleSheet persisted on LearnerProfile
```

### Phase 2: Worksheet Generation (cheap, per-image, no MCP)

```
render/asset_gen.py reads style_sheet from profile
  - Uses frozen character_block instead of hardcoded _CHARACTER_DESC
  - Passes reference images from style sheet pack
  |
render/pose_planner.py reads character_spec from theme
  - Scene prompts include theme environment elements
  - Poses match theme context (obby actions, not generic "pointing")
  |
Gemini judge evaluates with theme criteria
  - "Does this look like a Roblox character?"
  - "Are proportions blocky with flat cell-shading?"
  - No MCP calls, just criteria derived from style sheet
```

## Implementation

### Phase 1: Theme Character Spec Schema + Roblox Config

**Files:** `theme/schema.py`, `theme/themes/roblox_obby/config.yaml`

Add `CharacterSpec` model to `ThemeConfig`:

```python
class CharacterSpec(BaseModel):
    art_style: str = ""  # e.g., "roblox_3d_cartoon"
    style_description: str = ""  # detailed prompt-ready description
    body_description: str = ""  # proportions, shapes
    face_description: str = ""  # face rendering style
    scene_environment: str = ""  # environment elements for scenes
    scene_elements: list[str] = []  # specific props/objects
    color_palette: str = ""  # palette description
    reference_keywords: list[str] = []  # search anchors
    judge_criteria: list[str] = []  # theme-specific quality checks
```

Populate `roblox_obby/config.yaml` with researched Roblox visual DNA. Add minimal defaults for space/dinosaur/underwater.

### Phase 2: Character Style Sheet on Profile

**Files:** `companion/schema.py`, `profiles/ian.yaml`

Add `CharacterStyleSheet` to `AvatarConfig`:

```python
class CharacterStyleSheet(BaseModel):
    character_block: str = ""  # frozen prompt replacing _CHARACTER_DESC
    theme_id: str = ""  # which theme this was generated for
    reference_image_dir: str = ""  # path to reference pack
    scene_guidelines: str = ""  # how to compose scenes
    item_style_notes: str = ""  # how accessories should render in this style
    generated_at: str = ""  # ISO timestamp
```

### Phase 3: Character Research Module

**New file:** `companion/character_research.py`

The one-time expensive step that runs when:
- A new profile is created with a theme
- A profile's favorite theme changes
- Manually via CLI (`python -m companion.character_research --profile ian --theme roblox_obby`)

Flow:
1. Load theme's `CharacterSpec` (from config.yaml)
2. If `CharacterSpec` has no `style_description` or `reference_keywords`, call perplexity-ask/exa to research the theme's visual language
3. Compose a detailed `character_block` prompt from theme spec + child preferences (colors, visual_style)
4. Optionally generate 3-5 reference images via Gemini and save to `assets/style_sheets/<name>_<theme>/`
5. Return `CharacterStyleSheet` and persist to profile

The module should:
- Work without MCP/API keys (falls back to theme's static `style_description`)
- Cache results (only re-research if theme changes)
- Be invocable standalone or from profile creation

### Phase 4: Wire Style Sheet into Asset Generation

**Files:** `render/asset_gen.py`, `render/pose_planner.py`, `companion/generate_overlays.py`

**`render/asset_gen.py`:**
- Remove hardcoded `_CHARACTER_DESC`
- `generate_worksheet_assets()` accepts optional `style_sheet: CharacterStyleSheet` and `character_spec: CharacterSpec`
- `_generate_scene()` builds prompt from `style_sheet.character_block` + `character_spec.scene_environment`
- Falls back to current hardcoded description if no style sheet provided (backward compat)

**`render/pose_planner.py`:**
- `plan_scenes()` accepts optional `CharacterSpec`
- Scene prompts incorporate `scene_environment` and `scene_elements` from theme
- `_FORMAT_TO_POSE` extended with theme-aware variants (e.g., Roblox obby: "jumping between platforms" instead of "pointing at word signs")

**`companion/generate_overlays.py`:**
- Remove hardcoded `_CHARACTER_DESC`
- `_build_variant_prompt()` accepts optional `CharacterStyleSheet`
- `_ITEM_DESCRIPTIONS` rendered in theme-appropriate style (e.g., "Roblox-style red hoodie" not just "red hoodie")

### Phase 5: Theme-Aware Judge

**File:** `companion/generate_overlays.py`

Update `_build_judge_prompt()` to accept optional `CharacterSpec` and add theme fidelity criteria:

```
Current criteria (keep):
- CHARACTER CONSISTENCY
- ITEM ACCURACY
- ART STYLE
- IMAGE QUALITY
- BACKGROUND

New criteria (add when CharacterSpec available):
- THEME FIDELITY: Does the character look like it belongs in [theme]?
  Specific checks from character_spec.judge_criteria
- STYLE MATCH: Does the rendering match [art_style]?
  (e.g., "flat cell-shading, blocky geometry, no gradients")
```

### Phase 6: Pipeline Integration

**Files:** `transform.py`, `batch.py`

Wire the style sheet through the pipeline:
- `transform.py` loads profile's style sheet and theme's character spec
- Passes them to `generate_worksheet_assets()` and `plan_scenes()`
- If profile has no style sheet for current theme, optionally runs character research (or warns)

### Phase 7: Tests

- `test_companion_schema.py`: CharacterStyleSheet model validation
- `test_theme_schema.py`: CharacterSpec model validation
- `test_character_research.py`: Research module (mocked MCP/API)
- `test_asset_gen.py`: Style sheet prompt assembly
- `test_pose_planner.py`: Theme-aware scene prompts
- Existing render tests: backward compatibility (no style sheet = current behavior)

## Implementation Order

1. Phase 1 + Phase 2 (schemas, can be parallel — different files)
2. Phase 3 (character research module, depends on schemas)
3. Phase 4 + Phase 5 (wiring + judge, can be parallel)
4. Phase 6 (pipeline integration, depends on 3+4)
5. Phase 7 (tests, throughout)

## Verification

1. Run `python -m companion.character_research --profile profiles/ian.yaml --theme roblox_obby`
   - Verify it produces a `CharacterStyleSheet` with Roblox-specific character block
   - Verify reference images in `assets/style_sheets/ian_roblox_obby/`
2. Run lesson 73 pipeline with new style sheet
   - Compare scene images to previous (should look more authentically Roblox)
3. Run `make test` — all existing + new tests pass
4. Run `make lint` + `make typecheck` — clean
