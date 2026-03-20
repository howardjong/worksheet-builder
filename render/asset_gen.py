"""AI scene generation with caching — generates character scenes and word pictures.

Uses Gemini Flash Image for generation with the learner's base character as a
reference image for consistency. Falls back gracefully when no API key is available.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from companion.schema import CharacterStyleSheet
from render.pose_planner import ScenePlan
from theme.schema import AssetManifest, CharacterSpec

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "cache"
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

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

    cache_dir = _CACHE_DIR / f"worksheet_{worksheet_hash}"

    # Check if all assets already cached
    manifest = _check_cache(cache_dir, scene_plans, word_picture_prompts)
    if manifest is not None:
        logger.info(f"  Asset cache hit: {cache_dir}")
        return manifest

    if not _has_api_key():
        logger.info("  No AI API key -- skipping asset generation")
        return None

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

        result = _generate_scene(
            plan.scene_prompt,
            str(scene_file),
            extra_ref_bytes or ref_bytes,
            style_sheet=style_sheet,
            character_spec=character_spec,
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

        result = _generate_word_picture(prompt, str(word_file))
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
    return bool(
        os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    )


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

        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
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
                        mime_type="image/png", data=ref_bytes,
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

        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
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
) -> str | None:
    """Generate an AI cover image for a lesson package.

    Returns path to cached PNG or None if generation is unavailable.
    """
    if os.environ.get("WORKSHEET_SKIP_ASSET_GEN"):
        return None

    cache_dir = _CACHE_DIR / f"worksheet_{worksheet_hash}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cover_file = cache_dir / "cover.png"

    if cover_file.exists():
        logger.info(f"  Cover image cache hit: {cover_file}")
        return str(cover_file)

    if not _has_api_key():
        logger.info("  No AI API key -- skipping cover image generation")
        return None

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

    return _generate_word_picture(prompt, str(cover_file))


def compute_worksheet_hash(
    source_hash: str,
    worksheet_number: int,
    theme_id: str,
) -> str:
    """Compute a deterministic hash for caching worksheet assets."""
    data = f"{source_hash}:{worksheet_number}:{theme_id}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]
