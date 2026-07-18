"""A/B report: image_gen baseline runs vs hybrid_shell candidate runs."""

from __future__ import annotations

import sys
from pathlib import Path

from experiments.refound_baseline import RunMetrics, extract_run_metrics


def _row(m: RunMetrics) -> str:
    attempts = sum(m.page_attempts.values())
    defects = sum(m.severe_defect_counts.values())
    return (
        f"| {Path(m.run_dir).name} | {m.overall_score} | {defects} "
        f"| {attempts} | {len(m.page_attempts)} |"
    )


def build_ab_report(baseline: list[RunMetrics], candidate: list[RunMetrics]) -> str:
    header = (
        "| run | overall_score | severe_defects | total_page_attempts | pages |\n"
        "|---|---|---|---|---|"
    )
    lines = ["# Refound A/B: image_gen baseline vs hybrid_shell", "", "## Baseline", header]
    lines += [_row(m) for m in baseline]
    lines += ["", "## Candidate (hybrid_shell)", header]
    lines += [_row(m) for m in candidate]
    lines += [
        "",
        "hybrid_shell render-stage AI calls are 0 by construction "
        "(composed_manifest.json render_api_calls).",
    ]
    return "\n".join(lines)


def main() -> None:
    split = sys.argv.index("--vs")
    baseline = [extract_run_metrics(Path(p)) for p in sys.argv[1:split]]
    candidate = [extract_run_metrics(Path(p)) for p in sys.argv[split + 1 :]]
    print(build_ab_report(baseline, candidate))


if __name__ == "__main__":
    main()
