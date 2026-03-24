"""Theme-aware character research and style sheet generation.

Runs once per theme change to produce a CharacterStyleSheet:
1. Loads the theme's CharacterSpec (static visual DNA from config.yaml)
2. Optionally enriches via MCP research (perplexity-ask / exa) if spec is thin
3. Composes a frozen "character block" prompt from spec + child preferences
4. Optionally generates reference images via Gemini
5. Returns CharacterStyleSheet for persistence on the profile

Usage:
    python -m companion.character_research \\
        --profile profiles/ian.yaml --theme roblox_obby
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companion.schema import CharacterStyleSheet, LearnerProfile, Preferences
from theme.schema import CharacterSpec, ThemeConfig

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_STYLE_SHEETS_DIR = _ASSETS_DIR / "style_sheets"


def research_character_style(
    profile: LearnerProfile,
    theme: ThemeConfig,
    theme_id: str,
    *,
    skip_images: bool = False,
    skip_research: bool = False,
) -> CharacterStyleSheet:
    """Research theme visual language and produce a character style sheet.

    This is the expensive one-time step. Results are cached on the profile.

    Args:
        profile: The learner profile.
        theme: Loaded theme config with CharacterSpec.
        theme_id: Theme identifier string.
        skip_images: Skip reference image generation (faster, no Gemini).
        skip_research: Skip MCP research (use only static theme spec).

    Returns:
        CharacterStyleSheet ready to persist on the profile.
    """
    spec = theme.character_spec
    prefs = profile.preferences or Preferences()

    # Step 1: Enrich spec via MCP research if it's thin
    if not skip_research and _spec_needs_research(spec):
        enriched = _research_theme_visuals(theme.name, theme_id, spec)
        if enriched:
            spec = enriched

    # Step 2: Compose the frozen character block prompt
    character_block = _compose_character_block(spec, prefs, profile)

    # Step 3: Compose scene guidelines from spec
    scene_guidelines = _compose_scene_guidelines(spec)

    # Step 4: Compose item style notes
    item_style_notes = _compose_item_style_notes(spec)

    # Step 5: Optionally generate reference images
    ref_dir = ""
    if not skip_images:
        ref_dir = _generate_reference_pack(
            character_block, spec, profile.name, theme_id,
        )

    return CharacterStyleSheet(
        character_block=character_block,
        theme_id=theme_id,
        reference_image_dir=ref_dir,
        scene_guidelines=scene_guidelines,
        item_style_notes=item_style_notes,
        generated_at=datetime.now(UTC).isoformat(),
    )


def _spec_needs_research(spec: CharacterSpec) -> bool:
    """Check if the theme spec is too thin and needs MCP enrichment."""
    return not spec.style_description.strip() or not spec.body_description.strip()


def _research_theme_visuals(
    theme_name: str,
    theme_id: str,
    existing_spec: CharacterSpec,
) -> CharacterSpec | None:
    """Use perplexity-ask to research the theme's visual language.

    Returns an enriched CharacterSpec, or None if research is unavailable.
    """
    # Try perplexity via direct API (simpler than MCP in non-interactive context)
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        logger.info("  PERPLEXITY_API_KEY not set — skipping theme research")
        return None

    try:
        import httpx

        query = (
            f"What are the defining visual characteristics of {theme_name} "
            f"characters and environments that make them instantly recognizable? "
            f"Describe: body proportions, face styles, clothing rendering, "
            f"environment elements, color palette, and rendering style "
            f"(low-poly, cell-shaded, etc). Be specific and visual — "
            f"this will be used for AI image generation prompts."
        )

        response = httpx.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 1500,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        research_text = data["choices"][0]["message"]["content"]

        logger.info("  Theme research completed via Perplexity")

        # Parse research into spec fields using Gemini
        return _parse_research_into_spec(research_text, existing_spec)

    except Exception as e:
        logger.warning(f"  Theme research failed: {e}")
        return None


def _parse_research_into_spec(
    research_text: str,
    existing_spec: CharacterSpec,
) -> CharacterSpec | None:
    """Use Gemini to parse research text into structured CharacterSpec fields."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = (
            "You are a character design expert. Given this research about a theme's "
            "visual style, extract structured fields for AI image generation.\n\n"
            f"Research:\n{research_text}\n\n"
            "Return ONLY JSON (no markdown fences) with these fields:\n"
            '{\n'
            '  "style_description": "detailed art style for prompts",\n'
            '  "body_description": "body proportions and shapes",\n'
            '  "face_description": "face rendering style",\n'
            '  "scene_environment": "environment description",\n'
            '  "color_palette": "color palette description"\n'
            '}'
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part(text=prompt)],  # type: ignore[arg-type]
        )

        text = (response.text or "").strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )

        parsed: dict[str, Any] = json.loads(text)

        # Merge with existing spec — research fills gaps, doesn't overwrite
        return CharacterSpec(
            art_style=existing_spec.art_style or parsed.get("art_style", ""),
            style_description=(
                existing_spec.style_description
                or parsed.get("style_description", "")
            ),
            body_description=(
                existing_spec.body_description
                or parsed.get("body_description", "")
            ),
            face_description=(
                existing_spec.face_description
                or parsed.get("face_description", "")
            ),
            scene_environment=(
                existing_spec.scene_environment
                or parsed.get("scene_environment", "")
            ),
            scene_elements=existing_spec.scene_elements or [],
            color_palette=(
                existing_spec.color_palette
                or parsed.get("color_palette", "")
            ),
            reference_keywords=existing_spec.reference_keywords,
            judge_criteria=existing_spec.judge_criteria,
        )

    except Exception as e:
        logger.warning(f"  Research parsing failed: {e}")
        return None


