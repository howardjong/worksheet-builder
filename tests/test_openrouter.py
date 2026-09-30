"""OpenRouter protocol, failures, fallback chains, and gate integration."""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from ai import openrouter


def _image(format: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 48), "white").save(buffer, format=format)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setenv("WORKSHEET_AI_PROVIDER", "openrouter")
    monkeypatch.setattr(time, "sleep", lambda _: None)


def _responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response | Exception]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx, "post", post)
    return calls


def _text(value: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})


def test_image_api_preserves_reference_and_normalizes_raster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _image("JPEG")
    calls = _responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(raw).decode()}],
                },
            )
        ],
    )
    result = openrouter.generate_image("worksheet", raw, model="openai/gpt-image-2.5-sunburst")
    assert result and result.startswith(b"\x89PNG")
    payload = calls[0]["json"]
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/images"
    assert payload["input_references"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert payload["provider"]["allow_fallbacks"] is True
    assert payload["aspect_ratio"] == "3:4"


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_transient_failures_retry_once(monkeypatch: pytest.MonkeyPatch, failure: int | str) -> None:
    first = httpx.ReadTimeout("temporary") if failure == "timeout" else httpx.Response(int(failure))
    calls = _responses(monkeypatch, [first, _text("ok")])
    result = openrouter.complete("prompt")
    assert result and result.text == "ok"
    assert len(calls) == 2
    assert calls[0]["json"]["model"] == calls[1]["json"]["model"]


def test_text_chain_advances_after_exhausted_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_TEXT_MODELS", "model-a,model-b")
    calls = _responses(monkeypatch, [httpx.Response(503), httpx.Response(503), _text("ok")])
    result = openrouter.complete("prompt")
    assert result and result.model == "model-b"
    assert [c["json"]["model"] for c in calls] == ["model-a", "model-a", "model-b"]


def test_invalid_json_and_missing_fields_use_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_VISION_MODELS", "a,b,c")
    calls = _responses(
        monkeypatch, [_text("garbled"), _text("{}"), _text('{"missing": [], "misspelled": []}')]
    )
    from render.page_gates import evaluate_page_text

    result = evaluate_page_text(_image(), ["ship"])
    assert result.available and result.passed
    assert len(calls) == 3


@pytest.mark.parametrize("status", [401, 402])
def test_credentials_failure_stops_the_model_chain_and_redacts_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    calls = _responses(
        monkeypatch, [httpx.Response(status, text="test-router-key private learner content")]
    )
    assert openrouter.complete("private learner content") is None
    assert len(calls) == 1
    assert "test-router-key" not in caplog.text
    assert "private learner content" not in caplog.text


def test_image_auth_failure_stops_asset_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _responses(monkeypatch, [httpx.Response(401)])
    assert openrouter.generate_with_fallbacks("image") is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"b64_json": "not-base64"}]},
        {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]},
    ],
)
def test_missing_or_corrupt_images_are_rejected(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    _responses(monkeypatch, [httpx.Response(200, json=payload)])
    assert openrouter.generate_image("page", model="model-a") is None


def test_image_chain_retries_other_models_after_missing_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", "a,b")
    calls = _responses(
        monkeypatch,
        [
            httpx.Response(200, json={}),
            httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(_image()).decode()}],
                },
            ),
        ],
    )
    assert openrouter.generate_with_fallbacks("page", _image())
    assert [call["json"]["model"] for call in calls] == ["a", "b"]
    assert all(call["json"]["input_references"] for call in calls)


def test_configured_default_chain_has_four_reference_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", raising=False)
    chain = resolve_provider_chain()
    assert [p.model_id for p in chain] == list(openrouter.DEFAULT_MODELS["image"])
    assert len(chain) == 4


def test_no_key_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY")
    calls = _responses(monkeypatch, [])
    assert openrouter.complete("prompt") is None
    assert openrouter.generate_with_fallbacks("page") is None
    assert not calls


def test_model_configuration_deduplicates_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", " a, b,a, ,c ")
    assert openrouter.models("image") == ["a", "b", "c"]


def test_character_judge_uses_openrouter_without_direct_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from companion.character_judge import judge_character_consistency

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls = _responses(
        monkeypatch, [_text(json.dumps({"approved": True, "score": 9, "issues": []}))]
    )
    result = judge_character_consistency(_image(), _image(), ["same hair"])
    assert result.available and result.approved and result.judge == "openrouter"
    assert len(calls[0]["json"]["messages"][0]["content"]) == 3


def test_photo_extraction_with_only_router_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from extract.vision import extract_with_vision

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    source = tmp_path / "photo.jpg"
    source.write_bytes(_image("JPEG"))
    _responses(
        monkeypatch,
        [
            _text(
                json.dumps(
                    {
                        "template_type": "word_list",
                        "regions": [{"type": "word_list", "content": "ship shop fish"}],
                    }
                )
            )
        ],
    )
    result = extract_with_vision(str(source), "source-hash")
    assert result is not None
    assert result.ocr_engine == "openrouter_vision"
    assert "ship" in result.raw_text


def test_adapter_and_planner_prefer_router(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.llm_planner import _call_planner
    from extract.adapter import OpenRouterAdapter, get_adapter

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(get_adapter(), OpenRouterAdapter)
    _responses(monkeypatch, [_text("plan")])
    text, model = _call_planner("plan a lesson")
    assert text == "plan" and model == openrouter.DEFAULT_MODELS["text"][0]


def test_empty_review_is_not_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.schema import AdaptedActivityModel
    from validate.ai_review import _run_review

    adapted = AdaptedActivityModel.model_validate(
        {
            "source_hash": "source",
            "skill_model_hash": "skill",
            "learner_profile_hash": "profile",
            "grade_level": "1",
            "domain": "phonics",
            "specific_skill": "vowel_teams",
            "theme_id": "space",
            "decoration_zones": [],
            "scaffolding": {},
            "chunks": [],
        }
    )
    calls = _responses(
        monkeypatch,
        [
            _text("{}"),
            _text(
                json.dumps(
                    {
                        "passed": False,
                        "issues": [{"criterion": "completeness", "description": "no activities"}],
                        "suggestions": [],
                    }
                )
            ),
        ],
    )
    result = _run_review(adapted)
    assert not result.passed
    assert len(calls) == 2
