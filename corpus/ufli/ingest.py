"""Embed and index UFLI curriculum into ChromaDB, with CLI entry point."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import click

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from rag.embeddings import embed_text
from rag.store import CURRICULUM, add_document, get_or_create_collection, get_store

logger = logging.getLogger(__name__)

# Lesson-to-grade mapping based on UFLI scope and sequence.
_GRADE_RANGES: list[tuple[str, str, str]] = [
    # (start, end, grade)  — for numeric lessons
    ("1", "34", "K"),
    ("35", "64", "1"),
    ("65", "94", "1"),
    ("95", "128", "2"),
]

_ALPHA_LESSONS = set("ABCDEFGHIJ")


def _derive_grade(lesson_id: str) -> str:
    """Derive grade level from UFLI lesson ID."""
    if lesson_id.upper() in _ALPHA_LESSONS:
        return "K"
    try:
        num = int(lesson_id)
    except ValueError:
        return "K"
    for start, end, grade in _GRADE_RANGES:
        if int(start) <= num <= int(end):
            return grade
    return "2"


def ingest_curriculum(
    data_dir: str = "data/ufli",
    db_path: str = "vector_store",
) -> int:
    """Read normalized.jsonl, embed with Gemini, index into Chroma.

    Returns number of lessons indexed.
    """
    normalized_path = Path(data_dir) / "normalized.jsonl"
    if not normalized_path.exists():
        logger.error("No normalized.jsonl found in %s — run extract first", data_dir)
        return 0

    store = get_store(db_path)
    collection = get_or_create_collection(store, CURRICULUM)
    indexed = 0

    for line in normalized_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        lesson_id = rec["lesson_id"]

        # Combine all text sources for the richest embedding
        parts = [rec.get("slide_text", "")]
        if rec.get("decodable_text"):
            parts.append(rec["decodable_text"])
        if rec.get("home_practice_text"):
            parts.append(rec["home_practice_text"])
        if rec.get("additional_text"):
            parts.append(rec["additional_text"])
        combined_text = "\n\n".join(p for p in parts if p)

        if not combined_text.strip():
            logger.warning("No text content for lesson %s, skipping", lesson_id)
            continue

        doc_id = f"curriculum_ufli_{lesson_id}"
        grade_level = _derive_grade(lesson_id)

        try:
            result = embed_text(combined_text[:2000], task_type="RETRIEVAL_DOCUMENT")
        except Exception:
            logger.exception("Embedding failed for lesson %s", lesson_id)
            continue

        metadata = {
            "source": "ufli_toolbox",
            "lesson_id": lesson_id,
            "lesson_group": rec.get("lesson_group", ""),
            "concept": rec.get("concept", ""),
            "slide_count": rec.get("slide_count", 0),
            "grade_level": grade_level,
            "has_decodable": bool(rec.get("decodable_text")),
            "has_home_practice": bool(rec.get("home_practice_text")),
            "has_additional": bool(rec.get("additional_text")),
            "indexed_at": datetime.now(tz=UTC).isoformat(),
        }

        add_document(
            collection,
            doc_id=doc_id,
            embedding=result.values,
            metadata=metadata,
            document=combined_text[:1000],
        )
        indexed += 1
        logger.info("Indexed lesson %s: %s", lesson_id, rec.get("concept", ""))

    logger.info("Indexed %d lessons into curriculum collection", indexed)
    return indexed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool) -> None:
    """UFLI Foundations Toolbox corpus management."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@cli.command()
@click.option("--data-dir", default="data/ufli", help="Data directory.")
def crawl(data_dir: str) -> None:
    """Crawl UFLI Toolbox and generate manifest.jsonl."""
    from corpus.ufli.crawl import crawl_toolbox

    path = crawl_toolbox(output_dir=data_dir)
    click.echo(f"Manifest written to {path}")


@cli.command()
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option("--delay", default=1.5, help="Seconds between downloads.")
def acquire(data_dir: str, delay: float) -> None:
    """Download resources from manifest."""
    from corpus.ufli.acquire import acquire_resources

    count = acquire_resources(data_dir=data_dir, delay=delay)
    click.echo(f"Downloaded {count} files")


@cli.command()
@click.option("--data-dir", default="data/ufli", help="Data directory.")
def extract(data_dir: str) -> None:
    """Extract text from downloaded resources."""
    from corpus.ufli.extract import extract_all

    results = extract_all(data_dir=data_dir)
    click.echo(f"Extracted {len(results)} lessons")


@cli.command()
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option("--db-path", default="vector_store", help="ChromaDB path.")
def index(data_dir: str, db_path: str) -> None:
    """Embed and index extracted lessons into ChromaDB."""
    count = ingest_curriculum(data_dir=data_dir, db_path=db_path)
    click.echo(f"Indexed {count} lessons")


@cli.command(name="run-all")
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option("--db-path", default="vector_store", help="ChromaDB path.")
@click.option("--delay", default=1.5, help="Seconds between downloads.")
def run_all(data_dir: str, db_path: str, delay: float) -> None:
    """Run full pipeline: crawl -> acquire -> extract -> index."""
    from corpus.ufli.acquire import acquire_resources
    from corpus.ufli.crawl import crawl_toolbox
    from corpus.ufli.extract import extract_all

    click.echo("Step 1/4: Crawling UFLI Toolbox...")
    crawl_toolbox(output_dir=data_dir)

    click.echo("Step 2/4: Downloading resources...")
    acquire_resources(data_dir=data_dir, delay=delay)

    click.echo("Step 3/4: Extracting text...")
    extract_all(data_dir=data_dir)

    click.echo("Step 4/4: Embedding and indexing...")
    count = ingest_curriculum(data_dir=data_dir, db_path=db_path)
    click.echo(f"Done. Indexed {count} lessons into curriculum collection.")


if __name__ == "__main__":
    cli()
