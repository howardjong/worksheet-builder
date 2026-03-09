"""AI scene generation with caching — generates character scenes and word pictures.

Uses Gemini Flash Image for generation with the learner's base character as a
reference image for consistency. Falls back gracefully when no API key is available.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from render.pose_planner import ScenePlan
from theme.schema import AssetManifest

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "cache"
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

# Base character description for consistency
_CHARACTER_DESC = (
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
) -> AssetManifest | None:
    """Generate all assets for a worksheet: scenes + word pictures.

    Returns an AssetManifest with paths to generated images,
    or None if generation is unavailable (no API key).

    Uses content-hash-based caching -- second run with same content
    hits cache with no API calls.
    """
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

    # Generate scene images
    for plan in scene_plans:
        scene_file = cache_dir / f"scene_{plan.chunk_id}.png"
        if scene_file.exists():
            scene_paths[plan.chunk_id] = str(scene_file)
            continue

        result = _generate_scene(
            plan.scene_prompt, str(scene_file), ref_bytes,
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
) -> str | None:
    """Generate a character scene image using Gemini with reference character.

    Passes the base character as a reference image so the generated scene
    features the same character in a pose related to the activity.
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

        full_prompt = (
            f"Generate an image of {_CHARACTER_DESC}, "
            f"{prompt} "
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
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:
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
            contents=[types.Part(text=prompt)],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:
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


def compute_worksheet_hash(
    source_hash: str,
    worksheet_number: int,
    theme_id: str,
) -> str:
    """Compute a deterministic hash for caching worksheet assets."""
    data = f"{source_hash}:{worksheet_number}:{theme_id}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]
