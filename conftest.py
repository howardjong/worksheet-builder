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
        "WORKSHEET_RUN_MAX_USD",
        "WORKSHEET_RUN_DEADLINE_S",
        "WORKSHEET_RUN_MAX_CALLS",
        "WORKSHEET_CALL_CEILINGS_JSON",
        "WORKSHEET_OPENROUTER_REQUIRE_ZDR",
        "WORKSHEET_SCENE_GATE_BACKEND",
        "WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL",
        "WORKSHEET_OPENROUTER_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)

    def no_live_post(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Tests must mock HTTP inference; live requests are disabled")

    monkeypatch.setattr(httpx, "post", no_live_post)
    monkeypatch.setattr(httpx.Client, "post", no_live_post)
