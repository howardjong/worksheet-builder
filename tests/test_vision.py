from __future__ import annotations

import logging

from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from extract.vision import _configured_api_key, extract_with_vision


def test_configured_api_key_uses_only_router(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert _configured_api_key() == "router-key"


def test_configured_api_key_does_not_fall_back_to_google(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert _configured_api_key() == ""


def test_extract_with_vision_returns_none_without_any_api_key(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with caplog.at_level(logging.INFO):
        result = extract_with_vision("unused.jpg", "hash123")

    assert result is None
    assert "No OPENROUTER_API_KEY" in caplog.text
