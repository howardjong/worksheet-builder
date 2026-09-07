from experiments.refound_ab import build_ab_report
from experiments.refound_baseline import RunMetrics


def test_report_compares_render_metrics() -> None:
    baseline = [
        RunMetrics(run_dir="out/l101_imagegen", page_attempts={"render_1": 1, "render_2": 2})
    ]
    candidate = [RunMetrics(run_dir="out/l101_hybrid", page_attempts={})]
    report = build_ab_report(baseline, candidate)
    assert "l101_imagegen" in report and "l101_hybrid" in report
    assert "total_page_attempts" in report
