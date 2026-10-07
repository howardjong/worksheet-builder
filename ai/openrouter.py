"""OpenRouter text, vision, and reference-image transport.

Models are explicit; OpenRouter may fail over between hosting endpoints, while
the worksheet renderer owns retries for pages that fail its quality gates.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from PIL import Image

logger = logging.getLogger(__name__)
Role = Literal["text", "vision", "image", "research", "audio"]
DEFAULT_MODELS: dict[Role, tuple[str, ...]] = {
    "audio": ("google/gemini-3-flash-preview", "google/gemini-2.5-flash"),
    "research": ("perplexity/sonar-pro", "perplexity/sonar"),
    "text": ("openai/gpt-5.5", "anthropic/claude-sonnet-4.6", "google/gemini-3.1-pro-preview"),
    "vision": ("openai/gpt-5.5", "google/gemini-3.1-pro-preview", "anthropic/claude-sonnet-4.6"),
    "image": (
        "openai/gpt-image-2.5-sunburst",
        "google/gemini-3-pro-image",
        "bytedance-seed/seedream-5-0-pro",
        "google/gemini-3.1-flash-image",
    ),
}
_RETRYABLE = {408, 429, 500, 502, 503, 504}
_AUTH_FAILURES = {401, 402}


class CredentialsUnavailableError(RuntimeError):
    """Authentication or credit failure shared by every OpenRouter image model."""


@dataclass(frozen=True)
class Completion:
    text: str
    model: str


def available() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def enabled() -> bool:
    """OpenRouter is the only inference transport; no vendor bypass exists."""
    return available()


def models(role: Role) -> list[str]:
    value = os.environ.get(f"WORKSHEET_OPENROUTER_{role.upper()}_MODELS")
    names = DEFAULT_MODELS[role] if value is None else value.split(",")
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))


def image_url(data: bytes) -> str:
    # Preserve the actual MIME type for photographed JPEGs and PNG references.
    with Image.open(io.BytesIO(data)) as image:
        mime = Image.MIME.get(image.format or "", "image/png")
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
        return value if 0 < value <= 600 else default
    except ValueError:
        return default


def _request(endpoint: str, payload: dict[str, Any]) -> Mapping[str, Any] | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "X-Title": "Worksheet Builder"}
    timeout = _positive_float("WORKSHEET_OPENROUTER_TIMEOUT", 180)
    # One bounded retry for transient transport/hosting failure. Bad credentials
    # and exhausted credit are not solved by replaying the same request.
    for attempt in range(2):
        try:
            response = httpx.post(base + endpoint, json=payload, headers=headers, timeout=timeout)
            if response.status_code in _RETRYABLE and attempt == 0:
                try:
                    delay = min(5.0, max(0.0, float(response.headers.get("Retry-After", "1"))))
                except ValueError:
                    delay = 1.0
                time.sleep(delay)
                continue
            if response.status_code >= 400:
                logger.warning("OpenRouter %s returned HTTP %s", endpoint, response.status_code)
                return (
                    {"_terminal_auth_error": True}
                    if response.status_code in _AUTH_FAILURES
                    else None
                )
            data: Any = response.json()
            if not isinstance(data, dict) or data.get("error"):
                logger.warning("OpenRouter returned an invalid response or API error")
                return None
            return data
        except (httpx.TransportError, ValueError):
            # Avoid logging response bodies, headers, request payloads, or URLs
            # that may expose a secret or private learner content.
            logger.warning("OpenRouter %s transport/response failure", endpoint)
            if attempt == 0:
                time.sleep(1)
    return None


def complete(
    prompt: str,
    *,
    images: Sequence[bytes] = (),
    audio: Sequence[tuple[bytes, str]] = (),
    role: Role = "text",
    model_ids: Sequence[str] | None = None,
    max_tokens: int = 4096,
    accept: Callable[[str], bool] | None = None,
) -> Completion | None:
    if not available():
        return None
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": image_url(data)}} for data in images)
    content.extend(
        {
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(data).decode("ascii"), "format": format},
        }
        for data, format in audio
    )
    for model in models(role) if model_ids is None else model_ids:
        data = _request(
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": max_tokens,
                "provider": {"allow_fallbacks": True},
            },
        )
        if data and data.get("_terminal_auth_error"):
            break
        try:
            text = data["choices"][0]["message"]["content"] if data else None
            if (
                data is not None
                and isinstance(text, str)
                and text.strip()
                and (accept is None or accept(text))
            ):
                logger.info("OpenRouter %s completion accepted: %s", role, data.get("model", model))
                return Completion(text=text, model=str(data.get("model", model)))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        logger.warning("OpenRouter model %s returned no acceptable completion", model)
    return None


def json_value(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.splitlines()[1:])
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return json.loads(cleaned)


def complete_json(
    prompt: str,
    *,
    images: Sequence[bytes] = (),
    audio: Sequence[tuple[bytes, str]] = (),
    role: Role = "text",
    model_ids: Sequence[str] | None = None,
    max_tokens: int = 4096,
    validate: Callable[[Mapping[str, Any]], bool] | None = None,
) -> Mapping[str, Any] | None:
    def accepts(text: str) -> bool:
        value = json_value(text)
        return isinstance(value, dict) and (validate is None or validate(value))

    result = complete(
        prompt,
        images=images,
        audio=audio,
        role=role,
        model_ids=model_ids,
        max_tokens=max_tokens,
        accept=accepts,
    )
    value = json_value(result.text) if result else None
    return value if isinstance(value, dict) else None


def generate_image(
    prompt: str,
    reference_png: bytes | None = None,
    *,
    model: str,
    aspect_ratio: str = "3:4",
) -> bytes | None:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": aspect_ratio,
        "provider": {"allow_fallbacks": True},
    }
    if reference_png:
        payload["input_references"] = [
            {
                "type": "image_url",
                "image_url": {"url": image_url(reference_png)},
            }
        ]
    data = _request("/images", payload)
    if data and data.get("_terminal_auth_error"):
        raise CredentialsUnavailableError("OpenRouter credentials or credit unavailable")
    try:
        encoded = data["data"][0]["b64_json"] if data else None
        if not isinstance(encoded, str):
            return None
        raw = base64.b64decode(encoded, validate=True)
        # Normalize actual raster content to PNG. Truncated data, SVGs, and
        # base64 text pretending to be an image never enter the page cache.
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            return buffer.getvalue()
    except (KeyError, IndexError, TypeError, ValueError, OSError):
        logger.warning("OpenRouter model %s returned no usable image", model)
        return None


def generate_with_fallbacks(
    prompt: str,
    reference_png: bytes | None = None,
    *,
    aspect_ratio: str = "3:4",
) -> bytes | None:
    for model in models("image"):
        try:
            result = generate_image(prompt, reference_png, model=model, aspect_ratio=aspect_ratio)
        except CredentialsUnavailableError:
            return None
        if result:
            return result
    return None
