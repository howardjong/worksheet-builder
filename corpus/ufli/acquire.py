"""Download UFLI Toolbox resources from the crawl manifest."""

from __future__ import annotations

import json
import logging
import socket
import ssl
import time
import urllib.request
from pathlib import Path

import certifi

logger = logging.getLogger(__name__)

ALL_RESOURCE_TYPES = [
    "slide_deck_pptx",
    "slide_deck_gslides_export",
    "decodable_passage_pdf",
    "home_practice_pdf",
    "additional_pdf",
]

_EXT_MAP: dict[str, str] = {
    "slide_deck_pptx": ".pptx",
    "slide_deck_gslides_export": ".pptx",
    "decodable_passage_pdf": ".pdf",
    "home_practice_pdf": ".pdf",
    "additional_pdf": ".pdf",
}


_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds; doubles each retry
_DOWNLOAD_TIMEOUT = 60  # seconds


_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _download_with_retry(
    url: str, dest: str, lesson_id: str, rtype: str
) -> bool:
    """Download a file with retries and exponential backoff."""
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(url)  # noqa: S310
            with urllib.request.urlopen(req, context=_SSL_CTX) as resp, open(dest, "wb") as f:  # noqa: S310
                while chunk := resp.read(8192):
                    f.write(chunk)
            return True
        except Exception as exc:
            wait = _RETRY_BACKOFF * (2**attempt)
            if attempt < _MAX_RETRIES - 1:
                logger.warning(
                    "Attempt %d/%d failed for %s lesson %s (%s), retrying in %.0fs",
                    attempt + 1,
                    _MAX_RETRIES,
                    rtype,
                    lesson_id,
                    exc,
                    wait,
                )
                time.sleep(wait)
                # Clean up partial file
                partial = Path(dest)
                if partial.exists():
                    partial.unlink()
            else:
                logger.error(
                    "All %d attempts failed for %s lesson %s: %s",
                    _MAX_RETRIES,
                    rtype,
                    lesson_id,
                    exc,
                )
                # Clean up partial file
                partial = Path(dest)
                if partial.exists():
                    partial.unlink()
    return False


def acquire_resources(
    data_dir: str = "data/ufli",
    resource_types: list[str] | None = None,
    delay: float = 1.5,
) -> int:
    """Download resources listed in manifest.jsonl.

    Args:
        data_dir: Directory containing manifest.jsonl; raw/ created underneath.
        resource_types: Which resource types to download. Default: all available.
        delay: Seconds to wait between downloads (polite rate limiting).

    Returns:
        Number of files downloaded.
    """
    base = Path(data_dir)
    manifest_path = base / "manifest.jsonl"
    if not manifest_path.exists():
        logger.error("No manifest.jsonl found in %s — run crawl first", data_dir)
        return 0

    # Set global socket timeout so urlretrieve doesn't hang indefinitely
    socket.setdefaulttimeout(_DOWNLOAD_TIMEOUT)

    types = resource_types or ALL_RESOURCE_TYPES
    downloaded = 0
    lines = manifest_path.read_text().splitlines()
    total = len([ln for ln in lines if ln.strip()])

    updated_records: list[dict[str, object]] = []

    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        lesson_id = rec["lesson_id"]
        concept = rec.get("concept", "")
        resources = rec.get("resources", {})

        lesson_dir = base / "raw" / lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)

        acquired_types: list[str] = []
        had_failure = False
        for rtype in types:
            url = resources.get(rtype)
            if not url:
                continue

            # Skip Google Slides export if we already have the direct PPTX
            if rtype == "slide_deck_gslides_export":
                direct_pptx = lesson_dir / "slide_deck_pptx.pptx"
                if direct_pptx.exists():
                    continue

            ext = _EXT_MAP.get(rtype, ".bin")
            dest = lesson_dir / f"{rtype}{ext}"
            if dest.exists():
                acquired_types.append(rtype)
                continue

            logger.info(
                "Downloading lesson %s/%d: %s [%s]",
                lesson_id,
                total,
                concept,
                rtype,
            )
            success = _download_with_retry(url, str(dest), lesson_id, rtype)
            if success:
                acquired_types.append(rtype)
                downloaded += 1
            else:
                had_failure = True
            time.sleep(delay)

        if acquired_types and not had_failure:
            rec["status"] = "acquired"
        elif had_failure:
            rec["status"] = "partial"
        updated_records.append(rec)

    # Rewrite manifest with updated statuses
    with manifest_path.open("w") as f:
        for rec in updated_records:
            f.write(json.dumps(rec) + "\n")

    logger.info("Downloaded %d files", downloaded)
    return downloaded
