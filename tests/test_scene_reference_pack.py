"""Runtime reference conditioning, cache separation and original judge authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from companion.character_identity import resolve_character_identity
from companion.schema import LearnerProfile
from render.live_scene import (
    DECISION_THRESHOLDS,
    PRIOR_PROMPT_VERSION,
    PROMPT_VERSION,
    SceneReferences,
    _scene_key,
    judge_reference,
    judge_scene,
    load_approved_scene,
    scene_prompt,
    scene_references,
    scene_rubric,
)
from tests.test_live_composition import approved_gate, context, synthetic_image
from theme.schema import ThemeConfig

LIBRARY = (
    Path(__file__).resolve().parents[1]
    / "assets/characters/rainbow_learning_buddy/reference_library/v1/manifest.json"
)


def test_scene_quality_changes_request_and_cache_but_not_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render.live_scene import generate_scene

    current = context(tmp_path, count=1)
    qualities: list[str] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", "openai/gpt-image-2.5-flare")

    def generate(*args: Any, **kwargs: Any) -> bytes:
        assert kwargs["model"] == "openai/gpt-image-2.5-flare"
        qualities.append(kwargs["quality"])
        return synthetic_image()

    monkeypatch.setattr("ai.openrouter.generate_image", generate)
    monkeypatch.setattr("render.live_scene.judge_scene", lambda *a, **kw: approved_gate())
    assert generate_scene(current)
    assert generate_scene(current)
    monkeypatch.setenv("WORKSHEET_IMAGE_QUALITY", "medium")
    assert load_approved_scene(current) is None
    assert generate_scene(current)
    assert load_approved_scene(current)
    assert qualities == ["auto", "medium"]
    receipt = json.loads((tmp_path / "learning_scene.json").read_text())
    assert receipt["quality"] == "medium"
    assert receipt["decision_thresholds"] == DECISION_THRESHOLDS
    monkeypatch.setenv("WORKSHEET_IMAGE_QUALITY", "typo")
    with pytest.raises(ValueError, match="WORKSHEET_IMAGE_QUALITY"):
        generate_scene(current)
    assert qualities == ["auto", "medium"]


def test_previous_identity_prompt_receipt_replays_with_original_auto_quality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = context(tmp_path, count=1)
    theme = current.theme
    assert isinstance(theme, ThemeConfig)
    refs = scene_references(current.design_spec, theme, current.character_identity)
    old_prompt = scene_prompt(
        current.design_spec,
        theme,
        current.character_identity,
        prior_identity_prompt=True,
        reference_roles=tuple(refs.roles),
    )
    assert "mouth opening may change naturally" in old_prompt
    assert "Defining character details" not in old_prompt
    key = _scene_key(
        old_prompt,
        judge_reference(current.character_identity),
        prompt_version=PRIOR_PROMPT_VERSION,
        generation_reference_hashes=refs.hashes,
    )
    png = synthetic_image()
    (tmp_path / "learning_scene.png").write_bytes(png)
    (tmp_path / "learning_scene.json").write_text(
        json.dumps(
            {
                "scene_version": "live_scene_v5_relevant_procedure",
                "prompt_version": PRIOR_PROMPT_VERSION,
                "key": key,
                "status": "approved",
                "gate": approved_gate().model_dump(),
                "sha256": hashlib.sha256(png).hexdigest(),
            }
        )
    )
    monkeypatch.setenv("WORKSHEET_IMAGE_QUALITY", "low")
    monkeypatch.setattr("ai.openrouter.generate_image", lambda *a, **kw: pytest.fail("inference"))
    assert load_approved_scene(current)


def test_other_character_description_does_not_inherit_rainbow_details(tmp_path: Path) -> None:
    current = context(tmp_path, count=1)
    theme = current.theme
    assert isinstance(theme, ThemeConfig)
    identity = resolve_character_identity(LearnerProfile(name="Test", grade_level="2"), "space")
    other = identity.model_copy(update={"base_character": "robot", "character_block": "blue robot"})
    prompt = scene_prompt(current.design_spec, theme, other)
    assert "Defining character details: blue robot" in prompt
    assert "rainbow-haired" not in prompt
    assert "specified expression and theme clothing" in prompt


@pytest.mark.parametrize(
    "goal,format,expected",
    [
        ("Build 7 words", "write", "happy-open-smile"),
        ("Choose a word", "circle", "thinking"),
        ("Write 5 words", "write", "concentrating"),
    ],
)
def test_runtime_selects_approved_expression_and_costume_without_changing_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal: str, format: str, expected: str
) -> None:
    current = context(tmp_path, count=1)
    assert isinstance(current.theme, ThemeConfig)
    identity = resolve_character_identity(LearnerProfile(name="Test", grade_level="2"), "space")
    authority = judge_reference(identity)
    assert authority is not None
    current.design_spec.sections[0].micro_goal = goal
    current.design_spec.sections[0].items[0].response_format = format
    monkeypatch.setenv("WORKSHEET_SCENE_REFERENCE_LIBRARY", str(LIBRARY))
    pack = scene_references(current.design_spec, current.theme, identity)
    assert pack.roles == ["original_identity", "expression_detail", "theme_costume"]
    assert pack.expression == expected
    catalog = json.loads(LIBRARY.read_text())
    face = next(x for x in catalog["items"] if x["group"] == "expressions" and x["id"] == expected)
    outfit = next(
        x for x in catalog["items"] if x["group"] == "wardrobe" and x["id"] == "astronaut"
    )
    assert pack.hashes == (hashlib.sha256(authority).hexdigest(), face["sha256"], outfit["sha256"])
    assert judge_reference(identity) == authority == pack.images[0]
    prompt = scene_prompt(
        current.design_spec, current.theme, identity, reference_roles=tuple(pack.roles)
    )
    assert "Image 1 fixes the original character" in prompt
    assert "Image 2 supplies approved face/hair detail and expression" in prompt
    assert "costume, not its standing pose" in prompt
    assert "Preserve the exact approved expression from Image 2" in prompt
    assert "do not invent a different expression" in prompt
    assert "rainbow-haired Roblox-style buddy" in prompt
    assert "simple black oval eyes" in prompt
    assert "Do not change the face shape, facial features" in prompt
    assert "hair silhouette, hairstyle or individual hair colors" in prompt
    assert "torso or limb proportions, outline weight, shading or illustration style" in prompt
    assert "Change only the pose/action and scene" in prompt
    assert "large head" not in prompt and "soft rounded" not in prompt
    assert current.design_spec.sections[0].items[0].content not in prompt
    assert "Activities:" not in prompt and "Learning goal:" not in prompt


def test_full_scene_transport_sends_pack_to_generator_and_judge_and_separates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render.live_scene import generate_scene

    identity = resolve_character_identity(LearnerProfile(name="Test", grade_level="2"), "space")
    current = replace(context(tmp_path, count=1), character_identity=identity)
    sent: list[list[bytes]] = []
    judged: list[SceneReferences] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-surrogate")
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", "offline-image")
    monkeypatch.setenv("WORKSHEET_SCENE_REFERENCE_LIBRARY", str(LIBRARY))

    def generate(*args: Any, **kwargs: Any) -> bytes:
        sent.append(kwargs["reference_pngs"])
        assert kwargs["quality"] == "auto" and kwargs["background"] == "opaque"
        assert kwargs["allow_provider_fallback"] is (len(kwargs["reference_pngs"]) == 1)
        return synthetic_image()

    def judge(png: bytes, references: SceneReferences, *args: Any) -> Any:
        judged.append(references)
        return approved_gate()

    monkeypatch.setattr("ai.openrouter.generate_image", generate)
    monkeypatch.setattr("render.live_scene.judge_scene", judge)
    assert generate_scene(current)
    assert len(sent) == 1 and len(sent[0]) == 3
    assert judged[0].images == sent[0]
    assert judged[0].roles == ["original_identity", "expression_detail", "theme_costume"]
    assert judged[0].images[0] == judge_reference(identity)
    assert load_approved_scene(current)
    assert generate_scene(current)  # same reference hashes: actual cache hit
    assert len(sent) == 1
    report = json.loads((tmp_path / "learning_scene.json").read_text())
    assert report["prompt_version"] == PROMPT_VERSION
    assert report["generation_reference_hashes"] == [hashlib.sha256(x).hexdigest() for x in sent[0]]
    assert report["judge_reference_sha256"] == report["generation_reference_hashes"][0]
    assert (tmp_path / "scene_prompt.txt").is_file()
    monkeypatch.delenv("WORKSHEET_SCENE_REFERENCE_LIBRARY")
    assert load_approved_scene(current) is None  # pack receipt cannot certify original-only request
    assert generate_scene(current)
    assert len(sent) == 2 and len(sent[1]) == 1
    assert judged[1].images == sent[1] == [judge_reference(identity)]
    assert judged[1].roles == ["original_identity"]


@pytest.mark.parametrize("supplemented", [False, True])
@pytest.mark.parametrize("identity_score", [0.84, 0.85])
def test_luna_gate_sends_ordered_references_and_keeps_identity_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supplemented: bool,
    identity_score: float,
) -> None:
    current = context(tmp_path, count=1)
    theme = current.theme
    assert isinstance(theme, ThemeConfig)
    identity = resolve_character_identity(LearnerProfile(name="Test", grade_level="2"), "space")
    if supplemented:
        monkeypatch.setenv("WORKSHEET_SCENE_REFERENCE_LIBRARY", str(LIBRARY))
    else:
        monkeypatch.delenv("WORKSHEET_SCENE_REFERENCE_LIBRARY", raising=False)
    references = scene_references(current.design_spec, theme, identity)
    png = synthetic_image()
    calls: list[str] = []

    def decide(state: str, questions: dict[str, str], **kwargs: Any) -> dict[str, float]:
        calls.append(state)
        assert kwargs["images"] == [*references.images, png]
        assert len(kwargs["images"]) == (4 if supplemented else 2)
        assert (state, questions) == scene_rubric(
            current.design_spec, theme, reference_roles=tuple(references.roles)
        )
        return {name: identity_score if name == "identity_ok" else 0.99 for name in questions}

    monkeypatch.setattr("ai.openrouter.decide_yes_no", decide)
    gate = judge_scene(png, references, current.design_spec, theme, backend="decisions")
    assert len(calls) == 1
    assert gate is not None
    assert gate.identity_ok is (identity_score >= 0.85)
    assert gate.approved is (identity_score >= 0.85)


@pytest.mark.parametrize("supplemented", [False, True])
def test_scene_rubric_explains_reference_roles_without_weakening_checks(supplemented: bool) -> None:
    roles = (
        ("original_identity", "expression_detail", "theme_costume")
        if supplemented
        else ("original_identity",)
    )
    state, questions = scene_rubric(context(Path("unused")).design_spec, reference_roles=roles)
    assert "FIRST image is the neutral identity authority" in state
    assert "face, hair and proportions" in state
    assert "LAST image is the candidate" in state
    assert ("SECOND image is the approved expression for this scene" in state) is supplemented
    assert ("THIRD image is the approved theme costume" in state) is supplemented
    assert "FIRST reference's face, hair and proportions" in questions["identity_ok"]
    if supplemented:
        assert "approved expression and costume" in questions["identity_ok"]
    assert set(questions) == {*DECISION_THRESHOLDS, "meaningful_area"}
    assert DECISION_THRESHOLDS == {
        "identity_ok": 0.85,
        "supports_task": 0.35,
        "action_ok": 0.35,
        "outfit_ok": 0.85,
        "child_safe": 0.95,
        "no_text": 0.95,
        "answer_free": 0.95,
    }


@pytest.mark.parametrize("invalid", ["missing", "wrong-character", "wrong-theme"])
def test_invalid_runtime_pack_blocks_before_art_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    from render.live_scene import generate_scene

    identity = resolve_character_identity(LearnerProfile(name="Test", grade_level="2"), "space")
    current = replace(context(tmp_path, count=1), character_identity=identity)
    monkeypatch.setenv("WORKSHEET_SCENE_REFERENCE_LIBRARY", str(LIBRARY))
    if invalid == "missing":
        monkeypatch.setenv("WORKSHEET_SCENE_REFERENCE_LIBRARY", str(tmp_path / "missing.json"))
    elif invalid == "wrong-character":
        current = replace(
            current, character_identity=identity.model_copy(update={"base_character": "other"})
        )
    else:
        current.design_spec.theme_id = "dinosaur"
    monkeypatch.setattr(
        "ai.openrouter.generate_image",
        lambda *a, **k: pytest.fail("invalid pack reached inference"),
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        generate_scene(current)
