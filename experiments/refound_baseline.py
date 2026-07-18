"""Extract comparable metrics from a transform.py run's output directory.

Used to capture the pre-refound baseline (image_gen renders, judge verdicts)
and, in Task 10, to compare hybrid_shell runs against it. Tolerant of missing
artifacts: absent files record as None/empty, never raise.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class RunMetrics(BaseModel):
    run_dir: str
    overall_score: float | None = None
    approved: bool | None = None
    objective_quality: dict[str, float] = Field(default_factory=dict)
    severe_defect_counts: dict[str, int] = Field(default_factory=dict)
    page_attempts: dict[str, int] = Field(default_factory=dict)


def extract_run_metrics(run_dir: Path) -> RunMetrics:
    art = run_dir / "artifacts"
    metrics = RunMetrics(run_dir=str(run_dir))

    verdict_path = art / "judge_verdict.json"
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text())
        metrics.overall_score = verdict.get("overall_score")
        metrics.approved = verdict.get("approved")
        for cell in verdict.get("objective_scores", []):
            oid = cell.get("objective_id", "unknown")
            if cell.get("quality") is not None:
                metrics.objective_quality[oid] = cell["quality"]
            metrics.severe_defect_counts[oid] = len(cell.get("severe_defects", []))

    for render_dir in sorted(art.glob("render_*")):
        attempts = len(list(render_dir.glob("page_attempt_*.png")))
        if attempts:
            metrics.page_attempts[render_dir.name] = attempts

    return metrics


def main() -> None:
    import sys

    runs = [Path(p) for p in sys.argv[1:]]
    print(json.dumps([extract_run_metrics(r).model_dump() for r in runs], indent=2))


if __name__ == "__main__":
    main()
