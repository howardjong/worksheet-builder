"""Theme configuration schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ThemeFonts(BaseModel):
    """Font configuration for a theme."""

    primary: str = "Helvetica"
    heading: str = "Helvetica-Bold"


class ThemeColors(BaseModel):
    """Color palette for a theme — functional color coding."""

    directions: str = "#2563EB"  # Blue
    examples: str = "#059669"  # Green
    key_words: str = "#D97706"  # Amber
    rewards: str = "#D97706"  # Gold
    background: str = "#FAFAFA"  # Near-white
    text: str = "#1F2937"  # Dark gray
    chunk_border: str = "#E5E7EB"  # Light gray


class DecorativeConfig(BaseModel):
    """Decorative element constraints."""

    max_per_page: int = 2
    assets: list[str] = Field(default_factory=list)


class ThemeConfig(BaseModel):
    """Complete theme configuration."""

    name: str
    style: str = "calm"
    fonts: ThemeFonts = Field(default_factory=ThemeFonts)
    colors: ThemeColors = Field(default_factory=ThemeColors)
    avatar_position: str = "bottom-right"  # bottom-right/bottom-left/top-right/integrated
    decorative_elements: DecorativeConfig = Field(default_factory=DecorativeConfig)
    multi_worksheet: bool = False  # enable multi-worksheet (3 mini-worksheets per lesson)


class AssetManifest(BaseModel):
    """Manifest of generated assets for a worksheet — scenes and word pictures."""

    scene_paths: dict[int, str] = Field(default_factory=dict)  # chunk_id -> scene image path
    word_picture_paths: dict[str, str] = Field(default_factory=dict)  # word -> picture image path
    cache_dir: str = ""  # directory where cached assets are stored


class ThemedModel(BaseModel):
    """AdaptedActivityModel with theme applied — ready for rendering."""

    theme: ThemeConfig
    adapted_json: str  # serialized AdaptedActivityModel
    decoration_placements: list[dict[str, str | float]] = Field(default_factory=list)
