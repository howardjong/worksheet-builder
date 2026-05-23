"""AI scene generation with caching — generates character scenes and word pictures.

Uses Gemini Flash Image for generation with the learner's base character as a
reference image for consistency. Falls back gracefully when no API key is available.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import textwrap
from pathlib import Path
from typing import Any

from companion.schema import CharacterStyleSheet
from render.pose_planner import ScenePlan
from theme.schema import AssetManifest, CharacterSpec

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "cache"
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
_LOCAL_ASSET_VERSION = "activity_v6"

# Fallback character description — used only when no style sheet is available
_FALLBACK_CHARACTER_DESC = (
    "a cute blocky Roblox-style character with rainbow-colored spiky hair "
    "(red, orange, yellow, green, blue, purple), a simple smiling face with "
    "dot eyes and a curved mouth, a peach/skin-colored square head and hands, "
    "a blue t-shirt with a yellow lightning bolt, brown pants, and orange sneakers"
)


def generate_worksheet_assets(
    scene_plans: list[ScenePlan],
    word_picture_prompts: dict[str, str],
    worksheet_hash: str,
    character_name: str = "rainbow_roblox",
    style_sheet: CharacterStyleSheet | None = None,
    character_spec: CharacterSpec | None = None,
) -> AssetManifest | None:
    """Generate all assets for a worksheet: scenes + word pictures.

    Returns an AssetManifest with paths to generated images,
    or None if generation is unavailable (no API key).

    Uses content-hash-based caching -- second run with same content
    hits cache with no API calls.
    """
    if os.environ.get("WORKSHEET_SKIP_ASSET_GEN"):
        return None

    safe_character = re.sub(r"[^A-Za-z0-9_-]+", "_", character_name)
    cache_key = f"worksheet_{worksheet_hash}_{safe_character}_{_LOCAL_ASSET_VERSION}"
    cache_dir = _CACHE_DIR / cache_key

    # Check if all assets already cached
    manifest = _check_cache(cache_dir, scene_plans, word_picture_prompts)
    if manifest is not None:
        logger.info(f"  Asset cache hit: {cache_dir}")
        return manifest

    # Load reference character
    ref_path = _ASSETS_DIR / "characters" / f"{character_name}.png"
    ref_bytes: bytes | None = None
    if ref_path.exists():
        ref_bytes = ref_path.read_bytes()

    cache_dir.mkdir(parents=True, exist_ok=True)

    scene_paths: dict[int, str] = {}
    word_paths: dict[str, str] = {}

    # Load additional reference images from style sheet pack
    extra_ref_bytes: bytes | None = None
    if style_sheet and style_sheet.reference_image_dir:
        ref_pack_dir = Path(style_sheet.reference_image_dir)
        front_ref = ref_pack_dir / "ref_front.png"
        if front_ref.exists():
            extra_ref_bytes = front_ref.read_bytes()

    # Generate scene images
    for plan in scene_plans:
        scene_file = cache_dir / f"scene_{plan.chunk_id}.png"
        if scene_file.exists():
            scene_paths[plan.chunk_id] = str(scene_file)
            continue

        if _has_api_key():
            result = _generate_scene(
                plan.scene_prompt,
                str(scene_file),
                extra_ref_bytes or ref_bytes,
                style_sheet=style_sheet,
                character_spec=character_spec,
            )
            if result is None:
                result = _generate_local_scene(
                    plan,
                    str(scene_file),
                    character_spec,
                    character_name=character_name,
                    style_sheet=style_sheet,
                )
        else:
            result = _generate_local_scene(
                plan,
                str(scene_file),
                character_spec,
                character_name=character_name,
                style_sheet=style_sheet,
            )
        if result:
            scene_paths[plan.chunk_id] = result

    # Generate word picture images (no reference character needed)
    for word, prompt in word_picture_prompts.items():
        safe_name = word.lower().replace(" ", "_")
        word_file = cache_dir / f"word_{safe_name}.png"
        if word_file.exists():
            word_paths[word] = str(word_file)
            continue

        if _has_api_key():
            result = _generate_word_picture(prompt, str(word_file))
            if result is None:
                result = _generate_local_word_picture(
                    word,
                    prompt,
                    str(word_file),
                    character_name=character_name,
                    style_sheet=style_sheet,
                )
        else:
            result = _generate_local_word_picture(
                word,
                prompt,
                str(word_file),
                character_name=character_name,
                style_sheet=style_sheet,
            )
        if result:
            word_paths[word] = result

    return AssetManifest(
        scene_paths=scene_paths,
        word_picture_paths=word_paths,
        cache_dir=str(cache_dir),
    )


def _check_cache(
    cache_dir: Path,
    scene_plans: list[ScenePlan],
    word_prompts: dict[str, str],
) -> AssetManifest | None:
    """Check if all needed assets are already cached."""
    if not cache_dir.exists():
        return None

    scene_paths: dict[int, str] = {}
    word_paths: dict[str, str] = {}

    for plan in scene_plans:
        scene_file = cache_dir / f"scene_{plan.chunk_id}.png"
        if not scene_file.exists():
            return None
        scene_paths[plan.chunk_id] = str(scene_file)

    for word in word_prompts:
        safe_name = word.lower().replace(" ", "_")
        word_file = cache_dir / f"word_{safe_name}.png"
        if not word_file.exists():
            return None
        word_paths[word] = str(word_file)

    return AssetManifest(
        scene_paths=scene_paths,
        word_picture_paths=word_paths,
        cache_dir=str(cache_dir),
    )


def _has_api_key() -> bool:
    """Check if a Gemini API key is available."""
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def _generate_scene(
    prompt: str,
    output_path: str,
    ref_bytes: bytes | None,
    *,
    style_sheet: CharacterStyleSheet | None = None,
    character_spec: CharacterSpec | None = None,
) -> str | None:
    """Generate a character scene image using Gemini with reference character.

    Uses the profile's CharacterStyleSheet for theme-accurate prompts when
    available, falling back to the generic description otherwise.
    """
    try:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)

        # Use style sheet character block or fallback
        char_desc = (
            style_sheet.character_block
            if style_sheet and style_sheet.character_block
            else _FALLBACK_CHARACTER_DESC
        )

        # Build scene environment context from theme spec
        env_context = ""
        if character_spec and character_spec.scene_environment:
            env_context = f" The scene is set in {character_spec.scene_environment.strip()}"

        full_prompt = (
            f"Generate an image of {char_desc}, "
            f"{prompt}{env_context} "
            f"Keep the same character style as the reference image. "
            f"Bright colors, child-friendly, clean white background. "
            f"No text, no words, no letters in the image."
        )

        contents: list[types.Part] = [types.Part(text=full_prompt)]
        if ref_bytes:
            contents.append(
                types.Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=ref_bytes,
                    ),
                ),
            )

        response = client.models.generate_content(
            model=_IMAGE_MODEL,
            contents=contents,  # type: ignore[arg-type]
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:  # type: ignore[index,union-attr]
            if part.inline_data and part.inline_data.data:
                Path(output_path).write_bytes(part.inline_data.data)
                logger.info(f"  Generated scene: {output_path}")
                return output_path

        logger.warning(f"  No image in response for: {output_path}")
        return None

    except ImportError:
        logger.info("  google-genai not installed")
        return None
    except Exception as e:
        logger.warning(f"  Scene generation failed: {e}")
        return None


def _generate_word_picture(
    prompt: str,
    output_path: str,
) -> str | None:
    """Generate a small word picture icon (no reference character needed)."""
    try:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=_IMAGE_MODEL,
            contents=[types.Part(text=prompt)],  # type: ignore[arg-type]
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:  # type: ignore[index,union-attr]
            if part.inline_data and part.inline_data.data:
                Path(output_path).write_bytes(part.inline_data.data)
                logger.info(f"  Generated word picture: {output_path}")
                return output_path

        logger.warning(f"  No image in response for: {output_path}")
        return None

    except ImportError:
        logger.info("  google-genai not installed")
        return None
    except Exception as e:
        logger.warning(f"  Word picture generation failed: {e}")
        return None


def generate_cover_image(
    skill_description: str,
    target_words: list[str],
    theme_spec: CharacterSpec | None,
    worksheet_hash: str,
    character_name: str = "rainbow_roblox",
    style_sheet: CharacterStyleSheet | None = None,
) -> str | None:
    """Generate an AI cover image for a lesson package.

    Returns path to cached PNG or None if generation is unavailable.
    """
    if os.environ.get("WORKSHEET_SKIP_ASSET_GEN"):
        return None

    safe_character = re.sub(r"[^A-Za-z0-9_-]+", "_", character_name)
    cache_key = f"worksheet_{worksheet_hash}_{safe_character}_{_LOCAL_ASSET_VERSION}"
    cache_dir = _CACHE_DIR / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    cover_file = cache_dir / "cover.png"

    if cover_file.exists():
        logger.info(f"  Cover image cache hit: {cover_file}")
        return str(cover_file)

    if not _has_api_key():
        logger.info("  No AI API key -- using local cover image fallback")
        return _generate_local_cover_image(
            skill_description,
            target_words,
            theme_spec,
            str(cover_file),
            character_name=character_name,
            style_sheet=style_sheet,
        )

    # Build theme-aware prompt
    char_desc = ""
    env_desc = ""
    if theme_spec:
        if theme_spec.style_description:
            char_desc = f" featuring {theme_spec.style_description}"
        if theme_spec.scene_environment:
            env_desc = f" set in {theme_spec.scene_environment.strip()}"

    words_str = ", ".join(target_words[:6]) if target_words else ""
    word_context = f" surrounded by the words '{words_str}'." if words_str else "."

    prompt = (
        f"Fun colorful cartoon illustration for a children's worksheet cover page. "
        f"Scene: an exciting adventure{char_desc}{env_desc}{word_context} "
        f"Skill focus: {skill_description}. "
        f"Style: bright vibrant colors, Pixar-like, playful, child-friendly. "
        f"Clean composition suitable for printing. "
        f"No text, no words, no letters in the image."
    )

    result = _generate_word_picture(prompt, str(cover_file))
    if result:
        return result
    return _generate_local_cover_image(
        skill_description,
        target_words,
        theme_spec,
        str(cover_file),
        character_name=character_name,
        style_sheet=style_sheet,
    )


def _generate_local_scene(
    plan: ScenePlan,
    output_path: str,
    character_spec: CharacterSpec | None,
    *,
    character_name: str = "rainbow_roblox",
    style_sheet: CharacterStyleSheet | None = None,
) -> str:
    """Create a deterministic local scene card when AI image generation is unavailable."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.info("  Pillow not installed; local scene fallback unavailable")
        return ""

    width, height = 900, 600
    img = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(img)
    heading = _load_font(ImageFont, 44, bold=True)
    small = _load_font(ImageFont, 24)

    _draw_obby_background(draw, width, height)
    _draw_platform(draw, width, height)
    _draw_activity_props(draw, plan.pose, plan.activity_context, width, height, small)

    draw.rounded_rectangle(
        (54, 64, 536, 408),
        radius=34,
        fill="#DBEAFE",
        outline="#1F2937",
        width=4,
    )
    _draw_room_floor(draw, (54, 64, 536, 408))
    _draw_ian_action_character(draw, 292, 388, plan.pose, scale=0.78)

    accent = "#2563EB"
    if character_spec and character_spec.art_style in {
        "roblox_3d_cartoon",
        "roblox_2d_comic_avatar",
    }:
        accent = "#7C3AED"
    draw.rounded_rectangle(
        (548, 388, width - 52, 548),
        radius=30,
        fill="#FFFFFF",
        outline=accent,
        width=5,
    )
    draw.text((578, 410), _scene_title(plan.pose), fill=accent, font=heading)
    context = plan.activity_context or "practice words"
    wrapped = textwrap.wrap(f"Mission: {context}", width=28)[:3]
    for idx, line in enumerate(wrapped):
        draw.text((582, 466 + idx * 27), line, fill="#1F2937", font=small)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    logger.info("  Generated local scene fallback: %s", output_path)
    return output_path


