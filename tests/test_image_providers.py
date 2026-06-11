"""Tests for image provider chain resolution (offline; no API calls)."""

from __future__ import annotations

import pytest


def test_chain_default_order_with_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)

    chain = resolve_provider_chain()

    assert [provider.provider_id for provider in chain] == ["gemini", "openai"]


def test_chain_skips_unavailable_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)

    chain = resolve_provider_chain()

    assert [provider.provider_id for provider in chain] == ["openai"]


def test_chain_respects_env_order_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.setenv("WORKSHEET_IMAGE_PROVIDERS", "openai,gemini")

    chain = resolve_provider_chain()

    assert [provider.provider_id for provider in chain] == ["openai", "gemini"]


def test_chain_empty_without_any_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)

    assert resolve_provider_chain() == []


def test_generate_returns_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import GeminiImageProvider, OpenAIImageProvider

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert GeminiImageProvider().generate("prompt", None) is None
    assert OpenAIImageProvider().generate("prompt", None) is None


def test_openai_model_id_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from render.image_providers import OpenAIImageProvider

    monkeypatch.setenv("WORKSHEET_OPENAI_IMAGE_MODEL", "gpt-image-3-future")

    assert OpenAIImageProvider().model_id == "gpt-image-3-future"
