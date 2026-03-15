"""Crawl UFLI Foundations Toolbox and produce a lesson manifest."""

from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://ufli.education.ufl.edu/foundations/toolbox"

# Actual lesson group slugs from the UFLI Toolbox page (verified 2026-03-13).
LESSON_GROUP_SLUGS: list[str] = [
    "a-j",
    "1-34",
    "35-41",
    "42-53",
    "54-62",
    "63-68",
    "69-76",
    "77-83",
    "84-88",
    "89-94",
    "95-98",
    "99-106",
    "107-110",
    "111-118",
    "119-128",
]

# Column header text that should be skipped (not lesson rows).
_HEADER_TEXTS = {"lesson", "concept", "slide deck", "decodable passages"}


def _normalize_lesson_id(raw: str) -> str:
    """Normalize lesson IDs like 'Getting Ready A' to just 'A'."""
    m = re.match(r"Getting Ready\s+([A-J])", raw, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return raw


def _extract_gslides_id(url: str) -> str | None:
    """Extract Google Slides presentation ID from a URL.

    Handles both direct docs.google.com links and SafeLinks-wrapped URLs.
    """
    # Try direct URL first.
    m = re.search(r"/presentation/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)

    # SafeLinks wrapping: the real URL is in the ?url= query parameter.
    if "safelinks.protection.outlook.com" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        inner_url = qs.get("url", [""])[0]
        if inner_url:
            m = re.search(r"/presentation/d/([a-zA-Z0-9_-]+)", inner_url)
            if m:
                return m.group(1)

    return None


def _parse_lesson_rows(page: Any, lesson_group: str) -> list[dict[str, Any]]:
    """Parse table rows on a lesson group page into manifest records.

    Lessons 1-128 have 6 columns: Lesson | Concept | Slide Deck | Decodable |
    Home Practice | Additional Activities.

    Lessons A-J (Getting Ready) have only 2 columns: Lesson | Slide Deck, and
    the row header says 'Getting Ready A' etc.
    """
    records: list[dict[str, Any]] = []

    rows = page.query_selector_all("table tr")
    for row in rows:
        # Lesson number lives in a <th> rowheader element.
        # Column header rows also use <th> — skip them by text.
        header = row.query_selector("th")
        if not header:
            continue
        raw_header = (header.inner_text() or "").strip()
        if not raw_header or raw_header.lower() in _HEADER_TEXTS:
            continue

        lesson_id = _normalize_lesson_id(raw_header)

        # Concept is in the first <td> cell (absent for A-J pages).
        # On A-J pages the first <td> is the slide deck column (contains
        # <a> links); on 1-128 pages the first <td> is plain concept text.
        cells = row.query_selector_all("td")
        concept = ""
        if cells and not cells[0].query_selector("a[href]"):
            concept = (cells[0].inner_text() or "").strip()

        # Classify every link in the row by its visible text.
        links = row.query_selector_all("a[href]")
        resources: dict[str, str] = {}
        for link in links:
            href = link.get_attribute("href") or ""
            text = (link.inner_text() or "").strip().lower()

            if "powerpoint" in text or href.endswith(".pptx"):
                resources["slide_deck_pptx"] = href
            elif "google slide" in text or "docs.google.com/presentation" in href:
                sid = _extract_gslides_id(href)
                if sid:
                    resources["slide_deck_gslides_export"] = (
                        f"https://docs.google.com/presentation/d/{sid}/export/pptx"
                    )
            elif "decodable" in text:
                resources["decodable_passage_pdf"] = href
            elif "home" in text:
                resources["home_practice_pdf"] = href
            elif href.endswith(".pdf"):
                resources["additional_pdf"] = href

        if not resources:
            continue

        records.append(
            {
                "lesson_id": lesson_id,
                "lesson_group": lesson_group,
                "concept": concept,
                "resources": resources,
                "status": "pending",
            }
        )

    return records


_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds; doubles each retry
_PAGE_DELAY = 2.0  # polite delay between page navigations


def _goto_with_retry(page: Any, url: str, max_retries: int = _MAX_RETRIES) -> bool:
    """Navigate to a URL with retries and exponential backoff.

    Returns True if the page loaded and a table was found.
    """
    for attempt in range(max_retries):
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_selector("table", timeout=15000)
            return True
        except Exception:
            wait = _RETRY_BACKOFF * (2**attempt)
            if attempt < max_retries - 1:
                logger.warning(
                    "Attempt %d/%d failed for %s, retrying in %.0fs",
                    attempt + 1,
                    max_retries,
                    url,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "All %d attempts failed for %s, skipping", max_retries, url
                )
    return False


def crawl_toolbox(
    output_dir: str = "data/ufli",
    base_url: str = BASE_URL,
    slugs: list[str] | None = None,
) -> Path:
    """Crawl UFLI Toolbox lesson group pages and write manifest.jsonl.

    Returns path to the manifest file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.jsonl"

    existing_ids: set[str] = set()
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                existing_ids.add(rec["lesson_id"])
            except (json.JSONDecodeError, KeyError):
                logger.warning("Skipping malformed manifest line: %s", line[:80])

    group_slugs = slugs or LESSON_GROUP_SLUGS
    new_count = 0

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            msg = str(exc)
            if "Executable doesn't exist" in msg or "executable" in msg.lower():
                logger.error(
                    "Chromium not installed. Run: playwright install chromium"
                )
            raise

        try:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )
            page = context.new_page()

            for i, slug in enumerate(group_slugs):
                url = f"{base_url}/{slug}"
                logger.info("Crawling %s (%d/%d)", url, i + 1, len(group_slugs))

                if not _goto_with_retry(page, url):
                    continue

                try:
                    records = _parse_lesson_rows(page, lesson_group=slug)
                except Exception:
                    logger.exception("Failed to parse rows on %s, skipping", url)
                    continue

                # Write new records immediately so progress survives crashes
                new_records = [
                    r for r in records if r["lesson_id"] not in existing_ids
                ]
                if new_records:
                    with manifest_path.open("a") as f:
                        for rec in new_records:
                            f.write(json.dumps(rec) + "\n")
                            existing_ids.add(rec["lesson_id"])
                            new_count += 1

                logger.info(
                    "Found %d lessons on %s (%d new)",
                    len(records), slug, len(new_records),
                )

                # Polite delay with jitter between pages
                if i < len(group_slugs) - 1:
                    jitter = random.uniform(0, _PAGE_DELAY * 0.5)  # noqa: S311
                    time.sleep(_PAGE_DELAY + jitter)
        finally:
            browser.close()

    total = len(existing_ids)
    logger.info("Manifest has %d total lessons (%d new)", total, new_count)
    return manifest_path
