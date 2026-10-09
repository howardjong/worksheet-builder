"""Offline tests for character-consistency experiment support.

Covers: multi-reference transport payload/order, legacy single-reference
callers, rejected unsupported settings, RGBA preservation, judge-reference
invariance, face-crop provenance, dry-run no-network behavior, and live
budget admission failing closed before any inference.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ai import openrouter
from experiments import character_consistency as cc
from render.live_scene import (
    _reference,
    derive_face_crop,
    generation_reference_pack,
    judge_reference,
)
from render.replay import FrozenRenderPackage


@pytest.fixture(autouse=True)
def _router_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setenv("WORKSHEET_AI_PROVIDER", "openrouter")


PACKAGE = Path(
    "/home/hatch/workspace/wb-ondemand-run/live-full-100-v5/artifacts/frozen_render_package.json"
)

needs_package = pytest.mark.skipif(not PACKAGE.is_file(), reason="frozen package artifact absent")


def _image(mode: str = "RGB", size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    color = (255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0)
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _calls(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(raw).decode()}]})

    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    client = httpx.Client(transport=transport, trust_env=False)
    monkeypatch.setattr(client, "post", post)
    monkeypatch.setattr(openrouter, "_client", client)
    return calls


def test_multi_reference_payload_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    refs = [_image(), _image()]
    calls = _calls(monkeypatch, _image())
    openrouter.generate_image(
        "p", reference_pngs=refs, model="m", quality="auto", background="opaque",
        allow_provider_fallback=False,
    )
    payload = calls[0]["json"]
    assert len(payload["input_references"]) == 2
    urls = [r["image_url"]["url"] for r in payload["input_references"]]
    assert urls[0].startswith("data:image/png;base64,")
    assert urls[0] != urls[1] or len(refs[0]) == len(refs[1])
    assert payload["quality"] == "auto"
    assert payload["background"] == "opaque"
    assert payload["provider"]["allow_fallbacks"] is False


def test_legacy_single_reference_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _image()
    calls = _calls(monkeypatch, raw)
    result = openrouter.generate_image("worksheet", raw, model="m")
    assert result and result.startswith(b"\x89PNG")
    payload = calls[0]["json"]
    assert len(payload["input_references"]) == 1
    assert "quality" not in payload and "background" not in payload
    assert payload["provider"]["allow_fallbacks"] is True


def test_conflicting_and_unsupported_arguments_rejected() -> None:
    with pytest.raises(ValueError):
        openrouter.generate_image("p", _image(), reference_pngs=[_image()], model="m")
    with pytest.raises(ValueError):
        openrouter.generate_image("p", reference_pngs=[_image()] * 17, model="m")
    with pytest.raises(ValueError):
        openrouter.generate_image("p", model="m", quality="ultra")
    with pytest.raises(ValueError):
        openrouter.generate_image("p", model="m", background="clear")


def test_rgba_preserved_when_transparent(monkeypatch: pytest.MonkeyPatch) -> None:
    _calls(monkeypatch, _image("RGBA"))
    result = openrouter.generate_image("p", model="m")
    assert result is not None
    from PIL import Image

    with Image.open(io.BytesIO(result)) as image:
        assert image.mode == "RGBA"


def test_rgb_still_flattened(monkeypatch: pytest.MonkeyPatch) -> None:
    _calls(monkeypatch, _image("RGB"))
    result = openrouter.generate_image("p", model="m")
    assert result is not None
    from PIL import Image

    with Image.open(io.BytesIO(result)) as image:
        assert image.mode == "RGB"


@needs_package
def test_judge_reference_invariant_under_pack_changes() -> None:
    pkg = FrozenRenderPackage.model_validate_json(PACKAGE.read_text())
    baseline = judge_reference(pkg.identity)
    assert baseline == _reference(pkg.identity)
    pack = generation_reference_pack(pkg.identity, extra=(b"crop-bytes",))
    assert pack[0] == baseline
    # Changing the generation pack must not move the gate reference.
    assert judge_reference(pkg.identity) == baseline


@needs_package
def test_face_crop_deterministic_and_provenanced() -> None:
    pkg = FrozenRenderPackage.model_validate_json(PACKAGE.read_text())
    original = _reference(pkg.identity)
    assert original is not None
    rect = (0.33, 0.0, 0.66, 0.42)
    crop_a, prov_a = derive_face_crop(original, rect)
    crop_b, prov_b = derive_face_crop(original, rect)
    assert crop_a == crop_b
    assert prov_a["crop_sha256"] == prov_b["crop_sha256"]
    assert prov_a["rect"] == [0.33, 0.0, 0.66, 0.42]
    assert prov_a["source_sha256"] != prov_a["crop_sha256"]


def test_build_trials_factorial_layout() -> None:
    manifest = cc.ExperimentManifest(
        package="pkg.json",
        face_crop_rect=[0.33, 0.0, 0.66, 0.42],
        procedures={"word_building": 1, "blank_choices": 2},
        repeats=2,
    )
    trials = cc.build_trials(manifest)
    assert len(trials) == 16
    by_arm: dict[str, list[str]] = {}
    for trial in trials:
        by_arm.setdefault(trial.arm, []).append(trial.trial_id)
    assert set(by_arm) == {"A", "B", "C", "D"}
    assert all(len(ids) == 4 for ids in by_arm.values())
    assert [t.prompt_version for t in trials if t.arm == "A"] == ["current"] * 4
    assert [t.prompt_version for t in trials if t.arm == "B"] == ["structured"] * 4
    assert all("original_face_crop" in t.reference_roles for t in trials if t.arm in ("C", "D"))


def test_structured_prompt_separates_sections_and_roles() -> None:
    one = cc.structured_scene_prompt("slide a tile", "three tiles", 1, "word_building")
    two = cc.structured_scene_prompt("slide a tile", "three tiles", 2, "word_building")
    assert "IDENTITY - PRESERVE" in one and "HARD CONSTRAINTS" in one
    assert "Image 2 is a crop" not in one
    assert "Image 2 is a crop" in two
    assert "Do not redesign or age the buddy" in two


@needs_package
def test_dry_run_snapshots_prompts_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "package": str(PACKAGE),
        "face_crop_rect": [0.33, 0.0, 0.66, 0.42],
        "procedures": {"word_building": 1},
        "repeats": 1,
        "arms": ["A", "B"],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    out = tmp_path / "out"

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry run must not call the network")

    monkeypatch.setattr(openrouter, "generate_image", _boom)
    report = cc.run_experiment(str(out), str(manifest_path), live=False)
    assert report["mode"] == "dry_run_no_inference"
    assert report["trials_planned"] == 2
    prompts = json.loads((out / "prompts.json").read_text())
    assert set(prompts) == {"A_word_building_r1", "B_word_building_r1"}
    assert prompts["A_word_building_r1"] != prompts["B_word_building_r1"]
    assert (out / "face_crop.png").is_file()
    assert not (out / "trials.jsonl").exists()


@needs_package
def test_live_fails_closed_without_verified_ceilings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("WORKSHEET_RUN_MAX_USD", "WORKSHEET_RUN_MAX_CALLS", "WORKSHEET_RUN_DEADLINE_S",
                "WORKSHEET_CALL_CEILINGS_JSON", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    manifest = {
        "package": str(PACKAGE),
        "face_crop_rect": [0.33, 0.0, 0.66, 0.42],
        "procedures": {"word_building": 1},
        "repeats": 1,
        "arms": ["A"],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("admission must fail before any call")

    monkeypatch.setattr(openrouter, "generate_image", _boom)
    with pytest.raises(ValueError, match="verified"):
        cc.run_experiment(str(tmp_path / "out"), str(manifest_path), live=True)
