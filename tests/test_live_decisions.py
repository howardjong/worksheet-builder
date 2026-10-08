"""Shadow probe tooling cannot grant worksheet approval or spend by default."""

import json
from pathlib import Path

import pytest

from experiments.live_decisions import probe


def test_shadow_probe_is_dry_by_default_and_jev_refuses_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state.txt"
    state.write_text("Read cat.")
    questions = tmp_path / "questions.json"
    questions.write_text('{"clear":"Is this instruction clear?"}')
    monkeypatch.setattr(
        "ai.openrouter.decide_yes_no", lambda *args, **kwargs: pytest.fail("dry probe spent money")
    )
    report = probe(str(tmp_path / "dry"), str(state), str(questions), "typesafe/jev-1.13")
    assert not report["can_approve_worksheet"] and report["mode"] == "dry_run_no_inference"
    with pytest.raises(ValueError, match="text only"):
        probe(
            str(tmp_path / "images"),
            str(state),
            str(questions),
            "typesafe/jev-1.13",
            image_paths=["not-read"],
        )


def test_live_shadow_probe_requires_limits_and_saves_probabilities_without_promoting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state.txt"
    state.write_text("Read cat.")
    questions = tmp_path / "questions.json"
    questions.write_text('{"clear":"Is this instruction clear?"}')
    with pytest.raises(ValueError, match="verified USD"):
        probe(
            str(tmp_path / "unbounded"), str(state), str(questions), "typesafe/jev-1.13", live=True
        )
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.1")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "2")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "10")
    monkeypatch.setenv("WORKSHEET_CALL_CEILINGS_JSON", '{"typesafe/jev-1.13":0.01}')
    monkeypatch.setattr("ai.openrouter.decide_yes_no", lambda *args, **kwargs: {"clear": 0.99})
    report = probe(
        str(tmp_path / "shadow"), str(state), str(questions), "typesafe/jev-1.13", live=True
    )
    saved = json.loads(Path(str(report["report_path"])).read_text())
    assert saved["probabilities"] == {"clear": 0.99} and not saved["can_approve_worksheet"]