def _draw_activity_props(
    draw: Any,
    pose: str,
    activity_context: str,
    width: int,
    height: int,
    font: Any,
) -> None:
    """Draw simple task props so local scenes connect to the worksheet activity."""
    panel = (572, 74, width - 56, 366)
    draw.rounded_rectangle(panel, radius=34, fill="#FFFFFF", outline="#CBD5E1", width=4)

    if pose == "pointing":
        _draw_picture_match_props(draw, panel, activity_context, font)
    elif pose in {"writing", "building"}:
        _draw_word_build_props(draw, panel, activity_context, font)
    elif pose == "reading":
        _draw_reading_props(draw, panel, activity_context, font)
    elif pose == "listening":
        _draw_sound_props(draw, panel)
    else:
        _draw_thinking_props(draw, panel, activity_context, font)


def _draw_picture_match_props(
    draw: Any,
    panel: tuple[int, int, int, int],
    activity_context: str,
    font: Any,
) -> None:
    x0, y0, x1, _ = panel
    words = _context_words(activity_context)
    colors = ["#DBEAFE", "#FEF3C7", "#DCFCE7"]
    for idx in range(3):
        top = y0 + 34 + idx * 76
        draw.rounded_rectangle(
            (x0 + 28, top, x0 + 154, top + 54),
            radius=18,
            fill="#F8FAFC",
            outline="#94A3B8",
            width=3,
        )
        draw.rounded_rectangle(
            (x1 - 154, top, x1 - 28, top + 54),
            radius=18,
            fill=colors[idx],
            outline="#64748B",
            width=3,
        )
        draw.line((x0 + 170, top + 27, x1 - 170, top + 27), fill="#94A3B8", width=3)
        _draw_tiny_symbol(draw, x1 - 91, top + 27, idx)
        if idx < len(words):
            draw.text((x0 + 44, top + 17), words[idx][:8], fill="#1F2937", font=font)