def _compose_character_block(
    spec: CharacterSpec,
    prefs: Preferences,
    profile: LearnerProfile,
) -> str:
    """Compose the frozen character block prompt from spec + preferences.

    This replaces the hardcoded _CHARACTER_DESC in asset_gen.py and
    generate_overlays.py. It's stored once and reused on every render.
    """
    parts: list[str] = []

    # Art style framing
    if spec.style_description:
        parts.append(spec.style_description.strip())

    # Body description
    if spec.body_description:
        parts.append(f"Body: {spec.body_description.strip()}")

    # Face description
    if spec.face_description:
        parts.append(f"Face: {spec.face_description.strip()}")

    # Character-specific details from profile
    avatar = profile.avatar
    if avatar:
        color_parts = []
        colors = avatar.base_colors
        if colors.get("primary"):
            color_parts.append(f"primary color {colors['primary']}")
        if colors.get("secondary"):
            color_parts.append(f"secondary color {colors['secondary']}")
        if color_parts:
            parts.append(f"Character colors: {', '.join(color_parts)}.")

    # Color palette
    if spec.color_palette:
        parts.append(f"Palette: {spec.color_palette.strip()}")

    if not parts:
        # Fallback to a minimal generic description
        return (
            "a cute cartoon character with a friendly expression, "
            "bright colors, child-friendly style"
        )

    return " ".join(parts)


def _compose_scene_guidelines(spec: CharacterSpec) -> str:
    """Compose scene composition guidelines from the theme spec."""
    parts: list[str] = []

    if spec.scene_environment:
        parts.append(spec.scene_environment.strip())

    if spec.scene_elements:
        elements = ", ".join(spec.scene_elements)
        parts.append(f"Include elements like: {elements}.")

    return " ".join(parts) if parts else ""


def _compose_item_style_notes(spec: CharacterSpec) -> str:
    """Compose notes for how accessories should render in this theme's style."""
    if not spec.art_style:
        return ""

    return (
        f"All avatar items and accessories should match the {spec.art_style} "
        f"rendering style. Items should look like they belong in the same "
        f"visual universe — same geometry, shading, and color approach as "
        f"the base character."
    )


