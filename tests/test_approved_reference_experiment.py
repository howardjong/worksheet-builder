"""Exercise reference conditioning, hash checks and shared worker limits offline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from adapt.approval import package_hash
from ai import openrouter, telemetry
from ai.run_limits import RunLimitExceededError, current_limits
from experiments import character_consistency as cc
from experiments.reference_library import ReferenceLibrary, approved_supplements
from render.replay import FrozenRenderPackage
from tests.test_character_consistency import _image
from tests.test_live_replay import manifest as frozen_fixture

LIBRARY = Path("assets/characters/rainbow_learning_buddy/reference_library/v1/manifest.json")


def setup_manifest(tmp_path: Path, repeats: int = 1) -> Path:
    frozen = frozen_fixture(tmp_path / "source")
    package = FrozenRenderPackage.model_validate_json(frozen.read_text())
    package.worksheets[0].chunks[0].micro_goal = "Build two words"
    package.package_hash = package_hash(package.worksheets)
    package.judged_package_hash = package.package_hash
    frozen.write_text(package.model_dump_json())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "package": str(frozen), "face_crop_rect": [0.33, 0, 0.66, 0.42],
        "procedures": {"word_building": 1}, "repeats": repeats,
        "design": "approved_reference", "reference_library": str(LIBRARY.resolve()),
    }))
    return path


def test_library_hashes_and_owner_approval() -> None:
    library = ReferenceLibrary.model_validate_json(LIBRARY.read_text())
    assert len(library.items) == 44
    for item in library.items:
        assert library.item_bytes(LIBRARY.parent, item.group, item.id)


@pytest.mark.parametrize("tamper", ["approval", "hash", "escape"])
def test_supplement_rejects_unapproved_changed_or_external_asset(tamper: str) -> None:
    library = ReferenceLibrary.model_validate_json(LIBRARY.read_text())
    item = next(item for item in library.items if item.id == "neutral-friendly")
    if tamper == "approval":
        item.owner_approved = False
    elif tamper == "hash":
        item.sha256 = "0" * 64
    else:
        item.path = "../outside.png"
    with pytest.raises(ValueError):
        library.item_bytes(LIBRARY.parent, item.group, item.id)


def test_dry_screen_keeps_original_judge_and_changes_only_conditioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = setup_manifest(tmp_path)
    monkeypatch.setattr(openrouter, "generate_image", lambda *a, **k: pytest.fail("network"))
    report = cc.run_experiment(str(tmp_path / "dry"), str(path))
    hashes = report["reference_hashes"]
    original = report["original_reference_sha256"]
    face, suit = approved_supplements(LIBRARY, "neutral-friendly")
    face_hash, suit_hash = (hashlib.sha256(raw).hexdigest() for raw in (face, suit))
    assert all(refs[0] == original for refs in hashes.values())
    assert hashes["B_word_building_r1"] == [original, face_hash]
    assert hashes["D_word_building_r1"] == [original, face_hash, suit_hash]
    assert hashes["A_word_building_r1"] == hashes["C_word_building_r1"][:2]
    prompts = json.loads((tmp_path / "dry/prompts.json").read_text())
    assert len(set(prompts.values())) == 1
    assert report["trials_planned"] == 4 and not report["can_approve_worksheet"]


def test_live_workers_share_limits_telemetry_and_reference_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = setup_manifest(tmp_path)
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "1")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "16")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "30")
    monkeypatch.setenv("WORKSHEET_CALL_CEILINGS_JSON", json.dumps({
        cc.IMAGE_MODEL: 0.1, cc.GATE_MODEL: 0.01,
    }))
    monkeypatch.setattr(openrouter, "available", lambda: True)
    references: list[list[bytes]] = []
    limit_objects: list[int] = []

    def fake_image(*args: Any, **kwargs: Any) -> bytes:
        limits = current_limits()
        assert limits is not None
        limit_objects.append(id(limits))
        reservation = limits.reserve(cc.IMAGE_MODEL)
        limits.settle(reservation, 0.02)
        telemetry.record_call({"model": cc.IMAGE_MODEL, "cost_usd": 0.02})
        references.append(kwargs["reference_pngs"])
        assert kwargs["allow_provider_fallback"] is False
        return _image()

    def fake_gate(png: bytes, original: bytes, *args: Any, **kwargs: Any) -> None:
        assert kwargs["backend"] == "decisions"
        assert all(pack[0] == original for pack in references)
        return None

    monkeypatch.setattr(openrouter, "generate_image", fake_image)
    monkeypatch.setattr(cc, "judge_scene", fake_gate)
    cc.run_experiment(str(tmp_path / "live"), str(path), live=True)
    assert len(references) == 4 and len(set(limit_objects)) == 1
    log = (tmp_path / "live/inference_calls.jsonl").read_text().splitlines()
    assert len(log) == 4
    assert len({json.loads(line)["candidate_id"] for line in log}) == 4
    snapshot = json.loads((tmp_path / "live/run_limits.json").read_text())
    assert snapshot["http_attempts"] == 4
    assert snapshot["reported_cost_usd"] == pytest.approx(0.08)


def test_worker_over_ceiling_failure_is_preserved_and_blocks_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = setup_manifest(tmp_path)
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "1")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "16")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "30")
    monkeypatch.setenv("WORKSHEET_CALL_CEILINGS_JSON", json.dumps({
        cc.IMAGE_MODEL: 0.1, cc.GATE_MODEL: 0.01,
    }))
    monkeypatch.setattr(openrouter, "available", lambda: True)

    def over_ceiling(*args: Any, **kwargs: Any) -> None:
        limits = current_limits()
        assert limits is not None
        reservation = limits.reserve(cc.IMAGE_MODEL)
        limits.settle(reservation, 0.2)
        limits.check()

    monkeypatch.setattr(openrouter, "generate_image", over_ceiling)
    with pytest.raises(RunLimitExceededError, match="ceiling"):
        cc.run_experiment(str(tmp_path / "blocked"), str(path), live=True)
    records = (tmp_path / "blocked/trials.jsonl").read_text().splitlines()
    assert records and all(json.loads(line)["outcome"] == "error" for line in records)


def test_unrelated_character_is_not_given_buddy_supplements(tmp_path: Path) -> None:
    path = setup_manifest(tmp_path)
    config = json.loads(path.read_text())
    frozen = Path(config["package"])
    package = FrozenRenderPackage.model_validate_json(frozen.read_text())
    package.identity.base_character = "other_buddy"
    frozen.write_text(package.model_dump_json())
    with pytest.raises(ValueError, match="rainbow buddy"):
        cc.run_experiment(str(tmp_path / "other"), str(path))


def test_incorrect_procedure_mapping_stops_before_inference(tmp_path: Path) -> None:
    path = setup_manifest(tmp_path)
    config = json.loads(path.read_text())
    config["procedures"] = {"blank_choices": 1}
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="Procedure label"):
        cc.run_experiment(str(tmp_path / "wrong-action"), str(path))
