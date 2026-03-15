"""Tests for batch processing utilities and orchestration."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from batch_utils import (
    FileResult,
    ProgressTracker,
    RateLimiter,
    collect_input_files,
    generate_report,
    load_manifest,
    save_manifest_entry,
)

# --- FileResult ---


class TestFileResult:
    def test_success_result(self) -> None:
        r = FileResult(
            input_path="/tmp/a.jpg",
            status="success",
            output_path="/tmp/out.pdf",
            duration_seconds=12.345,
        )
        assert r.status == "success"
        assert r.output_path == "/tmp/out.pdf"

    def test_to_dict(self) -> None:
        r = FileResult(
            input_path="/tmp/a.jpg",
            status="failed",
            error="boom",
            duration_seconds=1.999,
            retries=2,
        )
        d = r.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "boom"
        assert d["duration_seconds"] == 2.0  # rounded
        assert d["retries"] == 2


# --- collect_input_files ---


class TestCollectInputFiles:
    def test_finds_images(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.png").touch()
        (tmp_path / "c.txt").touch()
        (tmp_path / "d.pdf").touch()

        files = collect_input_files(str(tmp_path))
        names = {f.name for f in files}
        assert names == {"a.jpg", "b.png"}

    def test_recursive(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "a.jpg").touch()
        (sub / "b.png").touch()

        files = collect_input_files(str(tmp_path), recursive=True)
        names = {f.name for f in files}
        assert names == {"a.jpg", "b.png"}

    def test_non_recursive(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "a.jpg").touch()
        (sub / "b.png").touch()

        files = collect_input_files(str(tmp_path), recursive=False)
        names = {f.name for f in files}
        assert names == {"a.jpg"}

    def test_empty_dir(self, tmp_path: Path) -> None:
        files = collect_input_files(str(tmp_path))
        assert files == []

    def test_nonexistent_dir(self) -> None:
        files = collect_input_files("/nonexistent/path")
        assert files == []

    def test_all_image_extensions(self, tmp_path: Path) -> None:
        for ext in [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"]:
            (tmp_path / f"file{ext}").touch()
        files = collect_input_files(str(tmp_path))
        assert len(files) == 7


# --- RateLimiter ---


class TestRateLimiter:
    def test_allows_within_limit(self) -> None:
        limiter = RateLimiter(rpm=5)
        for _ in range(5):
            assert limiter.acquire(timeout=1.0) is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(rpm=2)
        assert limiter.acquire(timeout=1.0) is True
        assert limiter.acquire(timeout=1.0) is True
        # Third should timeout (only 2 RPM)
        assert limiter.acquire(timeout=0.5) is False

    def test_concurrent_acquire_spaced(self) -> None:
        """Multiple threads competing for tokens are properly limited."""
        limiter = RateLimiter(rpm=3)
        results: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            r = limiter.acquire(timeout=2.0)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert results.count(True) == 3

    def test_timeout_returns_false(self) -> None:
        limiter = RateLimiter(rpm=1)
        limiter.acquire(timeout=1.0)  # Use the one slot
        assert limiter.acquire(timeout=0.2) is False


# --- ProgressTracker ---


class TestProgressTracker:
    def test_record_and_summary(self) -> None:
        tracker = ProgressTracker(total=3)
        r1 = FileResult(input_path="a.jpg", status="success")
        r2 = FileResult(input_path="b.jpg", status="failed", error="err")
        r3 = FileResult(input_path="c.jpg", status="skipped")

        tracker.record(r1)
        tracker.record(r2)
        line = tracker.record(r3)

        assert "[3/3]" in line
        summary = tracker.summary
        assert summary["success"] == 1
        assert summary["failed"] == 1
        assert summary["skipped"] == 1

    def test_thread_safe(self) -> None:
        tracker = ProgressTracker(total=20)
        threads = []

        def worker(i: int) -> None:
            r = FileResult(
                input_path=f"file_{i}.jpg",
                status="success" if i % 2 == 0 else "failed",
            )
            tracker.record(r)

        for i in range(20):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5.0)

        summary = tracker.summary
        assert summary["success"] + summary["failed"] == 20
        assert summary["success"] == 10
        assert summary["failed"] == 10


# --- Manifest ---


class TestManifest:
    def test_load_manifest_empty(self, tmp_path: Path) -> None:
        result = load_manifest(str(tmp_path))
        assert result == {}

    def test_load_manifest_with_data(self, tmp_path: Path) -> None:
        manifest = {
            "files": {
                "a.jpg": {"output": "out.pdf", "timestamp": "2026-01-01"}
            }
        }
        (tmp_path / "batch_manifest.json").write_text(json.dumps(manifest))
        result = load_manifest(str(tmp_path))
        assert "a.jpg" in result
        assert result["a.jpg"]["output"] == "out.pdf"

    def test_save_manifest_entry(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "batch_manifest.json"
        lock = threading.Lock()

        save_manifest_entry(
            manifest_path,
            "a.jpg",
            {"output": "out.pdf"},
            lock,
        )

        data = json.loads(manifest_path.read_text())
        assert data["files"]["a.jpg"]["output"] == "out.pdf"

    def test_save_manifest_entry_appends(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "batch_manifest.json"
        lock = threading.Lock()

        save_manifest_entry(manifest_path, "a.jpg", {"output": "a.pdf"}, lock)
        save_manifest_entry(manifest_path, "b.jpg", {"output": "b.pdf"}, lock)

        data = json.loads(manifest_path.read_text())
        assert len(data["files"]) == 2

    def test_skip_detection(self, tmp_path: Path) -> None:
        """Manifest + existing output file = skip."""
        pdf_path = tmp_path / "out.pdf"
        pdf_path.touch()

        manifest = {
            "files": {
                "a.jpg": {"output": str(pdf_path), "timestamp": "2026-01-01"}
            }
        }
        (tmp_path / "batch_manifest.json").write_text(json.dumps(manifest))

        existing = load_manifest(str(tmp_path))
        entry = existing.get("a.jpg")
        assert entry is not None
        assert Path(entry["output"]).exists()


# --- generate_report ---


class TestGenerateReport:
    def test_report_structure(self) -> None:
        results = [
            FileResult(input_path="a.jpg", status="success", output_path="a.pdf"),
            FileResult(input_path="b.jpg", status="failed", error="oops"),
            FileResult(input_path="c.jpg", status="skipped"),
        ]
        report = generate_report(results, 123.456)
        assert report["total"] == 3
        assert report["success"] == 1
        assert report["failed"] == 1
        assert report["skipped"] == 1
        assert report["duration_seconds"] == 123.46
        assert "failures" in report
        assert report["failures"][0]["error"] == "oops"


# --- _process_single_file ---


class TestProcessSingleFile:
    def test_success(self, tmp_path: Path) -> None:
        from batch import _process_single_file

        input_file = tmp_path / "test.jpg"
        input_file.touch()

        def mock_pipeline(**kwargs: object) -> str:
            return "/tmp/out.pdf"

        result = _process_single_file(
            input_path=input_file,
            profile_path="profiles/test.yaml",
            theme_id="space",
            output_dir=str(tmp_path),
            max_retries=0,
            rate_limiter=RateLimiter(rpm=60),
            shutdown_event=threading.Event(),
            skip_images=False,
            pipeline_fn=mock_pipeline,
        )

        assert result.status == "success"
        assert result.output_path == "/tmp/out.pdf"

    def test_retry_then_success(self, tmp_path: Path) -> None:
        from batch import _process_single_file

        input_file = tmp_path / "test.jpg"
        input_file.touch()

        call_count = 0

        def mock_pipeline(**kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            return "/tmp/out.pdf"

        result = _process_single_file(
            input_path=input_file,
            profile_path="profiles/test.yaml",
            theme_id="space",
            output_dir=str(tmp_path),
            max_retries=2,
            rate_limiter=RateLimiter(rpm=60),
            shutdown_event=threading.Event(),
            skip_images=False,
            pipeline_fn=mock_pipeline,
        )

        assert result.status == "success"
        assert result.retries == 1

    def test_shutdown_returns_skipped(self, tmp_path: Path) -> None:
        from batch import _process_single_file

        input_file = tmp_path / "test.jpg"
        input_file.touch()

        shutdown = threading.Event()
        shutdown.set()  # Already shutting down

        result = _process_single_file(
            input_path=input_file,
            profile_path="profiles/test.yaml",
            theme_id="space",
            output_dir=str(tmp_path),
            max_retries=0,
            rate_limiter=RateLimiter(rpm=60),
            shutdown_event=shutdown,
            skip_images=False,
        )

        assert result.status == "skipped"

    def test_no_images_sets_env(self, tmp_path: Path) -> None:
        from batch import _process_single_file

        input_file = tmp_path / "test.jpg"
        input_file.touch()
        captured_env: list[str | None] = []

        def mock_pipeline(**kwargs: object) -> str:
            captured_env.append(os.environ.get("WORKSHEET_SKIP_ASSET_GEN"))
            return "/tmp/out.pdf"

        result = _process_single_file(
            input_path=input_file,
            profile_path="profiles/test.yaml",
            theme_id="space",
            output_dir=str(tmp_path),
            max_retries=0,
            rate_limiter=RateLimiter(rpm=60),
            shutdown_event=threading.Event(),
            skip_images=True,
            pipeline_fn=mock_pipeline,
        )

        assert result.status == "success"
        assert captured_env[0] == "1"
        # Env var should be cleaned up after
        assert os.environ.get("WORKSHEET_SKIP_ASSET_GEN") is None

    def test_collects_rag_index_payload(self, tmp_path: Path) -> None:
        from batch import _process_single_file

        input_file = tmp_path / "test.jpg"
        input_file.touch()

        class MockArtifacts:
            def model_dump(self) -> dict[str, object]:
                return {
                    "source_image_hash": "hash123",
                    "pdf_paths": ["/tmp/out.pdf"],
                }

        def mock_pipeline(**kwargs: object) -> MockArtifacts:
            assert kwargs["index_results"] is False
            return MockArtifacts()

        result = _process_single_file(
            input_path=input_file,
            profile_path="profiles/test.yaml",
            theme_id="space",
            output_dir=str(tmp_path),
            max_retries=0,
            rate_limiter=RateLimiter(rpm=60),
            shutdown_event=threading.Event(),
            skip_images=False,
            pipeline_fn=mock_pipeline,
        )

        assert result.status == "success"
        assert result.output_path == "/tmp/out.pdf"
        assert result.rag_index_payload == {
            "source_image_hash": "hash123",
            "pdf_paths": ["/tmp/out.pdf"],
        }


class TestBatchIndexing:
    def test_indexes_successful_runs_from_main_thread(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from batch import _index_completed_runs

        calls: list[dict[str, object]] = []
        monkeypatch.setattr("transform.rag_available", lambda: True)
        monkeypatch.setattr("rag.indexer.index_run", lambda **kwargs: calls.append(kwargs))

        results = [
            FileResult(
                input_path="a.jpg",
                status="success",
                output_path="a.pdf",
                rag_index_payload={"source_image_hash": "hash-a", "pdf_paths": ["a.pdf"]},
            ),
            FileResult(input_path="b.jpg", status="failed", error="boom"),
            FileResult(
                input_path="c.jpg",
                status="success",
                output_path="c.pdf",
                rag_index_payload={"source_image_hash": "hash-c", "pdf_paths": ["c.pdf"]},
            ),
        ]

        indexed = _index_completed_runs(results)

        assert indexed == 2
        assert [call["source_image_hash"] for call in calls] == ["hash-a", "hash-c"]


# --- CLI dry-run ---


class TestBatchCLI:
    def test_dry_run_no_processing(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from batch import batch

        # Create test images
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.png").touch()

        runner = CliRunner()
        result = runner.invoke(
            batch,
            [
                "--input-dir", str(tmp_path),
                "--profile", "profiles/test.yaml",
                "--theme", "space",
                "--dry-run",
            ],
        )

        assert "Dry run" in result.output
        assert "2 file(s) would be processed" in result.output
