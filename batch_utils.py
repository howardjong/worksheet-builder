"""Shared utilities for batch worksheet processing."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}


@dataclass
class FileResult:
    """Result of processing a single file."""

    input_path: str
    status: Literal["success", "failed", "skipped"]
    output_path: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "status": self.status,
            "output_path": self.output_path,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 2),
            "retries": self.retries,
        }


class RateLimiter:
    """Thread-safe token-bucket rate limiter using a sliding window.

    Ensures no more than `rpm` calls per 60-second window across all threads.
    Workers call limiter.acquire() before each pipeline run and block until
    a slot is available.
    """

    def __init__(self, rpm: int = 4) -> None:
        self._rpm = rpm
        self._timestamps: deque[float] = deque()
        self._condition = threading.Condition()

    def acquire(self, timeout: float = 120.0) -> bool:
        """Block until a rate limit slot is available.

        Returns True if acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout

        with self._condition:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    return False

                # Evict timestamps older than 60s
                window_start = now - 60.0
                while self._timestamps and self._timestamps[0] < window_start:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._rpm:
                    self._timestamps.append(now)
                    return True

                # Wait until the oldest timestamp expires
                wait_time = self._timestamps[0] - window_start
                wait_time = min(wait_time + 0.1, deadline - now)
                if wait_time <= 0:
                    return False
                self._condition.wait(timeout=wait_time)


class ProgressTracker:
    """Thread-safe progress tracker with ETA."""

    def __init__(self, total: int) -> None:
        self._total = total
        self._lock = threading.Lock()
        self._completed = 0
        self._success = 0
        self._failed = 0
        self._skipped = 0
        self._start_time = time.monotonic()

    def record(self, result: FileResult) -> str:
        """Record a result and return a formatted progress line."""
        with self._lock:
            self._completed += 1
            if result.status == "success":
                self._success += 1
            elif result.status == "failed":
                self._failed += 1
            else:
                self._skipped += 1

            elapsed = time.monotonic() - self._start_time
            remaining = self._total - self._completed
            if self._completed > 0:
                avg = elapsed / self._completed
                eta_seconds = remaining * avg
                eta = _format_duration(eta_seconds)
            else:
                eta = "..."

            parts = []
            if self._success:
                parts.append(f"{self._success} ok")
            if self._failed:
                parts.append(f"{self._failed} fail")
            if self._skipped:
                parts.append(f"{self._skipped} skip")
            status_str = ", ".join(parts) if parts else "starting"

            return (
                f"[{self._completed}/{self._total}] "
                f"{status_str} | ETA: {eta}"
            )

    @property
    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total": self._total,
                "success": self._success,
                "failed": self._failed,
                "skipped": self._skipped,
                "duration_seconds": round(
                    time.monotonic() - self._start_time, 2
                ),
            }


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs:02d}s"


def collect_input_files(input_dir: str, recursive: bool = True) -> list[Path]:
    """Collect image files from a directory, sorted by name."""
    root = Path(input_dir)
    if not root.is_dir():
        return []

    files: list[Path] = []
    if recursive:
        for ext in IMAGE_EXTENSIONS:
            files.extend(root.rglob(f"*{ext}"))
    else:
        for ext in IMAGE_EXTENSIONS:
            files.extend(root.glob(f"*{ext}"))

    return sorted(set(files))


def load_manifest(output_dir: str) -> dict[str, dict[str, str]]:
    """Load the batch manifest from the output directory."""
    manifest_path = Path(output_dir) / "batch_manifest.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text())
            files: dict[str, dict[str, str]] = data.get("files", {})
            return files
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}


def save_manifest_entry(
    manifest_path: Path,
    filename: str,
    entry: dict[str, Any],
    lock: threading.Lock,
) -> None:
    """Thread-safe atomic update of a single manifest entry."""
    with lock:
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        if "files" not in data:
            data["files"] = {}
        data["files"][filename] = entry
        manifest_path.write_text(json.dumps(data, indent=2))


def generate_report(results: list[FileResult], duration: float) -> dict[str, Any]:
    """Generate a summary report from batch results."""
    success = [r for r in results if r.status == "success"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]

    report: dict[str, Any] = {
        "total": len(results),
        "success": len(success),
        "failed": len(failed),
        "skipped": len(skipped),
        "duration_seconds": round(duration, 2),
        "duration_human": _format_duration(duration),
    }

    if failed:
        report["failures"] = [
            {"file": r.input_path, "error": r.error} for r in failed
        ]

    return report
