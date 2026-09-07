"""Baseline metrics extractor for the refound A/B comparison."""

import json
from pathlib import Path

from experiments.refound_baseline import extract_run_metrics


def _make_run_dir(tmp_path: Path) -> Path:
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "judge_verdict.json").write_text(
        json.dumps(
            {
                "objective_scores": [
                    {"objective_id": "obj_manipulation", "quality": 0.8, "severe_defects": []},
                    {
                        "objective_id": "obj_connected_text",
                        "quality": 0.38,
                        "severe_defects": [
                            {"defect_type": "overwhelming_or_adhd_unsafe", "evidence": "x"}
                        ],
                    },
                ],
                "overall_score": 0.66,
                "approved": False,
            }
        )
    )
    render_1 = art / "render_1"
    render_1.mkdir()
    (render_1 / "page_attempt_openai_1.png").write_bytes(b"png")
    return tmp_path


def test_extracts_judge_and_render_metrics(tmp_path: Path) -> None:
    metrics = extract_run_metrics(_make_run_dir(tmp_path))
    assert metrics.overall_score == 0.66
    assert metrics.objective_quality["obj_manipulation"] == 0.8
    assert metrics.severe_defect_counts["obj_connected_text"] == 1
    assert metrics.page_attempts == {"render_1": 1}
    assert metrics.approved is False


def test_tolerates_missing_artifacts(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    metrics = extract_run_metrics(tmp_path)
    assert metrics.overall_score is None
    assert metrics.page_attempts == {}
