"""Avatar composition — character variant rendering via AI image generation.

Instead of layering flat overlay PNGs, this module generates complete character
images with equipped items naturally integrated using Gemini's character-consistent
image generation (passing the base character as a reference image).

Results are cached by equipment combination so the API is only called once per
unique loadout.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PIL import Image

from companion.schema import LearnerProfile

logger = logging.getLogger(__name__)

# Asset directories
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_CHARACTERS_DIR = _ASSETS_DIR / "characters"
_CACHE_DIR = _ASSETS_DIR / "cache"

# Render sizes
SIZES = {
    "companion": (150, 150),  # On-worksheet buddy
    "profile": (400, 400),  # Profile view
    "icon": (64, 64),  # Small icon
}


def compose_avatar(
    profile: LearnerProfile,
    size: str = "companion",
    theme_id: str = "space",
) -> Path | None:
    """Compose an avatar image for the profile's current equipment.

    If no items are equipped, uses the base character directly.
    If items are equipped, generates a character variant via Gemini AI
    with the items naturally integrated (cached per equipment combo).

    Returns path to the avatar PNG, or None if generation fails.
    """
    if not profile.avatar:
        return None

    base_char = profile.avatar.base_character
    base_path = _CHARACTERS_DIR / f"{base_char}.png"

    if not base_path.exists():
        logger.warning(f"Base character not found: {base_path}")
        return None

    # Check cache
    cache_key = _cache_key(profile, size, theme_id)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = _CACHE_DIR / f"avatar_{cache_key}.png"

    if cached_path.exists():
        return cached_path

    equipped = profile.avatar.equipped_items

    if equipped:
        # Generate a new character variant with items via AI
        variant_path = _get_or_generate_variant(equipped)
        if variant_path and variant_path.exists():
            img = Image.open(variant_path).convert("RGBA")
        else:
            # Fall back to base character if generation fails
            logger.warning("Variant generation failed, using base character")
            img = Image.open(base_path).convert("RGBA")
            img = _remove_white_background(img)
    else:
        # No items equipped — use base character
        img = Image.open(base_path).convert("RGBA")
        img = _remove_white_background(img)

    # Crop to content (remove excess transparent space)
    img = _crop_to_content(img)

    # Resize to target size
    target = SIZES.get(size, SIZES["companion"])
    img = _resize_contain(img, target)

    # Save to cache
    img.save(str(cached_path), "PNG")
    logger.info(f"Composed avatar: {cached_path} ({target[0]}x{target[1]})")

    return cached_path


def _get_or_generate_variant(equipped: dict[str, str]) -> Path | None:
    """Get a cached variant or generate a new one via AI."""
    from companion.generate_overlays import generate_variant

    # Cache variant by equipment combo
    variants_dir = _ASSETS_DIR / "variants"
    variant_key = _equipment_hash(equipped)
    variant_path = variants_dir / f"variant_{variant_key}.png"

    if variant_path.exists():
        return variant_path

    return generate_variant(equipped, variant_path)


def _equipment_hash(equipped: dict[str, str]) -> str:
    """Hash the equipped items dict for use as a cache key."""
    items_str = ",".join(f"{k}={v}" for k, v in sorted(equipped.items()))
    return hashlib.sha256(items_str.encode()).hexdigest()[:12]


def _remove_white_background(img: Image.Image, threshold: int = 230) -> Image.Image:
    """Replace near-white pixels with transparency."""
    data = img.getdata()
    new_data = []
    for pixel in data:
        r, g, b = pixel[0], pixel[1], pixel[2]
        if r > threshold and g > threshold and b > threshold:
            new_data.append((r, g, b, 0))  # Transparent
        else:
            a = pixel[3] if len(pixel) > 3 else 255
            new_data.append((r, g, b, a))
    img.putdata(new_data)  # type: ignore[arg-type]
    return img


def _crop_to_content(img: Image.Image) -> Image.Image:
    """Crop image to the bounding box of non-transparent content."""
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def _resize_contain(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Resize image to fit within target size while maintaining aspect ratio.

    Centers the image on a transparent canvas of the target size.
    """
    img.thumbnail(target, Image.LANCZOS)

    # Center on target-sized transparent canvas
    canvas = Image.new("RGBA", target, (0, 0, 0, 0))
    x = (target[0] - img.width) // 2
    y = (target[1] - img.height) // 2
    canvas.paste(img, (x, y), img)

    return canvas


def _cache_key(profile: LearnerProfile, size: str, theme_id: str) -> str:
    """Generate a cache key from profile avatar state."""
    equipped_str = ",".join(
        f"{k}={v}" for k, v in sorted(profile.avatar.equipped_items.items())
    ) if profile.avatar else ""
    parts = [
        profile.avatar.base_character if profile.avatar else "none",
        equipped_str,
        size,
        theme_id,
    ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:12]
