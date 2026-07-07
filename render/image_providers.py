"""Image generation provider adapters with a configurable fallback chain.

Adding a provider (e.g., Seedream via fal.ai/Replicate/ARK) is one adapter
class plus one registry entry in resolve_provider_chain(). Everything
upstream (prompt) and downstream (gates, PDF wrap) is provider-agnostic.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)

# Owner decision 2026-06-12 (D29): OpenAI first, then Gemini. Across all live
# runs gpt-image-2 rescued text-dense pages 4-for-4 on attempt 1 while gemini
# third attempts recovered 0-for-4. The Gemini fallback is upgraded to the pro
# image model.
GEMINI_IMAGE_MODEL = "gemini-3-pro-image"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2-2026-04-21"
DEFAULT_PROVIDER_ORDER = "openai,gemini"


class ImageProvider(Protocol):
    """A single image-generation backend."""

    provider_id: str
    model_id: str

    def available(self) -> bool:
        """Whether this provider has credentials configured."""

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        """Generate one page image. Returns PNG bytes or None on failure."""


class GeminiImageProvider:
    """Gemini image generation (same pattern as render/asset_gen._generate_scene)."""

    provider_id = "gemini"

    def __init__(self) -> None:
        self.model_id = os.environ.get("WORKSHEET_GEMINI_IMAGE_MODEL", GEMINI_IMAGE_MODEL)

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            contents: list[types.Part] = [types.Part(text=prompt)]
            if reference_png:
                contents.append(
                    types.Part(
                        inline_data=types.Blob(mime_type="image/png", data=reference_png),
                    ),
                )
            response = client.models.generate_content(
                model=self.model_id,
                contents=contents,  # type: ignore[arg-type]
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
            for part in response.candidates[0].content.parts:  # type: ignore[index,union-attr]
                if part.inline_data and part.inline_data.data:
                    return bytes(part.inline_data.data)
            logger.warning("Gemini image response contained no image part")
            return None
        except Exception as exc:
            logger.warning("Gemini image generation failed: %s", exc)
            return None


class OpenAIImageProvider:
    """OpenAI gpt-image generation with reference conditioning via images.edit.

    Note: gpt-image models return b64_json by default and reject the
    response_format param (see gotcha G8 in the project context doc).
    """

    provider_id = "openai"

    def __init__(self) -> None:
        self.model_id = os.environ.get("WORKSHEET_OPENAI_IMAGE_MODEL", DEFAULT_OPENAI_IMAGE_MODEL)

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            if reference_png:
                result = client.images.edit(
                    model=self.model_id,
                    image=[("reference.png", io.BytesIO(reference_png), "image/png")],
                    prompt=prompt,
                    size="1024x1536",
                )
            else:
                result = client.images.generate(
                    model=self.model_id,
                    prompt=prompt,
                    size="1024x1536",
                )
            b64 = result.data[0].b64_json if result.data else None
            if not b64:
                logger.warning("OpenAI image response contained no b64_json payload")
                return None
            return base64.b64decode(b64)
        except Exception as exc:
            logger.warning("OpenAI image generation failed: %s", exc)
            return None


def resolve_provider_chain() -> list[ImageProvider]:
    """Resolve the configured provider fallback chain, available providers only.

    Order comes from WORKSHEET_IMAGE_PROVIDERS (comma-separated), default
    "openai,gemini" (see DEFAULT_PROVIDER_ORDER / decision D29). Unknown names
    are ignored.
    """
    order = os.environ.get("WORKSHEET_IMAGE_PROVIDERS", DEFAULT_PROVIDER_ORDER)
    registry: dict[str, ImageProvider] = {
        "gemini": GeminiImageProvider(),
        "openai": OpenAIImageProvider(),
    }
    chain: list[ImageProvider] = []
    for name in order.split(","):
        provider = registry.get(name.strip().lower())
        if provider is not None and provider.available():
            chain.append(provider)
    return chain
