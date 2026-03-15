"""Batch processing CLI for worksheet-builder with rate-limited API orchestration.

Processes all worksheet images in a directory through the transform pipeline,
with rate limiting, retry logic, and graceful shutdown support.

Usage:
    python batch.py --input-dir ./photos/ --profile profiles/ian.yaml --theme space
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

# Load .env before anything else
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from batch_utils import (
    FileResult,
    ProgressTracker,
    RateLimiter,
    collect_input_files,
    generate_report,
    load_manifest,
    save_manifest_entry,
)

logger = logging.getLogger(__name__)


# Type alias for the pipeline function
PipelineFn = Callable[..., object]


def _get_run_pipeline() -> PipelineFn:
    """Lazy import of artifact-returning pipeline to avoid heavy module load at import time."""
    from transform import run_pipeline_collect_artifacts

    return run_pipeline_collect_artifacts


def _process_single_file(
    input_path: Path,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    max_retries: int,
    rate_limiter: RateLimiter,
    shutdown_event: threading.Event,
    skip_images: bool,
    pipeline_fn: PipelineFn | None = None,
) -> FileResult:
    """Process one file with retry + rate limiting. Called per worker thread."""
    if pipeline_fn is None:
        pipeline_fn = _get_run_pipeline()

    start = time.monotonic()

    for attempt in range(max_retries + 1):
        if shutdown_event.is_set():
            return FileResult(
                input_path=str(input_path),
                status="skipped",
                error="shutdown requested",
                duration_seconds=time.monotonic() - start,
                retries=attempt,
            )

        # Acquire rate limit token
        if not rate_limiter.acquire(timeout=120.0):
            return FileResult(
                input_path=str(input_path),
                status="failed",
                error="rate limiter timeout",
                duration_seconds=time.monotonic() - start,
                retries=attempt,
            )

        try:
            # Set env var for skipping image generation
            old_val = os.environ.get("WORKSHEET_SKIP_ASSET_GEN")
            if skip_images:
                os.environ["WORKSHEET_SKIP_ASSET_GEN"] = "1"

            try:
                artifacts_dir = str(
                    Path(output_dir) / "artifacts" / input_path.stem
                )
                Path(artifacts_dir).mkdir(parents=True, exist_ok=True)

                pdf_path = pipeline_fn(
                    input_path=str(input_path),
                    profile_path=profile_path,
                    theme_id=theme_id,
                    output_dir=output_dir,
                    artifacts_dir=artifacts_dir,
                    index_results=False,
                )

                output_path: str | None = None
                rag_index_payload: dict[str, Any] | None = None
                if isinstance(pdf_path, str):
                    output_path = pdf_path
                elif hasattr(pdf_path, "model_dump"):
                    rag_index_payload = dict(pdf_path.model_dump())
                    pdf_paths = rag_index_payload.get("pdf_paths")
                    if isinstance(pdf_paths, list) and pdf_paths:
                        first_path = pdf_paths[0]
                        if isinstance(first_path, str):
                            output_path = first_path
                else:
                    raise TypeError(
                        "Pipeline returned unsupported result type: "
                        f"{type(pdf_path).__name__}"
                    )

                return FileResult(
                    input_path=str(input_path),
                    status="success",
                    output_path=output_path,
                    rag_index_payload=rag_index_payload,
                    duration_seconds=time.monotonic() - start,
                    retries=attempt,
                )
            finally:
                # Restore env var
                if skip_images:
                    if old_val is None:
                        os.environ.pop("WORKSHEET_SKIP_ASSET_GEN", None)
                    else:
                        os.environ["WORKSHEET_SKIP_ASSET_GEN"] = old_val

        except Exception as e:
            if attempt < max_retries:
                # Exponential backoff: 5s, 10s, 20s + jitter
                backoff = min(5 * (2 ** attempt), 60) + random.uniform(0, 1)
                logger.warning(
                    f"  Retry {attempt + 1}/{max_retries} for "
                    f"{input_path.name}: {e}"
                )
                # Sleep in 1s increments to check shutdown
                end_sleep = time.monotonic() + backoff
                while time.monotonic() < end_sleep:
                    if shutdown_event.is_set():
                        return FileResult(
                            input_path=str(input_path),
                            status="skipped",
                            error="shutdown during retry backoff",
                            duration_seconds=time.monotonic() - start,
                            retries=attempt,
                        )
                    time.sleep(min(1.0, end_sleep - time.monotonic()))
            else:
                return FileResult(
                    input_path=str(input_path),
                    status="failed",
                    error=str(e),
                    duration_seconds=time.monotonic() - start,
                    retries=attempt,
                )

    # Should not reach here, but just in case
    return FileResult(
        input_path=str(input_path),
        status="failed",
        error="unexpected: exhausted retries",
        duration_seconds=time.monotonic() - start,
        retries=max_retries,
    )


@click.command()
@click.option(
    "--input-dir", required=True, help="Directory containing worksheet images"
)
@click.option(
    "--profile", "profile_path", required=True, help="Path to learner profile YAML"
)
@click.option("--theme", "theme_id", default="space", help="Theme name")
@click.option(
    "--output", "output_dir", default="./output", help="Output directory"
)
@click.option(
    "--workers",
    default=2,
    type=int,
    help="Number of concurrent workers (default: 2)",
)
@click.option(
    "--max-retries",
    default=2,
    type=int,
    help="Max retries per file on failure (default: 2)",
)
@click.option(
    "--force", is_flag=True, help="Reprocess even if output already exists"
)
@click.option(
    "--dry-run", is_flag=True, help="List files without processing"
)
@click.option(
    "--no-images",
    is_flag=True,
    help="Skip AI image generation (text-only PDFs)",
)
@click.option(
    "--no-recursive",
    is_flag=True,
    help="Don't search subdirectories for images",
)
@click.option(
    "--rpm",
    default=4,
    type=int,
    help="Rate limit: max pipeline runs per minute (default: 4)",
)
def batch(
    input_dir: str,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    workers: int,
    max_retries: int,
    force: bool,
    dry_run: bool,
    no_images: bool,
    no_recursive: bool,
    rpm: int,
) -> None:
    """Process all worksheet images in a directory."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # 1. Collect input files
    files = collect_input_files(input_dir, recursive=not no_recursive)
    if not files:
        click.echo(f"No image files found in {input_dir}")
        sys.exit(0)

    click.echo(f"Found {len(files)} image file(s) in {input_dir}")

    # 2. Load manifest and filter already-processed files
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path / "batch_manifest.json"

    if not force:
        existing = load_manifest(output_dir)
        unprocessed = []
        for f in files:
            entry = existing.get(f.name)
            if entry and Path(entry.get("output", "")).exists():
                logger.info(f"  Skipping (already processed): {f.name}")
            else:
                unprocessed.append(f)
        files = unprocessed

    if not files:
        click.echo("All files already processed. Use --force to reprocess.")
        sys.exit(0)

    # 3. Dry run
    if dry_run:
        click.echo(f"\nDry run — {len(files)} file(s) would be processed:")
        for f in files:
            click.echo(f"  {f}")
        sys.exit(0)

    # 4. Process files
    click.echo(
        f"\nProcessing {len(files)} file(s) with {workers} worker(s), "
        f"RPM limit: {rpm}"
    )
    if no_images:
        click.echo("  Image generation disabled (--no-images)")

    rate_limiter = RateLimiter(rpm=rpm)
    shutdown_event = threading.Event()
    manifest_lock = threading.Lock()
    tracker = ProgressTracker(len(files))
    results: list[FileResult] = []
    results_lock = threading.Lock()

    # Install SIGINT handler for graceful shutdown
    original_handler = signal.getsignal(signal.SIGINT)

    def _handle_sigint(signum: int, frame: object) -> None:
        click.echo("\nShutdown requested — finishing running tasks...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_sigint)

    batch_start = time.monotonic()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_single_file,
                    f,
                    profile_path,
                    theme_id,
                    output_dir,
                    max_retries,
                    rate_limiter,
                    shutdown_event,
                    no_images,
                ): f
                for f in files
            }

            for future in as_completed(futures):
                input_file = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = FileResult(
                        input_path=str(input_file),
                        status="failed",
                        error=f"unexpected: {e}",
                    )

                with results_lock:
                    results.append(result)

                # Update manifest on success
                if result.status == "success" and result.output_path:
                    save_manifest_entry(
                        manifest_path,
                        input_file.name,
                        {
                            "output": result.output_path,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "duration": result.duration_seconds,
                        },
                        manifest_lock,
                    )

                # Print progress
                progress = tracker.record(result)
                status_icon = (
                    "ok" if result.status == "success"
                    else "FAIL" if result.status == "failed"
                    else "skip"
                )
                click.echo(
                    f"  [{status_icon}] {input_file.name} "
                    f"({result.duration_seconds:.1f}s) — {progress}"
                )
                if result.status == "failed" and result.error:
                    click.echo(f"       Error: {result.error}")

    finally:
        signal.signal(signal.SIGINT, original_handler)

    indexed_count = _index_completed_runs(results)

    # 5. Summary report
    batch_duration = time.monotonic() - batch_start
    report = generate_report(results, batch_duration)

    report_path = output_path / "batch_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    click.echo(f"\nBatch complete in {report['duration_human']}:")
    click.echo(
        f"  {report['success']} succeeded, "
        f"{report['failed']} failed, "
        f"{report['skipped']} skipped"
    )
    if indexed_count:
        click.echo(f"  {indexed_count} run(s) indexed into RAG store")
    click.echo(f"  Report: {report_path}")

    # Save manifest metadata
    with manifest_lock:
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
        else:
            data = {}
        data["profile"] = profile_path
        data["theme"] = theme_id
        data["last_run"] = datetime.now(UTC).isoformat()
        manifest_path.write_text(json.dumps(data, indent=2))

    sys.exit(1 if report["failed"] > 0 else 0)


def _index_completed_runs(results: list[FileResult]) -> int:
    """Index successful batch runs from the main thread only."""
    artifacts_to_index = [
        result.rag_index_payload
        for result in results
        if result.status == "success" and result.rag_index_payload
    ]
    if not artifacts_to_index:
        return 0

    try:
        from transform import rag_available
    except ImportError:
        return 0

    if not rag_available():
        logger.info("Skipping RAG indexing after batch: backend unavailable")
        return 0

    try:
        from rag.indexer import index_run
    except ImportError:
        logger.warning("Skipping RAG indexing after batch: rag.indexer unavailable")
        return 0

    logger.info("Indexing %s completed run(s) into RAG store...", len(artifacts_to_index))
    indexed_count = 0
    for payload in artifacts_to_index:
        try:
            index_run(**payload)
            indexed_count += 1
        except Exception as exc:
            source_hash = payload.get("source_image_hash", "unknown")
            logger.warning("RAG indexing failed for %s: %s", source_hash, exc)
    return indexed_count


if __name__ == "__main__":
    batch()
