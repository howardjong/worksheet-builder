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

import logging
from datetime import UTC, datetime
from pathlib import Path

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
            character_block,
            spec,
            profile.name,
            theme_id,
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
    from ai import openrouter

    result = openrouter.complete(
        f"Research the defining visual characteristics of {theme_name} characters and "
        "environments: body proportions, face, clothing, palette, and rendering style. "
        "Give concrete descriptions for a faithful, calm children's worksheet illustration.",
        role="research",
        max_tokens=1500,
    )
    return _parse_research_into_spec(result.text, existing_spec) if result else None


def _parse_research_into_spec(
    research_text: str,
    existing_spec: CharacterSpec,
) -> CharacterSpec | None:
    """Use Gemini to parse research text into structured CharacterSpec fields."""
    from ai import openrouter

    raw = openrouter.complete_json(
        "Extract style_description, body_description, face_description, "
        "scene_environment, and color_palette from this visual research. Return JSON.\n"
        + research_text,
    )
    if raw is None:
        return None
    updates = {
        key: str(raw[key])
        for key in (
            "style_description",
            "body_description",
            "face_description",
            "scene_environment",
            "color_palette",
        )
        if raw.get(key) and not getattr(existing_spec, key)
    }
    return existing_spec.model_copy(update=updates)


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
    from ai import openrouter

    ref_dir = _STYLE_SHEETS_DIR / f"{profile_name.lower().replace(' ', '_')}_{theme_id}"
    ref_dir.mkdir(parents=True, exist_ok=True)
    base_path = _ASSETS_DIR / "characters" / "rainbow_roblox.png"
    reference = base_path.read_bytes() if base_path.exists() else None
    for pose, action in [
        ("front", "standing facing forward"),
        ("happy", "jumping happily"),
        ("reading", "reading a storybook"),
    ]:
        path = ref_dir / f"ref_{pose}.png"
        if path.exists():
            continue
        png = openrouter.generate_with_fallbacks(
            f"{character_block}. {action}. Full body, clean white background, no text.",
            reference,
            aspect_ratio="1:1",
        )
        if png:
            path.write_bytes(png)
            reference = png  # Keep subsequent poses consistent with the first reference.
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
        "--profile",
        required=True,
        help="Path to learner profile YAML",
    )
    parser.add_argument(
        "--theme",
        required=True,
        help="Theme ID (e.g., roblox_obby)",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Skip reference image generation",
    )
    parser.add_argument(
        "--skip-research",
        action="store_true",
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
