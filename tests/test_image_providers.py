"""Legacy image selectors resolve to ordered OpenRouter models (offline)."""

from __future__ import annotations

import pytest

from render.image_providers import GeminiImageProvider, OpenAIImageProvider, resolve_provider_chain


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("openai,gemini", ["openai/gpt-image-2.5-sunburst", "google/gemini-3-pro-image"]),
        ("gemini,openai", ["google/gemini-3-pro-image", "openai/gpt-image-2.5-sunburst"]),
    ],
)
def test_legacy_provider_order_uses_only_router_credentials(
    monkeypatch: pytest.MonkeyPatch, order: str, expected: list[str]
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("WORKSHEET_IMAGE_PROVIDERS", order)
    assert [provider.model_id for provider in resolve_provider_chain()] == expected


@pytest.mark.parametrize("order", ["openrouter", "openai,gemini"])
def test_no_router_key_disables_chain_even_with_vendor_keys(
    monkeypatch: pytest.MonkeyPatch, order: str
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(key, "legacy-key")
    monkeypatch.setenv("WORKSHEET_IMAGE_PROVIDERS", order)
    assert resolve_provider_chain() == []


@pytest.mark.parametrize(
    ("provider_type", "env_name", "override", "expected"),
    [
        (
            OpenAIImageProvider,
            "WORKSHEET_OPENAI_IMAGE_MODEL",
            "gpt-image-3-future",
            "openai/gpt-image-3-future",
        ),
        (
            GeminiImageProvider,
            "WORKSHEET_GEMINI_IMAGE_MODEL",
            "google/custom-image",
            "google/custom-image",
        ),
    ],
)
def test_legacy_model_override_qualifies_only_unqualified_ids(
    monkeypatch: pytest.MonkeyPatch,
    provider_type: type[OpenAIImageProvider] | type[GeminiImageProvider],
    env_name: str,
    override: str,
    expected: str,
) -> None:
    monkeypatch.setenv(env_name, override)
    assert provider_type().model_id == expected


def test_legacy_model_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKSHEET_OPENAI_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("WORKSHEET_GEMINI_IMAGE_MODEL", raising=False)
    assert OpenAIImageProvider().model_id == "openai/gpt-image-2.5-sunburst"
    assert GeminiImageProvider().model_id == "google/gemini-3-pro-image"
