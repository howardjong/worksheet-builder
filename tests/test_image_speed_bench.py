"""Benchmark safety and measurement plumbing; all image calls are mocked."""

import json
from pathlib import Path
from typing import Any

import pytest

from experiments.image_speed_bench import BenchManifest, benchmark
from tests.test_live_composition import synthetic_image

MODELS = ["openai/gpt-image-2.5-sunburst", "openai/gpt-image-2.5-flare"]


def cases(directory: Path) -> Path:
    (directory / "reference.png").write_bytes(synthetic_image())
    (directory / "prompt.txt").write_text("Image 1 identity, Image 2 expression, Image 3 costume.")
    source = directory / "cases.json"
    source.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "id": name,
                        "prompt": "prompt.txt",
                        "references": [
                            {"role": role, "path": "reference.png"}
                            for role in ("original_identity", "expression_detail", "theme_costume")
                        ],
                    }
                    for name in ("build", "choose")
                ]
            }
        )
    )
    return source


def limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSHEET_IMAGE_SPEED_BENCH_LIVE", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", ",".join(MODELS))
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "1")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "8")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "30")
    monkeypatch.setenv("WORKSHEET_CALL_CEILINGS_JSON", json.dumps(dict.fromkeys(MODELS, 0.1)))


def test_default_benchmark_validates_inputs_without_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = cases(tmp_path)
    manifest = BenchManifest.model_validate_json(source.read_text())
    assert BenchManifest.model_validate_json(manifest.model_dump_json()) == manifest
    limits(monkeypatch)  # Even opt-in env alone cannot start generation.
    monkeypatch.setattr("ai.openrouter.generate_image", lambda *a, **kw: pytest.fail("inference"))
    report = benchmark(str(tmp_path / "dry"), str(source))
    assert report["mode"] == "dry_run_no_inference" and report["results"] == []
    assert report["planned_image_requests"] == 4 and report["maximum_http_attempts"] == 8
    assert report["quality"] == "auto" and not report["can_approve_worksheet"]
    assert len(report["inputs"]) == 2 and len(report["inputs"][0]["reference_hashes"]) == 3
    with pytest.raises(ValueError, match="fresh output"):
        benchmark(str(tmp_path / "dry"), str(source))


def test_benchmark_refuses_unqualified_live_and_invalid_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = cases(tmp_path)
    monkeypatch.setattr("ai.openrouter.generate_image", lambda *a, **kw: pytest.fail("inference"))
    with pytest.raises(ValueError, match="BENCH_LIVE=1"):
        benchmark(str(tmp_path / "no-opt-in"), str(source), live=True)
    monkeypatch.setenv("WORKSHEET_IMAGE_SPEED_BENCH_LIVE", "1")
    with pytest.raises(ValueError, match="verified USD"):
        benchmark(str(tmp_path / "no-limits"), str(source), live=True)
    limits(monkeypatch)
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.1")
    with pytest.raises(ValueError, match="Allocation cannot cover"):
        benchmark(str(tmp_path / "too-small"), str(source), live=True)
    raw = json.loads(source.read_text())
    raw["scenes"][0]["references"].reverse()
    source.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="References must be"):
        benchmark(str(tmp_path / "bad-roles"), str(source))


def test_mocked_benchmark_records_timing_exact_pack_quality_and_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = cases(tmp_path)
    limits(monkeypatch)
    monkeypatch.setenv("WORKSHEET_IMAGE_QUALITY", "low")
    png = synthetic_image()
    calls: list[str] = []
    ticks = iter(range(100))
    monkeypatch.setattr(
        "experiments.image_speed_bench.time.perf_counter", lambda: float(next(ticks))
    )

    def generate(prompt: str, **kwargs: Any) -> bytes:
        assert prompt == (tmp_path / "prompt.txt").read_text()
        assert kwargs["reference_pngs"] == [png, png, png]
        assert kwargs["quality"] == "low" and kwargs["background"] == "opaque"
        assert kwargs["aspect_ratio"] == "16:9" and not kwargs["allow_provider_fallback"]
        calls.append(kwargs["model"])
        return png

    monkeypatch.setattr("ai.openrouter.generate_image", generate)
    output = tmp_path / "mocked-live"
    report = benchmark(str(output), str(source), live=True)
    assert calls == [*MODELS, *reversed(MODELS)]
    assert report["completed"] and len(report["results"]) == 4
    for row in report["results"]:
        assert row["elapsed_s"] > 0 and row["outcome"] == "generated_unreviewed"
        assert (output / row["image_path"]).read_bytes() == png
    assert json.loads((output / "image_speed_bench.json").read_text()) == report


def test_mocked_benchmark_preserves_partial_results_and_failed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = cases(tmp_path)
    limits(monkeypatch)
    calls = 0

    def generate(*args: Any, **kwargs: Any) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private provider message")
        return synthetic_image()

    monkeypatch.setattr("ai.openrouter.generate_image", generate)
    output = tmp_path / "partial"
    with pytest.raises(RuntimeError):
        benchmark(str(output), str(source), live=True)
    raw = (output / "image_speed_bench.json").read_text()
    report = json.loads(raw)
    assert not report["completed"] and len(report["results"]) == 2
    assert report["results"][0]["outcome"] == "generated_unreviewed"
    assert report["results"][1]["error_type"] == "RuntimeError"
    assert "private provider message" not in raw
