"""Replay uses frozen approval and never re-plans or quietly substitutes fallback art."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from adapt.schema import AdaptedActivityModel, Example
from companion.character_identity import resolve_character_identity
from companion.schema import LearnerProfile
from experiments.live_replay import replay
from render.replay import FrozenRenderPackage, save_frozen_package
from skill.schema import LiteracySkillModel, SourceItem
from tests.test_live_composition import context, mock_images
from theme.schema import ThemeConfig


def manifest(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    current = context(directory, count=2)
    assert isinstance(current.adapted, AdaptedActivityModel)
    assert isinstance(current.theme, ThemeConfig)
    worksheet = current.adapted
    worksheet.chunks[0].worked_example = Example(
        instruction="Read the completed word example:", content="cat"
    )
    profile = LearnerProfile(name="Test Learner", grade_level="2")
    skill = LiteracySkillModel(
        grade_level="2",
        domain="phonics",
        specific_skill="cvc",
        learning_objectives=["Read and write CVC words"],
        target_words=["cat"],
        response_types=["write"],
        source_items=[SourceItem(item_type="word_list", content="cat", source_region_index=0)],
        extraction_confidence=1,
        template_type="unknown",
    )
    from adapt.approval import package_hash

    save_frozen_package(
        directory,
        [worksheet],
        skill,
        profile,
        current.theme,
        resolve_character_identity(profile, "space", character_spec=current.theme.character_spec),
        True,
        package_hash([worksheet]),
        objective_mode=False,
    )
    return directory / "frozen_render_package.json"


def test_dry_replay_makes_no_inference_and_uses_frozen_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = manifest(tmp_path / "source")
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")  # must not change photo replay policy
    monkeypatch.setattr(
        "render.live_scene.openrouter.generate_image",
        lambda *args, **kwargs: pytest.fail("dry run spent budget"),
    )
    report = replay(str(tmp_path / "dry"), str(frozen))
    assert report["mode"] == "dry_run_no_inference" and not report["extracts_or_plans_content"]
    assert (tmp_path / "dry/photo_coverage_ledger.json").is_file()


@pytest.mark.parametrize("tamper", ["content", "approval", "judged_hash"])
def test_replay_rejects_changed_or_unapproved_packages(tmp_path: Path, tamper: str) -> None:
    frozen = manifest(tmp_path / "source")
    package = FrozenRenderPackage.model_validate_json(frozen.read_text())
    if tamper == "content":
        package.worksheets[0].chunks[0].items[0].content = "dog"
    elif tamper == "approval":
        package.approved = False
    else:
        package.judged_package_hash = "different"
    frozen.write_text(package.model_dump_json())
    with pytest.raises(ValueError, match="affirmative approval"):
        replay(str(tmp_path / "trial"), str(frozen))


def test_live_replay_requires_limits_and_rejects_cache_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = manifest(tmp_path / "source")
    mock_images(monkeypatch)
    with pytest.raises(ValueError, match="run USD"):
        replay(str(tmp_path / "unbounded"), str(frozen), live=True)
    (tmp_path / "cached/render_1").mkdir(parents=True)
    with pytest.raises(ValueError, match="empty replay directory"):
        replay(str(tmp_path / "cached"), str(frozen))


def test_render_only_replay_produces_pdf_with_mocked_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = manifest(tmp_path / "source")
    calls = mock_images(monkeypatch)
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "1")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "4")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "30")
    from ai import openrouter

    monkeypatch.setenv(
        "WORKSHEET_CALL_CEILINGS_JSON",
        json.dumps(
            {model: 0.1 for model in [*openrouter.models("image"), "openai/gpt-6-luna-decisions"]}
        ),
    )
    report = replay(str(tmp_path / "trial"), str(frozen), live=True, worksheet=1)
    assert report["approved"] and Path(str(report["pdf_path"])).is_file()
    assert calls == ["first"]
    assert report["package_hash"] == json.loads(frozen.read_text())["package_hash"]


def test_new_pipeline_run_clears_old_frozen_approval(tmp_path: Path) -> None:
    from transform import _clear_stale_run_artifacts

    frozen = manifest(tmp_path)
    (tmp_path / "judge_verdict.json").write_text('{"approved": true}')
    _clear_stale_run_artifacts(tmp_path)
    assert not frozen.exists()
    assert not (tmp_path / "judge_verdict.json").exists()


def saved_scenes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create a real hash-bound fixture with mocked, not paid, artwork."""
    from render.design_spec import compile_worksheet_design_spec
    from render.live_scene import generate_scene
    from render.strategies import RenderContext

    frozen = manifest(tmp_path / "source")
    package = FrozenRenderPackage.model_validate_json(frozen.read_text())
    mock_images(monkeypatch)
    source = tmp_path / "saved"
    for index, worksheet in enumerate(package.worksheets, 1):
        current = RenderContext(
            design_spec=compile_worksheet_design_spec(
                worksheet, package.theme, package.profile, render_mode="hybrid_shell"
            ),
            adapted=worksheet,
            theme=package.theme,
            character_identity=package.identity,
            artifacts_dir=source / f"render_{index}",
            output_path=source / f"worksheet_{index}.pdf",
        )
        assert generate_scene(current)
    return frozen, source


