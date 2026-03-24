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
    example_bg: str = "#F0FDF4"  # worked-example box fill
    example_border: str = "#BBF7D0"  # worked-example box border
    reading_bg: str = "#EFF6FF"  # read-aloud box fill
    reading_border: str = "#BFDBFE"  # read-aloud box border
    writing_line: str = "#D1D5DB"  # writing line color
    micro_goal_bg: str = "#FEF3C7"  # micro-goal pill background


class DecorativeConfig(BaseModel):
    """Decorative element constraints."""

    max_per_page: int = 2
    assets: list[str] = Field(default_factory=list)


class CharacterSpec(BaseModel):
    """Theme-specific character visual identity — drives prompt generation and judge criteria."""

    art_style: str = ""  # e.g., "roblox_3d_cartoon"
    style_description: str = ""  # detailed prompt-ready art style description
    body_description: str = ""  # proportions, shapes, rig details
    face_description: str = ""  # face rendering style
    scene_environment: str = ""  # environment description for scene prompts
    scene_elements: list[str] = Field(default_factory=list)  # props/objects in scenes
    color_palette: str = ""  # palette description for prompt
    reference_keywords: list[str] = Field(default_factory=list)  # search anchors
    judge_criteria: list[str] = Field(default_factory=list)  # theme-specific quality checks


class ThemeConfig(BaseModel):
    """Complete theme configuration."""

    name: str
    style: str = "calm"
    fonts: ThemeFonts = Field(default_factory=ThemeFonts)
    colors: ThemeColors = Field(default_factory=ThemeColors)
    avatar_position: str = "bottom-right"  # bottom-right/bottom-left/top-right/integrated
    decorative_elements: DecorativeConfig = Field(default_factory=DecorativeConfig)
    multi_worksheet: bool = False  # enable multi-worksheet (3 mini-worksheets per lesson)
    character_spec: CharacterSpec = Field(default_factory=CharacterSpec)


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
