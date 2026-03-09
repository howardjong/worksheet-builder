"""AI scene generation with caching — generates character scenes and word pictures.

Uses Gemini Flash for image generation with a reference character + judge loop.
Falls back gracefully when no API key is available.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from render.pose_planner import ScenePlan
from theme.schema import AssetManifest

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "cache"


def generate_worksheet_assets(
    scene_plans: list[ScenePlan],
    word_picture_prompts: dict[str, str],
    worksheet_hash: str,
) -> AssetManifest | None:
    """Generate all assets for a worksheet: scenes + word pictures.

    Returns an AssetManifest with paths to generated images,
    or None if generation is unavailable (no API key).

    Uses content-hash-based caching — second run with same content
    hits cache with no API calls.
    """
    cache_dir = _CACHE_DIR / f"worksheet_{worksheet_hash}"

    # Check if all assets already cached
    manifest = _check_cache(cache_dir, scene_plans, word_picture_prompts)
    if manifest is not None:
        logger.info(f"  Asset cache hit: {cache_dir}")
        return manifest

    # Try to generate via AI
    if not _has_api_key():
        logger.info("  No AI API key available — skipping asset generation")
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)

    scene_paths: dict[int, str] = {}
    word_paths: dict[str, str] = {}

    # Generate scene images
    for plan in scene_plans:
        scene_file = cache_dir / f"scene_{plan.chunk_id}.png"
        if scene_file.exists():
            scene_paths[plan.chunk_id] = str(scene_file)
            continue

        result = _generate_image(plan.scene_prompt, str(scene_file))
        if result:
            scene_paths[plan.chunk_id] = result

    # Generate word picture images
    for word, prompt in word_picture_prompts.items():
        safe_name = word.lower().replace(" ", "_")
        word_file = cache_dir / f"word_{safe_name}.png"
        if word_file.exists():
            word_paths[word] = str(word_file)
            continue

        result = _generate_image(prompt, str(word_file))
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
    import os
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def _generate_image(prompt: str, output_path: str) -> str | None:
    """Generate a single image using Gemini Flash.

    Returns the output path on success, None on failure.
    """
    try:
        import os

        import google.generativeai as genai

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return None

        genai.configure(api_key=api_key)  # type: ignore[attr-defined]
        model = genai.GenerativeModel("gemini-2.0-flash-exp")  # type: ignore[attr-defined]

        response = model.generate_content(
            [prompt],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="image/png",
            ),
        )

        if response.parts:
            for part in response.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    image_data = part.inline_data.data
                    Path(output_path).write_bytes(image_data)
                    logger.info(f"  Generated: {output_path}")
                    return output_path

        logger.warning(f"  No image data in response for: {output_path}")
        return None

    except ImportError:
        logger.info("  google-generativeai not installed — skipping image generation")
        return None
    except Exception as e:
        logger.warning(f"  Image generation failed: {e}")
        return None


def compute_worksheet_hash(
    source_hash: str,
    worksheet_number: int,
    theme_id: str,
) -> str:
    """Compute a deterministic hash for caching worksheet assets."""
    data = f"{source_hash}:{worksheet_number}:{theme_id}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]