def forbid_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("No-inference recomposition attempted an API call")

    for name in ("generate_image", "complete", "complete_json", "decide_yes_no"):
        monkeypatch.setattr(f"ai.openrouter.{name}", forbidden)
    monkeypatch.setattr("render.live_scene.judge_scene", forbidden)


def test_recomposition_preserves_approved_content_and_image_without_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen, source = saved_scenes(tmp_path, monkeypatch)
    content_before = frozen.read_bytes()
    image_before = (source / "render_1/learning_scene.png").read_bytes()
    forbid_inference(monkeypatch)  # key remains present, so an accidental live call fails
    report = replay(str(tmp_path / "recomposed"), str(frozen), reuse_scenes=str(source))
    assert report["mode"] == "recompose_no_inference" and report["approved"]
    assert Path(str(report["pdf_path"])).is_file()
    assert frozen.read_bytes() == content_before
    assert (tmp_path / "recomposed/render_1/learning_scene.png").read_bytes() == image_before


@pytest.mark.parametrize("tamper", ["image", "gate", "configuration", "missing"])
def test_recomposition_never_regenerates_invalid_saved_art(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    frozen, source = saved_scenes(tmp_path, monkeypatch)
    if tamper == "image":
        (source / "render_1/learning_scene.png").write_bytes(b"changed")
    elif tamper == "gate":
        path = source / "render_1/learning_scene.json"
        receipt = json.loads(path.read_text())
        receipt["gate"]["child_safe"] = False
        path.write_text(json.dumps(receipt))
    elif tamper == "configuration":
        monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", "different")
    else:
        (source / "render_1/learning_scene.json").unlink()
    forbid_inference(monkeypatch)
    with pytest.raises(ValueError, match="Saved scene"):
        replay(str(tmp_path / "recomposed"), str(frozen), reuse_scenes=str(source))


def test_recomposition_cannot_be_reported_as_live(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a live benchmark"):
        replay(str(tmp_path), "unused", live=True, reuse_scenes="unused")


def test_legacy_scene_receipt_can_be_recomposed_without_new_gate_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render.design_spec import compile_worksheet_design_spec
    from render.live_scene import _reference, _scene_key, scene_prompt

    frozen, source = saved_scenes(tmp_path, monkeypatch)
    package = FrozenRenderPackage.model_validate_json(frozen.read_text())
    spec = compile_worksheet_design_spec(
        package.worksheets[0], package.theme, package.profile, render_mode="hybrid_shell"
    )
    monkeypatch.setenv("WORKSHEET_OPENROUTER_SCENE_JUDGE_MODELS", "original-judge")
    path = source / "render_1/learning_scene.json"
    receipt = json.loads(path.read_text())
    receipt["scene_version"] = "live_scene_v2_action_contract"
    receipt["key"] = _scene_key(
        scene_prompt(spec, package.theme, package.identity, legacy=True),
        _reference(package.identity),
        legacy=True,
    )
    path.write_text(json.dumps(receipt))
    forbid_inference(monkeypatch)
    report = replay(str(tmp_path / "recomposed"), str(frozen), reuse_scenes=str(source))
    assert report["mode"] == "recompose_no_inference"
    copied = json.loads((tmp_path / "recomposed/render_1/learning_scene.json").read_text())
    assert copied["scene_version"] == "live_scene_v2_action_contract"
