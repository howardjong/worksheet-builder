"""Avatar composition — layered character rendering from profile + equipped items."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PIL import Image, ImageEnhance

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

# Z-order for layering equipped items
Z_ORDER = ["body", "clothing", "accessories", "hats", "expressions"]


def compose_avatar(
    profile: LearnerProfile,
    size: str = "companion",
    theme_id: str = "space",
) -> Path | None:
    """Compose an avatar image from profile's base character and equipped items.

    Loads the base character, applies color tinting, layers equipped items,
    resizes to the requested size, and caches the result.

    Returns path to the composed avatar PNG, or None if base character not found.
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

    # Load base character
    img = Image.open(base_path).convert("RGBA")

    # Remove white background (make it transparent)
    img = _remove_white_background(img)

    # Apply color tinting from profile
    if profile.avatar.base_colors:
        primary = profile.avatar.base_colors.get("primary", "#4A90D9")
        img = _apply_color_tint(img, primary)

    # Crop to content (remove excess transparent space)
    img = _crop_to_content(img)

    # Resize to target size
    target = SIZES.get(size, SIZES["companion"])
    img = _resize_contain(img, target)

    # Save to cache
    img.save(str(cached_path), "PNG")
    logger.info(f"Composed avatar: {cached_path} ({target[0]}x{target[1]})")

    return cached_path


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
    img.putdata(new_data)
    return img


def _apply_color_tint(img: Image.Image, hex_color: str) -> Image.Image:
    """Apply a subtle color tint to the character.

    Shifts hue toward the target color while preserving the character's details.
    Only tints non-transparent, non-dark pixels.
    """
    r_t = int(hex_color[1:3], 16)
    g_t = int(hex_color[3:5], 16)
    b_t = int(hex_color[5:7], 16)

    # Subtle tint — blend 15% toward target color
    blend = 0.15
    data = img.getdata()
    new_data = []
    for pixel in data:
        r, g, b, a = pixel
        if a < 50:  # Skip transparent
            new_data.append(pixel)
            continue
        # Only tint mid-tone pixels (not very dark or very light)
        brightness = (r + g + b) / 3
        if 30 < brightness < 220:
            r = int(r * (1 - blend) + r_t * blend)
            g = int(g * (1 - blend) + g_t * blend)
            b = int(b * (1 - blend) + b_t * blend)
        new_data.append((r, g, b, a))
    img.putdata(new_data)
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
    parts = [
        profile.avatar.base_character if profile.avatar else "none",
        str(profile.avatar.base_colors) if profile.avatar else "",
        ",".join(profile.avatar.equipped_items) if profile.avatar else "",
        size,
        theme_id,
    ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:12]
