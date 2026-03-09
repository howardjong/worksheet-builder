"""Generate character variant images using Gemini character-consistent image generation.

Instead of generating separate overlay PNGs, this module generates complete character
images with items integrated naturally by passing the base character as a reference
image to Gemini 3.1 Flash Image (Nano Banana 2).

An AI judge validates each generated image for character consistency and quality,
retrying up to MAX_JUDGE_RETRIES times if the result is poor.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
from typing import Any

from PIL import Image

from companion.catalog import CATALOG

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_BASE_PATH = _ASSETS_DIR / "characters" / "rainbow_roblox.png"
_VARIANTS_DIR = _ASSETS_DIR / "variants"

# Gemini model for character-consistent image generation
_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

# Judge models (Gemini primary, GPT fallback)
_JUDGE_MODEL_GEMINI = "gemini-3.1-flash-lite-preview"
_JUDGE_MODEL_OPENAI = "gpt-5.4"

MAX_JUDGE_RETRIES = 5

# Base character description for consistency prompting
_CHARACTER_DESC = (
    "a cute blocky Roblox-style character with rainbow-colored spiky hair "
    "(red, orange, yellow, green, blue, purple), a simple smiling face with "
    "dot eyes and a curved mouth, a peach/skin-colored square head and hands, "
    "a blue t-shirt with a yellow lightning bolt, brown pants, and orange sneakers. "
    "The character has a boxy body with outstretched arms in a T-pose."
)

# Item descriptions for prompting
_ITEM_DESCRIPTIONS: dict[str, str] = {
    "white_sneakers": "wearing white sneakers instead of orange sneakers",
    "red_hoodie": (
        "wearing a bright red hoodie sweatshirt "
        "instead of the blue lightning bolt t-shirt"
    ),
    "blue_jeans": "wearing blue denim jeans instead of brown pants",
    "green_backpack": "wearing a small green backpack on his back",
    "star_shades": "wearing fun star-shaped yellow sunglasses on his face",
    "wizard_hat": "wearing a tall purple wizard hat with gold stars on his head",
    "gold_crown": "wearing a shiny golden crown with jewels on his head",
}


def _build_variant_prompt(equipped_items: dict[str, str]) -> str:
    """Build a prompt to regenerate the character with equipped items."""
    if not equipped_items:
        return (
            f"Generate an image of {_CHARACTER_DESC} "
            f"White background. Cartoon style, clean lines, bright colors. "
            f"Full body, centered, same pose as the reference image."
        )

    item_changes: list[str] = []
    for slot, item_id in equipped_items.items():
        desc = _ITEM_DESCRIPTIONS.get(item_id)
        if desc:
            item_changes.append(desc)

    changes_text = ", and ".join(item_changes)

    return (
        f"Generate an image of exactly this same Roblox character from the reference image, "
        f"but {changes_text}. "
        f"Keep the character's rainbow spiky hair, square blocky body shape, simple smiling "
        f"face, T-pose, and cartoon Roblox style exactly the same as the reference. "
        f"Only change the specific items mentioned. "
        f"White background. Full body, centered. Same proportions and art style."
    )


def _generate_single_variant(
    equipped_items: dict[str, str],
) -> bytes | None:
    """Generate a single character variant image, returning raw PNG bytes."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        with open(_BASE_PATH, "rb") as f:
            ref_bytes = f.read()

        prompt = _build_variant_prompt(equipped_items)

        contents = [
            types.Part(text=prompt),
            types.Part(
                inline_data=types.Blob(mime_type="image/png", data=ref_bytes),
            ),
        ]

        response = client.models.generate_content(
            model=_IMAGE_MODEL,
            contents=contents,  # type: ignore[arg-type]
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:  # type: ignore[index,union-attr]
            if part.inline_data:
                return part.inline_data.data

        logger.warning("Gemini returned no image in response")
        return None

    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None


def _build_judge_prompt(equipped_items: dict[str, str]) -> str:
    """Build the prompt for the AI judge."""
    item_changes: list[str] = []
    for slot, item_id in equipped_items.items():
        desc = _ITEM_DESCRIPTIONS.get(item_id, item_id)
        item_changes.append(desc)
    changes_text = ", and ".join(item_changes) if item_changes else "no changes"

    return (
        "You are a quality judge for character-consistent image generation. "
        "You are given two images:\n"
        "1. The REFERENCE image (original character)\n"
        "2. The GENERATED image (character with modifications)\n\n"
        f"The generated image should show the same Roblox character but {changes_text}.\n\n"
        "Judge the generated image on these criteria:\n"
        "- CHARACTER CONSISTENCY: Does it look like the same character? Same rainbow hair, "
        "blocky Roblox body, square head, simple face, T-pose?\n"
        "- ITEM ACCURACY: Are the requested items visible and correctly placed?\n"
        "- ART STYLE: Does it match the cartoon Roblox style of the reference?\n"
        "- IMAGE QUALITY: Clean lines, no artifacts, no distortion, no screen effects?\n"
        "- BACKGROUND: Is the background clean white (no patterns, gradients, or noise)?\n\n"
        "Respond with ONLY JSON (no markdown fences):\n"
        '{"passed": true/false, "score": 1-10, "issues": ["issue1", "issue2"]}\n'
        "Score 7+ means acceptable. Be strict about character consistency and clean output."
    )


def _judge_with_gemini(
    ref_bytes: bytes, generated_bytes: bytes, equipped_items: dict[str, str]
) -> dict[str, Any] | None:
    """Judge using Gemini 3.1 Flash Lite."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = _build_judge_prompt(equipped_items)

        contents = [
            types.Part(text=prompt),
            types.Part(
                inline_data=types.Blob(mime_type="image/png", data=ref_bytes),
            ),
            types.Part(
                inline_data=types.Blob(mime_type="image/png", data=generated_bytes),
            ),
        ]

        response = client.models.generate_content(
            model=_JUDGE_MODEL_GEMINI,
            contents=contents,  # type: ignore[arg-type]
        )

        text = response.text or ""
        text = _extract_json(text)
        result: dict[str, Any] = json.loads(text)
        return result

    except Exception as e:
        logger.warning(f"Gemini judge failed: {e}")
        return None


def _judge_with_openai(
    ref_bytes: bytes, generated_bytes: bytes, equipped_items: dict[str, str]
) -> dict[str, Any] | None:
    """Judge using OpenAI GPT-5.4 as fallback."""
    import base64

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        prompt = _build_judge_prompt(equipped_items)

        ref_b64 = base64.b64encode(ref_bytes).decode("utf-8")
        gen_b64 = base64.b64encode(generated_bytes).decode("utf-8")

        response = client.chat.completions.create(
            model=_JUDGE_MODEL_OPENAI,
            max_completion_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{ref_b64}",
                            },
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{gen_b64}",
                            },
                        },
                    ],
                }
            ],
        )

        text = response.choices[0].message.content or ""
        text = _extract_json(text)
        result: dict[str, Any] = json.loads(text)
        return result

    except Exception as e:
        logger.warning(f"OpenAI judge failed: {e}")
        return None


def _judge_variant(
    ref_bytes: bytes, generated_bytes: bytes, equipped_items: dict[str, str]
) -> dict[str, Any]:
    """Judge a generated variant, trying Gemini first, then OpenAI.

    Returns a dict with "passed", "score", and "issues" keys.
    Falls back to auto-pass if both judges fail.
    """
    result = _judge_with_gemini(ref_bytes, generated_bytes, equipped_items)
    if result and "passed" in result:
        logger.info(f"  Judge (Gemini): score={result.get('score')}, passed={result['passed']}")
        return result

    result = _judge_with_openai(ref_bytes, generated_bytes, equipped_items)
    if result and "passed" in result:
        logger.info(f"  Judge (OpenAI): score={result.get('score')}, passed={result['passed']}")
        return result

    logger.warning("  Both judges unavailable — auto-passing")
    return {"passed": True, "score": 0, "issues": ["no judge available"]}


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            if line.strip() == "```" and in_block:
                break
            if in_block:
                json_lines.append(line)
        return "\n".join(json_lines)
    return text


def generate_variant(
    equipped_items: dict[str, str],
    output_path: Path,
) -> Path | None:
    """Generate a character variant with AI judge validation loop.

    Generates the character image, then runs an AI judge to check consistency
    and quality. Retries up to MAX_JUDGE_RETRIES times if the judge rejects it.

    Returns the output path on success, None on failure.
    """
    if not _BASE_PATH.exists():
        logger.error(f"Base character not found: {_BASE_PATH}")
        return None

    with open(_BASE_PATH, "rb") as f:
        ref_bytes = f.read()

    best_result: tuple[int, bytes] | None = None  # (score, image_bytes)

    for attempt in range(1, MAX_JUDGE_RETRIES + 1):
        logger.info(f"Generating character variant (attempt {attempt}/{MAX_JUDGE_RETRIES})...")

        generated_bytes = _generate_single_variant(equipped_items)
        if generated_bytes is None:
            logger.error(f"  Generation failed on attempt {attempt}")
            continue

        # Judge the result
        verdict = _judge_variant(ref_bytes, generated_bytes, equipped_items)
        score = int(verdict.get("score", 0))

        # Track best result so far
        if best_result is None or score > best_result[0]:
            best_result = (score, generated_bytes)

        if verdict.get("passed", False):
            logger.info(f"  Accepted on attempt {attempt} (score: {score})")
            return _save_variant(generated_bytes, output_path)

        issues = verdict.get("issues", [])
        logger.info(f"  Rejected (score: {score}): {issues}")

    # All attempts exhausted — use the best one we got
    if best_result is not None:
        logger.warning(
            f"All {MAX_JUDGE_RETRIES} attempts judged below threshold. "
            f"Using best result (score: {best_result[0]})."
        )
        return _save_variant(best_result[1], output_path)

    logger.error("All generation attempts failed.")
    return None


def _save_variant(image_bytes: bytes, output_path: Path) -> Path:
    """Post-process and save a variant image."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    img = _remove_white_background(img)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")
    logger.info(f"Saved character variant: {output_path}")
    return output_path


def _remove_white_background(img: Image.Image, threshold: int = 230) -> Image.Image:
    """Replace near-white pixels with transparency."""
    data = img.getdata()
    new_data = []
    for pixel in data:
        r, g, b = pixel[0], pixel[1], pixel[2]
        if r > threshold and g > threshold and b > threshold:
            new_data.append((r, g, b, 0))
        else:
            a = pixel[3] if len(pixel) > 3 else 255
            new_data.append((r, g, b, a))
    img.putdata(new_data)  # type: ignore[arg-type]
    return img


def generate_all_items() -> dict[str, Path | None]:
    """Generate a character variant for each individual catalog item.

    Useful for previewing what each item looks like on the character.
    Returns a dict of item_id -> output path (None if generation failed).
    """
    results: dict[str, Path | None] = {}
    for item in CATALOG:
        output_path = _VARIANTS_DIR / f"{item.item_id}.png"
        equipped = {item.slot: item.item_id}
        results[item.item_id] = generate_variant(equipped, output_path)
    return results
