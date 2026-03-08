"""Theme engine — applies calm visual themes to adapted activities."""

from __future__ import annotations

from pathlib import Path

import yaml

from adapt.schema import AdaptedActivityModel
from theme.schema import (
    DecorativeConfig,
    ThemeColors,
    ThemeConfig,
    ThemedModel,
    ThemeFonts,
)

# Built-in themes directory
_THEMES_DIR = Path(__file__).parent / "themes"


def load_theme(theme_id: str) -> ThemeConfig:
    """Load a theme configuration by ID.

    Looks for config.yaml in theme/themes/<theme_id>/.
    Falls back to a built-in default theme if not found.
    """
    theme_dir = _THEMES_DIR / theme_id
    config_path = theme_dir / "config.yaml"

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return _parse_theme_config(data)

    # Built-in default theme
    return _default_theme()


def apply_theme(
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
) -> ThemedModel:
    """Apply a theme to an adapted activity model.

    Theme swap changes only visual elements, not content.
    Returns a ThemedModel ready for rendering.
    """
    # Determine decoration placements within decoration zones
    placements = _plan_decorations(adapted, theme)

    return ThemedModel(
        theme=theme,
        adapted_json=adapted.model_dump_json(),
        decoration_placements=placements,
    )


def _plan_decorations(
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
) -> list[dict[str, str | float]]:
    """Plan where decorative elements go, respecting decoration zones."""
    placements: list[dict[str, str | float]] = []

    assets = theme.decorative_elements.assets
    max_elements = theme.decorative_elements.max_per_page

    if not assets or not adapted.decoration_zones:
        return placements

    for i, zone in enumerate(adapted.decoration_zones):
        if i >= max_elements:
            break
        if i >= len(assets):
            break

        placements.append({
            "asset": assets[i],
            "x0": zone[0],
            "y0": zone[1],
            "x1": zone[2],
            "y1": zone[3],
        })

    return placements


def _parse_theme_config(data: dict[str, object]) -> ThemeConfig:
    """Parse a theme config from YAML data."""
    fonts_data = data.get("fonts", {})
    colors_data = data.get("colors", {})
    deco_data = data.get("decorative_elements", {})

    fonts = ThemeFonts(**fonts_data) if isinstance(fonts_data, dict) else ThemeFonts()
    colors = ThemeColors(**colors_data) if isinstance(colors_data, dict) else ThemeColors()
    deco = DecorativeConfig(**deco_data) if isinstance(deco_data, dict) else DecorativeConfig()

    return ThemeConfig(
        name=str(data.get("name", "Unknown")),
        style=str(data.get("style", "calm")),
        fonts=fonts,
        colors=colors,
        avatar_position=str(data.get("avatar_position", "bottom-right")),
        decorative_elements=deco,
    )


def _default_theme() -> ThemeConfig:
    """Return the built-in default theme (clean, calm, no decorations)."""
    return ThemeConfig(
        name="Default",
        style="calm",
        fonts=ThemeFonts(),
        colors=ThemeColors(),
        avatar_position="bottom-right",
        decorative_elements=DecorativeConfig(max_per_page=0),
    )