def _draw_word_build_props(
    draw: Any,
    panel: tuple[int, int, int, int],
    activity_context: str,
    font: Any,
) -> None:
    x0, y0, x1, _ = panel
    words = _context_words(activity_context)
    target = words[0] if words else "word"
    for idx, ch in enumerate(target[:5]):
        left = x0 + 34 + idx * 58
        draw.rounded_rectangle(
            (left, y0 + 46, left + 48, y0 + 100),
            radius=10,
            fill="#FEF3C7",
            outline="#D97706",
            width=3,
        )
        draw.text((left + 24, y0 + 73), ch, fill="#92400E", font=font, anchor="mm")
    for idx in range(max(3, min(5, len(target)))):
        left = x0 + 40 + idx * 62
        draw.line((left, y0 + 178, left + 46, y0 + 178), fill="#2563EB", width=5)
    draw.rounded_rectangle(
        (x1 - 122, y0 + 128, x1 - 48, y0 + 212),
        radius=16,
        fill="#DBEAFE",
        outline="#2563EB",
        width=3,
    )
    draw.line((x1 - 110, y0 + 198, x1 - 58, y0 + 146), fill="#F97316", width=9)


def _draw_reading_props(
    draw: Any,
    panel: tuple[int, int, int, int],
    activity_context: str,
    font: Any,
) -> None:
    x0, y0, x1, _ = panel
    draw.rounded_rectangle(
        (x0 + 46, y0 + 48, x1 - 46, y0 + 218),
        radius=22,
        fill="#DBEAFE",
        outline="#2563EB",
        width=4,
    )
    draw.line((x0 + 186, y0 + 54, x0 + 186, y0 + 212), fill="#60A5FA", width=4)
    for idx, word in enumerate(_context_words(activity_context)[:4]):
        draw.text((x0 + 76, y0 + 78 + idx * 30), word[:10], fill="#1F2937", font=font)


