"""Shadow comparisons preserve labels, limits and evidence without generating art."""

import json
from pathlib import Path
from typing import Any

import pytest

from experiments.scene_gate_compare import compare
from render.live_scene import DECISIONS_MODEL, HAIKU_MODEL
from tests.test_live_composition import approved_gate, synthetic_image
from tests.test_live_replay import manifest


def cases(tmp_path: Path) -> Path:
    package = manifest(tmp_path / "frozen")
    (tmp_path / "scene.png").write_bytes(synthetic_image())
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "package": str(package),
                "cases": [
                    {"id": "accepted", "image": "scene.png", "worksheet": 1, "human_approved": True}
                ],
            }
        )
    )
    return path


def limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.2")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "8")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "20")
    monkeypatch.setenv(
        "WORKSHEET_CALL_CEILINGS_JSON",
        json.dumps(
            {
                DECISIONS_MODEL: 0.01,
                HAIKU_MODEL: 0.02,
            }
        ),
    )


def test_comparison_defaults_to_no_inference_and_validates_frozen_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = cases(tmp_path)
    monkeypatch.setattr(
        "experiments.scene_gate_compare.judge_scene",
        lambda *a, **kw: pytest.fail("dry comparison made inference"),
    )
    report = compare(str(tmp_path / "dry"), str(path))
    assert report["planned_gate_requests"] == 2
    assert not report["can_approve_worksheet"] and not report["generates_artwork"]
    with pytest.raises(ValueError, match="verified USD"):
        compare(str(tmp_path / "unbounded"), str(path), live=True)
    limits(monkeypatch)
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.01")
    with pytest.raises(ValueError, match="allocation cannot cover"):
        compare(str(tmp_path / "underpriced"), str(path), live=True)
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.2")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "2")
    with pytest.raises(ValueError, match="allocation cannot cover"):
        compare(str(tmp_path / "too-few-attempts"), str(path), live=True)
    package = Path(json.loads(path.read_text())["package"])
    raw = json.loads(package.read_text())
    raw["approved"] = False
    package.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="affirmative approval"):
        compare(str(tmp_path / "bad"), str(path))


def test_comparison_reports_false_rejection_and_keeps_explicit_model_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = cases(tmp_path)
    limits(monkeypatch)
    calls: list[str] = []

    def gate(*args: Any, **kwargs: Any) -> Any:
        model = kwargs["model_ids"][0]
        calls.append(model)
        if model == DECISIONS_MODEL:
            assert kwargs["backend"] == "decisions"
            return approved_gate().model_copy(update={"action_ok": False})
        assert kwargs["backend"] == "vision" and model == HAIKU_MODEL
        return approved_gate()

    monkeypatch.setattr("experiments.scene_gate_compare.judge_scene", gate)
    monkeypatch.setattr(
        "ai.openrouter.generate_image", lambda *a, **kw: pytest.fail("generated new art")
    )
    report = compare(str(tmp_path / "live"), str(path), live=True, repeats=2)
    assert calls == [DECISIONS_MODEL, HAIKU_MODEL] * 2
    assert report["metrics"][DECISIONS_MODEL]["false_rejects"] == 2
    assert report["metrics"][HAIKU_MODEL]["true_accepts"] == 2
    assert len({row["image_sha256"] for row in report["results"]}) == 1
    assert report["completed"] and not report["can_approve_worksheet"]


def test_comparison_retains_partial_paid_evidence_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = cases(tmp_path)
    limits(monkeypatch)
    calls = 0

    def gate(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("test limit exhausted")
        return None if calls == 1 else approved_gate()

    monkeypatch.setattr("experiments.scene_gate_compare.judge_scene", gate)
    with pytest.raises(RuntimeError, match="limit exhausted"):
        compare(str(tmp_path / "partial"), str(path), live=True, repeats=2)
    report = json.loads((tmp_path / "partial/scene_gate_comparison.json").read_text())
    assert len(report["results"]) == 2 and not report["completed"]
    assert report["metrics"][DECISIONS_MODEL]["invalid_responses"] == 1
    timing = json.loads((tmp_path / "partial/timing_summary.json").read_text())
    assert not timing["completed"]


def test_negative_control_must_fail_the_declared_check_not_just_other_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = cases(tmp_path)
    raw = json.loads(path.read_text())
    raw["cases"][0].update(human_approved=False, expected_failed_checks=["outfit_ok"])
    path.write_text(json.dumps(raw))
    limits(monkeypatch)

    def gate(*args: Any, **kwargs: Any) -> Any:
        if kwargs["model_ids"] == [DECISIONS_MODEL]:
            # A generic rejection for a different reason does not verify outfit checking.
            return approved_gate().model_copy(update={"bounds": (0.4, 0.4, 0.5, 0.5)})
        return approved_gate()  # Haiku falsely accepts this synthetic negative label.

    monkeypatch.setattr("experiments.scene_gate_compare.judge_scene", gate)
    report = compare(str(tmp_path / "controls"), str(path), live=True)
    assert report["metrics"][DECISIONS_MODEL]["true_rejects"] == 1
    assert report["metrics"][DECISIONS_MODEL]["control_misses"] == 1
    assert report["metrics"][HAIKU_MODEL]["false_accepts"] == 1
    assert report["results"][0]["expected_check_misses"] == ["outfit_ok"]
