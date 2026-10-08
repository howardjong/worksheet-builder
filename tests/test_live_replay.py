"""Replay uses frozen approval and never re-plans or quietly substitutes fallback art."""

from __future__ import annotations

import json
from pathlib import Path

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
            {model: 0.1 for model in [*openrouter.models("image"), *openrouter.models("vision")]}
        ),
    )
    report = replay(str(tmp_path / "trial"), str(frozen), live=True, worksheet=1)
    assert report["approved"] and Path(str(report["pdf_path"])).is_file()
    assert calls == ["first"]
    assert report["package_hash"] == json.loads(frozen.read_text())["package_hash"]