def _draw_sound_props(draw: Any, panel: tuple[int, int, int, int]) -> None:
    x0, y0, x1, _ = panel
    cx, cy = (x0 + x1) // 2, y0 + 142
    draw.arc((cx - 92, cy - 92, cx + 92, cy + 92), 300, 60, fill="#2563EB", width=8)
    draw.arc((cx - 130, cy - 130, cx + 130, cy + 130), 310, 50, fill="#60A5FA", width=7)
    draw.rounded_rectangle(
        (cx - 44, cy - 60, cx + 26, cy + 60),
        radius=22,
        fill="#FEF3C7",
        outline="#92400E",
        width=4,
    )


def _draw_thinking_props(
    draw: Any,
    panel: tuple[int, int, int, int],
    activity_context: str,
    font: Any,
) -> None:
    x0, y0, x1, _ = panel
    for idx, word in enumerate(_context_words(activity_context)[:4]):
        left = x0 + 42 + (idx % 2) * 150
        top = y0 + 54 + (idx // 2) * 86
        draw.rounded_rectangle(
            (left, top, left + 124, top + 54),
            radius=18,
            fill="#F8FAFC",
            outline="#94A3B8",
            width=3,
        )
        draw.text((left + 16, top + 16), word[:8], fill="#1F2937", font=font)
    draw.ellipse((x1 - 112, y0 + 174, x1 - 42, y0 + 244), outline="#7C3AED", width=7)
    draw.line((x1 - 58, y0 + 228, x1 - 20, y0 + 266), fill="#7C3AED", width=8)


def _generate_local_word_picture(
    word: str,
    prompt: str,
    output_path: str,
    *,
    character_name: str = "rainbow_roblox",
    style_sheet: CharacterStyleSheet | None = None,
) -> str:
    """Create a deterministic local phonics picture card for a match tile."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.info("  Pillow not installed; local word fallback unavailable")
        return ""

    width = height = 512
    img = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (18, 18, width - 18, height - 18),
        radius=46,
        fill="#F8FAFC",
        outline="#CBD5E1",
        width=6,
    )
    _draw_word_symbol(draw, word, width, height)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    logger.info("  Generated local word fallback: %s", output_path)
    return output_path


def _generate_local_cover_image(
    skill_description: str,
    target_words: list[str],
    theme_spec: CharacterSpec | None,
    output_path: str,
    *,
    character_name: str = "rainbow_roblox",
    style_sheet: CharacterStyleSheet | None = None,
) -> str:
    """Create a deterministic printable cover image without external services."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.info("  Pillow not installed; local cover fallback unavailable")
        return ""

    width, height = 2100, 1350
    img = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(img)
    heading = _load_font(ImageFont, 120, bold=True)
    body = _load_font(ImageFont, 62)
    small = _load_font(ImageFont, 48)

    _draw_obby_background(draw, width, height, step=120)
    _draw_platform(draw, width, height, scale=2.4)
    draw.rounded_rectangle(
        (620, 110, 1480, 820),
        radius=88,
        fill="#DBEAFE",
        outline="#1F2937",
        width=10,
    )
    _draw_room_floor(draw, (620, 110, 1480, 820), scale=2.0)
    _draw_ian_action_character(draw, width // 2, 790, "celebrating", scale=1.65)
    accent = "#7C3AED" if theme_spec and theme_spec.art_style else "#2563EB"

    draw.rounded_rectangle(
        (150, 920, width - 150, 1210), radius=70, fill="#FFFFFF", outline=accent, width=12
    )
    draw.text((width / 2, 1010), "Reading Mission", fill=accent, font=heading, anchor="mm")
    draw.text((width / 2, 1115), skill_description[:54], fill="#1F2937", font=body, anchor="mm")
    words = "  ".join(target_words[:6])
    draw.text((width / 2, 1270), words, fill="#475569", font=small, anchor="mm")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    logger.info("  Generated local cover fallback: %s", output_path)
    return output_path


def _load_font(image_font_module: Any, size: int, *, bold: bool = False) -> Any:
    font_name = "Fredoka-VariableFont.ttf" if bold else "Lexend-VariableFont.ttf"
    font_path = _ASSETS_DIR / "fonts" / font_name
    try:
        return image_font_module.truetype(str(font_path), size)
    except Exception:
        return image_font_module.load_default()


def _draw_soft_grid(draw: Any, width: int, height: int, *, step: int = 72) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill="#E2E8F0", width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill="#E2E8F0", width=1)


def _draw_obby_background(draw: Any, width: int, height: int, *, step: int = 72) -> None:
    """Draw a calm obby-inspired background with print-safe contrast."""
    _draw_soft_grid(draw, width, height, step=step)
    colors = ["#DBEAFE", "#EDE9FE", "#DCFCE7", "#FEF3C7"]
    block_w = max(42, width // 16)
    block_h = max(20, height // 18)
    y = int(height * 0.18)
    for idx, color in enumerate(colors * 3):
        x = int(width * 0.08) + idx * int(block_w * 1.45)
        offset = int((idx % 3) * block_h * 0.8)
        draw.rounded_rectangle(
            (x, y + offset, x + block_w, y + offset + block_h),
            radius=10,
            fill=color,
            outline="#CBD5E1",
            width=2,
        )
    for idx, color in enumerate(reversed(colors * 3)):
        x = int(width * 0.06) + idx * int(block_w * 1.35)
        y2 = int(height * 0.72) + int((idx % 2) * block_h * 0.5)
        draw.rounded_rectangle(
            (x, y2, x + block_w, y2 + block_h),
            radius=10,
            fill=color,
            outline="#CBD5E1",
            width=2,
        )


def _draw_platform(draw: Any, width: int, height: int, *, scale: float = 1.0) -> None:
    y = int(height * 0.62)
    h = int(80 * scale)
    draw.rounded_rectangle(
        (int(width * 0.22), y, int(width * 0.78), y + h),
        radius=int(18 * scale),
        fill="#DBEAFE",
        outline="#60A5FA",
        width=max(3, int(4 * scale)),
    )
    draw.rectangle(
        (int(width * 0.28), y + h, int(width * 0.72), y + h + int(24 * scale)), fill="#C4B5FD"
    )


def _draw_room_floor(
    draw: Any,
    box: tuple[int, int, int, int],
    *,
    scale: float = 1.0,
) -> None:
    x0, y0, x1, y1 = box
    floor_y = int(y0 + (y1 - y0) * 0.68)
    draw.rectangle((x0 + 4, floor_y, x1 - 4, y1 - 4), fill="#FCD9A7")
    for offset in range(0, x1 - x0, max(28, int(42 * scale))):
        draw.line(
            (x0 + offset, floor_y, x0 + offset - 70, y1),
            fill="#D89A4A",
            width=max(1, int(2 * scale)),
        )
    for y in range(floor_y + 18, y1, max(18, int(24 * scale))):
        draw.line((x0 + 6, y, x1 - 6, y), fill="#E7B76E", width=max(1, int(2 * scale)))


def _draw_ian_action_character(
    draw: Any,
    cx: int,
    foot_y: int,
    pose: str,
    *,
    scale: float = 1.0,
) -> None:
    """Draw Ian as new local artwork using the profile's reference attributes."""
    s = scale

    def rr(x0: float, y0: float, x1: float, y1: float, fill: str, width: int = 4) -> None:
        draw.rounded_rectangle(
            (
                cx + int(x0 * s),
                foot_y + int(y0 * s),
                cx + int(x1 * s),
                foot_y + int(y1 * s),
            ),
            radius=max(5, int(10 * s)),
            fill=fill,
            outline="#111827",
            width=max(2, int(width * s)),
        )

    # Legs and orange sneakers.
    rr(-54, -132, -10, -32, "#7C4A28")
    rr(12, -132, 56, -32, "#7C4A28")
    rr(-70, -36, -2, -6, "#F97316")
    rr(4, -36, 72, -6, "#F97316")
    draw.line(
        (cx - int(54 * s), foot_y - int(22 * s), cx - int(12 * s), foot_y - int(22 * s)),
        fill="#FFFFFF",
        width=max(2, int(4 * s)),
    )
    draw.line(
        (cx + int(20 * s), foot_y - int(22 * s), cx + int(62 * s), foot_y - int(22 * s)),
        fill="#FFFFFF",
        width=max(2, int(4 * s)),
    )

    # Torso with yellow lightning bolt.
    rr(-70, -250, 70, -128, "#0EA5E9")
    draw.polygon(
        [
            (cx - int(4 * s), foot_y - int(236 * s)),
            (cx + int(32 * s), foot_y - int(236 * s)),
            (cx + int(10 * s), foot_y - int(188 * s)),
            (cx + int(36 * s), foot_y - int(188 * s)),
            (cx - int(16 * s), foot_y - int(132 * s)),
            (cx + int(0 * s), foot_y - int(182 * s)),
            (cx - int(28 * s), foot_y - int(182 * s)),
        ],
        fill="#FACC15",
        outline="#111827",
    )

    _draw_ian_arms(draw, cx, foot_y, pose, s)

    # Head and face.
    rr(-52, -348, 52, -248, "#F3B184")
    eye_y = foot_y - int(302 * s)
    draw.ellipse((cx - int(24 * s), eye_y, cx - int(14 * s), eye_y + int(14 * s)), fill="#111827")
    draw.ellipse((cx + int(14 * s), eye_y, cx + int(24 * s), eye_y + int(14 * s)), fill="#111827")
    if pose == "celebrating":
        draw.arc(
            (cx - int(25 * s), foot_y - int(294 * s), cx + int(25 * s), foot_y - int(258 * s)),
            5,
            175,
            fill="#111827",
            width=max(2, int(4 * s)),
        )
    else:
        draw.arc(
            (cx - int(24 * s), foot_y - int(286 * s), cx + int(24 * s), foot_y - int(262 * s)),
            15,
            165,
            fill="#111827",
            width=max(2, int(4 * s)),
        )

    _draw_rainbow_hair(draw, cx, foot_y, s)


def _draw_ian_arms(draw: Any, cx: int, foot_y: int, pose: str, s: float) -> None:
    def limb(points: list[tuple[float, float]], fill: str = "#F3B184") -> None:
        draw.polygon(
            [(cx + int(x * s), foot_y + int(y * s)) for x, y in points],
            fill=fill,
            outline="#111827",
        )

    if pose == "pointing":
        limb([(-74, -238), (-142, -224), (-132, -188), (-70, -202)])
        limb([(72, -236), (154, -284), (172, -250), (88, -202)])
        draw.ellipse(
            (cx + int(148 * s), foot_y - int(294 * s), cx + int(184 * s), foot_y - int(256 * s)),
            fill="#F3B184",
            outline="#111827",
            width=max(2, int(4 * s)),
        )
    elif pose in {"writing", "building"}:
        limb([(-74, -224), (-128, -170), (-100, -148), (-58, -196)])
        limb([(72, -220), (142, -164), (116, -136), (52, -192)])
        draw.rounded_rectangle(
            (
                cx + int(62 * s),
                foot_y - int(162 * s),
                cx + int(152 * s),
                foot_y - int(108 * s),
            ),
            radius=max(4, int(8 * s)),
            fill="#FFFFFF",
            outline="#2563EB",
            width=max(2, int(3 * s)),
        )
        draw.line(
            (cx + int(126 * s), foot_y - int(150 * s), cx + int(154 * s), foot_y - int(180 * s)),
            fill="#F97316",
            width=max(4, int(7 * s)),
        )
    elif pose == "celebrating":
        limb([(-72, -236), (-150, -320), (-126, -344), (-52, -252)])
        limb([(72, -236), (150, -320), (126, -344), (52, -252)])
        confetti = [
            (-170, -368, "#EF4444"),
            (162, -374, "#22C55E"),
            (0, -390, "#FACC15"),
        ]
        for dx, dy, color in confetti:
            draw.rectangle(
                (
                    cx + int(dx * s),
                    foot_y + int(dy * s),
                    cx + int((dx + 16) * s),
                    foot_y + int((dy + 16) * s),
                ),
                fill=color,
            )
    else:
        limb([(-74, -232), (-132, -202), (-114, -166), (-60, -198)])
        limb([(74, -232), (132, -202), (114, -166), (60, -198)])


def _draw_rainbow_hair(draw: Any, cx: int, foot_y: int, s: float) -> None:
    colors = [
        "#EF4444",
        "#F97316",
        "#FACC15",
        "#22C55E",
        "#06B6D4",
        "#2563EB",
        "#7C3AED",
        "#DB2777",
    ]
    spikes = [
        (-56, -342, -96, -410, -18, -368),
        (-38, -356, -52, -432, 10, -374),
        (-14, -368, -6, -444, 34, -372),
        (12, -368, 34, -438, 56, -360),
        (36, -354, 78, -416, 70, -332),
        (-72, -330, -122, -370, -68, -296),
        (56, -332, 104, -382, 84, -296),
        (-8, -350, 78, -408, 46, -318),
    ]
    for color, (x1, y1, x2, y2, x3, y3) in zip(colors, spikes, strict=False):
        draw.polygon(
            [
                (cx + int(x1 * s), foot_y + int(y1 * s)),
                (cx + int(x2 * s), foot_y + int(y2 * s)),
                (cx + int(x3 * s), foot_y + int(y3 * s)),
            ],
            fill=color,
            outline="#111827",
        )


def _context_words(activity_context: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", activity_context)
    stop = {"words", "word", "practice", "skill", "focus", "story", "sentence"}
    filtered = [word for word in words if word.lower() not in stop]
    return filtered[:6]


def _draw_tiny_symbol(draw: Any, cx: int, cy: int, idx: int) -> None:
    if idx == 0:
        draw.ellipse(
            (cx - 22, cy - 18, cx + 22, cy + 18),
            fill="#60A5FA",
            outline="#1D4ED8",
            width=3,
        )
        draw.rectangle((cx - 30, cy + 4, cx + 30, cy + 24), fill="#DBEAFE")
    elif idx == 1:
        draw.polygon(
            [(cx, cy - 28), (cx + 32, cy + 22), (cx - 32, cy + 22)],
            fill="#FCD34D",
            outline="#92400E",
        )
    else:
        draw.rounded_rectangle(
            (cx - 28, cy - 24, cx + 28, cy + 24),
            radius=10,
            fill="#86EFAC",
            outline="#166534",
            width=3,
        )


def _draw_word_symbol(draw: Any, word: str, width: int, height: int) -> None:
    lower = word.lower()
    cx, cy = width // 2, 190
    if any(key in lower for key in ("rain", "storm", "snow")):
        draw.ellipse((135, 125, 245, 220), fill="#BFDBFE", outline="#2563EB", width=5)
        draw.ellipse((210, 105, 340, 220), fill="#DBEAFE", outline="#2563EB", width=5)
        draw.rectangle((150, 170, 360, 228), fill="#DBEAFE")
        drops = "#60A5FA" if "snow" not in lower else "#CBD5E1"
        for x in (170, 230, 290, 350):
            draw.ellipse((x, 245, x + 26, 271), fill=drops)
        if "storm" in lower:
            draw.polygon([(250, 215), (220, 300), (270, 270), (245, 350)], fill="#FACC15")
    elif any(key in lower for key in ("say", "lies")):
        draw.rounded_rectangle(
            (115, 120, 380, 245), radius=34, fill="#DBEAFE", outline="#2563EB", width=5
        )
        draw.polygon([(190, 245), (150, 305), (250, 245)], fill="#DBEAFE", outline="#2563EB")
        for x in (175, 240, 305):
            draw.ellipse((x, 172, x + 30, 202), fill="#1D4ED8")
    elif any(key in lower for key in ("main", "away", "roam", "railway")):
        draw.rounded_rectangle(
            (90, 245, 422, 305), radius=22, fill="#94A3B8", outline="#475569", width=5
        )
        for x in range(120, 390, 72):
            draw.rectangle((x, 273, x + 36, 282), fill="#F8FAFC")
        if "railway" in lower:
            draw.rectangle((145, 135, 350, 215), fill="#93C5FD", outline="#1D4ED8", width=5)
            draw.ellipse((168, 213, 214, 259), fill="#1F2937")
            draw.ellipse((288, 213, 334, 259), fill="#1F2937")
        else:
            draw.polygon([(355, 165), (425, 215), (355, 265)], fill="#F97316")
    elif any(key in lower for key in ("wait", "today")):
        draw.ellipse((142, 100, 370, 328), fill="#FFFFFF", outline="#2563EB", width=8)
        draw.line((256, 214, 256, 142), fill="#1F2937", width=8)
        draw.line((256, 214, 312, 242), fill="#1F2937", width=8)
    elif any(key in lower for key in ("sleep", "dream")):
        draw.rounded_rectangle(
            (95, 185, 420, 290), radius=24, fill="#C7D2FE", outline="#4F46E5", width=5
        )
        draw.rectangle((95, 235, 420, 300), fill="#DBEAFE")
        draw.ellipse((135, 145, 220, 220), fill="#FFFFFF", outline="#94A3B8", width=4)
    elif any(key in lower for key in ("paint", "art")):
        draw.rounded_rectangle(
            (145, 120, 365, 260), radius=20, fill="#FEF3C7", outline="#D97706", width=5
        )
        for color, x in [("#EF4444", 185), ("#3B82F6", 245), ("#22C55E", 305)]:
            draw.ellipse((x, 165, x + 42, 207), fill=color)
        draw.line((180, 290, 350, 120), fill="#92400E", width=12)
    elif any(key in lower for key in ("seed", "east", "cream")):
        if "cream" in lower:
            draw.polygon([(190, 230), (322, 230), (256, 365)], fill="#FCD34D", outline="#92400E")
            draw.ellipse((170, 118, 342, 258), fill="#FBCFE8", outline="#BE185D", width=5)
        elif "east" in lower:
            from PIL import ImageFont

            draw.ellipse((140, 105, 372, 337), fill="#FFFFFF", outline="#475569", width=5)
            draw.polygon([(256, 135), (286, 225), (256, 205), (226, 225)], fill="#EF4444")
            draw.text((333, 210), "E", fill="#1F2937", font=_load_font(ImageFont, 48, bold=True))
        else:
            draw.ellipse((220, 110, 292, 230), fill="#FDE68A", outline="#92400E", width=5)
            draw.line((256, 230, 256, 290), fill="#16A34A", width=8)
            draw.ellipse((260, 240, 335, 280), fill="#86EFAC", outline="#16A34A", width=4)
    elif any(key in lower for key in ("meet", "team")):
        for x, color in [(185, "#BFDBFE"), (285, "#FDE68A")]:
            draw.ellipse((x, 120, x + 70, 190), fill=color, outline="#1F2937", width=4)
            draw.rounded_rectangle(
                (x - 20, 195, x + 90, 310), radius=24, fill=color, outline="#1F2937", width=4
            )
        draw.line((250, 245, 290, 245), fill="#16A34A", width=10)
    elif any(key in lower for key in ("coat", "tie")):
        draw.polygon(
            [(210, 110), (300, 110), (345, 280), (165, 280)], fill="#93C5FD", outline="#1D4ED8"
        )
        draw.polygon(
            [(245, 128), (267, 128), (282, 245), (256, 280), (230, 245)],
            fill="#EF4444",
            outline="#991B1B",
        )
    elif any(key in lower for key in ("load", "hold")):
        for i, (x, y) in enumerate([(150, 135), (240, 135), (195, 220)]):
            draw.rounded_rectangle(
                (x, y, x + 105, y + 90), radius=12, fill="#FCD34D", outline="#92400E", width=5
            )
            draw.line((x, y + 28, x + 105, y + 28), fill="#92400E", width=3)
    elif "sharp" in lower:
        draw.polygon(
            [(150, 280), (345, 85), (395, 135), (200, 330)], fill="#FDE68A", outline="#92400E"
        )
        draw.polygon([(345, 85), (420, 55), (395, 135)], fill="#1F2937")
    elif any(key in lower for key in ("pie", "slice")):
        draw.pieslice((135, 100, 375, 340), 20, 330, fill="#FCD34D", outline="#92400E", width=5)
        draw.pieslice((185, 145, 325, 285), 20, 330, fill="#F97316")
    elif any(key in lower for key in ("target", "right")):
        for r, color in [(125, "#FEE2E2"), (92, "#EF4444"), (60, "#FFFFFF"), (28, "#1D4ED8")]:
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline="#1F2937", width=3)
    else:
        draw.rounded_rectangle(
            (150, 105, 362, 275), radius=28, fill="#E0E7FF", outline="#6366F1", width=5
        )
        draw.ellipse((198, 142, 238, 182), fill="#FFFFFF")
        draw.ellipse((274, 142, 314, 182), fill="#FFFFFF")
        draw.arc((205, 190, 307, 250), 15, 165, fill="#1F2937", width=6)


def _phonics_focus(word: str) -> str:
    for pattern in (
        "igh",
        "ai",
        "ay",
        "ee",
        "ea",
        "ey",
        "oa",
        "ow",
        "oe",
        "ie",
        "ore",
        "ar",
        "or",
        "er",
        "ir",
        "ur",
    ):
        if pattern in word.lower():
            return pattern
    return ""


def _shape_label(prompt: str) -> str:
    match = re.search(r"representing ([A-Za-z]+)", prompt)
    if match:
        return match.group(1)[:8]
    return "cue"


def _scene_title(pose: str) -> str:
    labels = {
        "pointing": "Picture Match",
        "writing": "Word Builder",
        "thinking": "Pattern Hunt",
        "building": "Word Builder",
        "reading": "Story Read",
        "listening": "Sound Check",
    }
    return labels.get(pose, "Skill Quest")


def compute_worksheet_hash(
    source_hash: str,
    worksheet_number: int,
    theme_id: str,
) -> str:
    """Compute a deterministic hash for caching worksheet assets."""
    data = f"{source_hash}:{worksheet_number}:{theme_id}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]
