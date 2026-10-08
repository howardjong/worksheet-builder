"""Keep repository tests independent of credentials in the developer's environment."""

from typing import Any

import httpx
import pytest


@pytest.fixture(autouse=True)
def _isolate_inference_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "PERPLEXITY_API_KEY",
        "OPENROUTER_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    def no_live_post(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Tests must mock HTTP inference; live requests are disabled")

    monkeypatch.setattr(httpx, "post", no_live_post)
    monkeypatch.setattr(httpx.Client, "post", no_live_post)