def _generate_reference_pack(
    character_block: str,
    spec: CharacterSpec,
    profile_name: str,
    theme_id: str,
) -> str:
    """Generate 3-5 reference images and save to style sheet directory.

    Returns the directory path, or empty string if generation fails.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.info("  No Gemini API key — skipping reference image generation")
        return ""

    safe_name = profile_name.lower().replace(" ", "_")
    ref_dir = _STYLE_SHEETS_DIR / f"{safe_name}_{theme_id}"
    ref_dir.mkdir(parents=True, exist_ok=True)

    # Check if pack already exists
    existing = list(ref_dir.glob("ref_*.png"))
    if len(existing) >= 3:
        logger.info(f"  Reference pack already exists: {ref_dir}")
        return str(ref_dir)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Load base character as reference if available
        base_path = _ASSETS_DIR / "characters" / "rainbow_roblox.png"
        ref_bytes: bytes | None = None
        if base_path.exists():
            ref_bytes = base_path.read_bytes()

        poses = [
            ("front", "standing facing forward, full body, centered, neutral T-pose"),
            ("happy", "jumping with arms up, celebrating, happy expression"),
            ("reading", "sitting and reading a large storybook, focused expression"),
        ]

        generated = 0
        for pose_name, pose_desc in poses:
            out_path = ref_dir / f"ref_{pose_name}.png"
            if out_path.exists():
                generated += 1
                continue

            prompt = (
                f"Generate an image of {character_block}. "
                f"The character is {pose_desc}. "
                f"Clean white background. No text, no words, no letters. "
                f"Full body visible."
            )
            if ref_bytes:
                prompt += " Keep the same character as the reference image."

            contents: list[types.Part] = [types.Part(text=prompt)]
            if ref_bytes:
                contents.append(
                    types.Part(
                        inline_data=types.Blob(
                            mime_type="image/png", data=ref_bytes,
                        ),
                    ),
                )

            response = client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=contents,  # type: ignore[arg-type]
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            for part in response.candidates[0].content.parts:  # type: ignore[index,union-attr]
                if part.inline_data and part.inline_data.data:
                    out_path.write_bytes(part.inline_data.data)
                    generated += 1
                    logger.info(f"  Generated reference: {out_path}")
                    break

        if generated > 0:
            logger.info(f"  Reference pack: {generated} images in {ref_dir}")
            return str(ref_dir)

    except ImportError:
        logger.info("  google-genai not installed — skipping reference images")
    except Exception as e:
        logger.warning(f"  Reference image generation failed: {e}")

    return str(ref_dir) if list(ref_dir.glob("ref_*.png")) else ""


# --- CLI entry point ---

def main() -> None:
    """CLI for character research."""
    import argparse

    from companion.schema import load_profile, save_profile
    from theme.engine import load_theme

    parser = argparse.ArgumentParser(
        description="Research theme visuals and generate style sheet",
    )
    parser.add_argument(
        "--profile", required=True, help="Path to learner profile YAML",
    )
    parser.add_argument(
        "--theme", required=True, help="Theme ID (e.g., roblox_obby)",
    )
    parser.add_argument(
        "--skip-images", action="store_true",
        help="Skip reference image generation",
    )
    parser.add_argument(
        "--skip-research", action="store_true",
        help="Skip MCP research (use static spec only)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    profile = load_profile(args.profile)
    theme = load_theme(args.theme)

    logger.info(f"Researching character style for {profile.name} + {theme.name}...")

    style_sheet = research_character_style(
        profile,
        theme,
        args.theme,
        skip_images=args.skip_images,
        skip_research=args.skip_research,
    )

    # Persist to profile
    if profile.avatar is None:
        from companion.schema import AvatarConfig
        profile.avatar = AvatarConfig()
    profile.avatar.style_sheet = style_sheet

    save_profile(profile, args.profile)
    logger.info(f"Style sheet saved to {args.profile}")
    logger.info(f"Character block:\n{style_sheet.character_block[:200]}...")
    if style_sheet.reference_image_dir:
        logger.info(f"Reference images: {style_sheet.reference_image_dir}")


if __name__ == "__main__":
    main()
