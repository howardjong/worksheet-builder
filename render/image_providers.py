"""Image generation provider adapters with a configurable fallback chain.

Adding a provider (e.g., Seedream via fal.ai/Replicate/ARK) is one adapter
class plus one registry entry in resolve_provider_chain(). Everything
upstream (prompt) and downstream (gates, PDF wrap) is provider-agnostic.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from ai import openrouter

logger = logging.getLogger(__name__)

# Owner decision 2026-06-12 (D29): OpenAI first, then Gemini. Across all live
# runs gpt-image-2 rescued text-dense pages 4-for-4 on attempt 1 while gemini
# third attempts recovered 0-for-4. The Gemini fallback is upgraded to the pro
# image model.
GEMINI_IMAGE_MODEL = "gemini-3-pro-image"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2-2026-04-21"
DEFAULT_PROVIDER_ORDER = "openrouter"


class OpenRouterImageProvider:
    """One explicit model in the quality-gated OpenRouter image chain."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.provider_id = "openrouter_" + model_id.replace("/", "_")

    def available(self) -> bool:
        return openrouter.available()

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        return openrouter.generate_image(prompt, reference_png, model=self.model_id)


class ImageProvider(Protocol):
    """A single image-generation backend."""

    provider_id: str
    model_id: str

    def available(self) -> bool:
        """Whether this provider has credentials configured."""

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        """Generate one page image. Returns PNG bytes or None on failure."""


class GeminiImageProvider(OpenRouterImageProvider):
    """Legacy name for a Google image model hosted through OpenRouter."""

    def __init__(self) -> None:
        model = os.environ.get("WORKSHEET_GEMINI_IMAGE_MODEL", GEMINI_IMAGE_MODEL)
        super().__init__(model if "/" in model else "google/" + model)


class OpenAIImageProvider(OpenRouterImageProvider):
    """Legacy name for an OpenAI image model hosted through OpenRouter."""

    def __init__(self) -> None:
        model = os.environ.get(
            "WORKSHEET_OPENAI_IMAGE_MODEL", openrouter.DEFAULT_MODELS["image"][0]
        )
        super().__init__(model if "/" in model else "openai/" + model)


def resolve_provider_chain() -> list[ImageProvider]:
    """Resolve the configured provider fallback chain, available providers only.

    Order comes from WORKSHEET_IMAGE_PROVIDERS (comma-separated), default
    "openrouter". Each configured OpenRouter image model becomes one entry.
    Legacy provider names are OpenRouter model aliases. Unknown names are ignored.
    """
    order = os.environ.get("WORKSHEET_IMAGE_PROVIDERS", DEFAULT_PROVIDER_ORDER)
    registry: dict[str, ImageProvider] = {
        "gemini": GeminiImageProvider(),
        "openai": OpenAIImageProvider(),
    }
    chain: list[ImageProvider] = []
    for name in order.split(","):
        if name.strip().lower() == "openrouter":
            chain.extend(
                OpenRouterImageProvider(model)
                for model in openrouter.models("image")
                if openrouter.available()
            )
            continue
        provider = registry.get(name.strip().lower())
        if provider is not None and provider.available():
            chain.append(provider)
    return chain
