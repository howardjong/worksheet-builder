"""Theme asset resolution — curated assets with generative fallback."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_THEMES_DIR = _ASSETS_DIR / "themes"


def resolve_decoration(asset_name: str, theme_id: str) -> Path | None:
    """Resolve a decorative asset by name and theme.

    Checks curated assets first. Handles both .png and .svg extensions.
    Returns the path if found, None otherwise.
    """
    theme_dir = _THEMES_DIR / theme_id

    # Try exact name first
    exact = theme_dir / asset_name
    if exact.exists():
        return exact

    # Try with .png extension if the name has .svg
    if asset_name.endswith(".svg"):
        png_name = asset_name.rsplit(".", 1)[0] + ".png"
        png_path = theme_dir / png_name
        if png_path.exists():
            return png_path

    # Try without extension
    stem = asset_name.rsplit(".", 1)[0] if "." in asset_name else asset_name
    for ext in [".png", ".svg", ".jpg"]:
        candidate = theme_dir / f"{stem}{ext}"
        if candidate.exists():
            return candidate

    logger.debug(f"Decoration asset not found: {asset_name} in theme {theme_id}")
    return None


def resolve_character(character_name: str) -> Path | None:
    """Resolve a base character image by name.

    Returns path to the character PNG, or None if not found.
    """
    char_dir = _ASSETS_DIR / "characters"
    for ext in [".png", ".svg"]:
        path = char_dir / f"{character_name}{ext}"
        if path.exists():
            return path

    logger.debug(f"Character asset not found: {character_name}")
    return None


def list_available_decorations(theme_id: str) -> list[str]:
    """List available decoration assets for a theme."""
    theme_dir = _THEMES_DIR / theme_id
    if not theme_dir.exists():
        return []

    return [
        f.name
        for f in theme_dir.iterdir()
        if f.suffix in (".png", ".svg", ".jpg")
    ]


def list_available_characters() -> list[str]:
    """List available base character names."""
    char_dir = _ASSETS_DIR / "characters"
    if not char_dir.exists():
        return []

    return [
        f.stem
        for f in char_dir.iterdir()
        if f.suffix in (".png", ".svg")
    ]
