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

from corpus.ufli.grade_levels import derive_grade
from rag.embeddings import embed_text
from rag.store import CURRICULUM, add_document, get_or_create_collection, get_store

logger = logging.getLogger(__name__)


def _derive_grade(lesson_id: str) -> str:
    """Backward-compatible wrapper for UFLI grade derivation."""
    return derive_grade(lesson_id)


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


@cli.command(name="build-audio")
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option(
    "--lesson-set",
    type=click.Choice(["pilot_micro", "pilot_rep", "all", "range"]),
    default="pilot_micro",
    show_default=True,
    help="Lesson selection mode.",
)
@click.option("--lesson", "lesson_id", default=None, help="Specific numeric lesson to build.")
@click.option("--lesson-min", default=1, help="Minimum numeric lesson for --lesson-set range.")
@click.option("--lesson-max", default=128, help="Maximum numeric lesson for --lesson-set range.")
def build_audio(
    data_dir: str,
    lesson_set: str,
    lesson_id: str | None,
    lesson_min: int,
    lesson_max: int,
) -> None:
    """Build lesson audio bundles and audio companion manifests."""
    from corpus.ufli.audio_companion import build_audio_companion_manifests

    bundles = build_audio_companion_manifests(
        data_dir=data_dir,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
    )
    click.echo(f"Built {len(bundles)} audio lesson bundles")


@cli.command(name="validate-audio")
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option(
    "--lesson-set",
    type=click.Choice(["pilot_micro", "pilot_rep", "all", "range"]),
    default="pilot_micro",
    show_default=True,
    help="Lesson selection mode.",
)
@click.option("--lesson", "lesson_id", default=None, help="Specific numeric lesson to validate.")
@click.option("--lesson-min", default=1, help="Minimum numeric lesson for --lesson-set range.")
@click.option("--lesson-max", default=128, help="Maximum numeric lesson for --lesson-set range.")
def validate_audio(
    data_dir: str,
    lesson_set: str,
    lesson_id: str | None,
    lesson_min: int,
    lesson_max: int,
) -> None:
    """Validate built lesson audio bundles before synthesis."""
    from corpus.ufli.audio_companion import validate_audio_companion

    report = validate_audio_companion(
        data_dir=data_dir,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
    )
    click.echo(
        "Audio validation summary: "
        f"bundles={report.bundle_count} "
        f"issues={report.issue_count} "
        f"passed={report.passed}"
    )
    for issue in report.issues[:25]:
        location = issue.segment_id or issue.bundle_key
        click.echo(f"- {location} [{issue.code}] {issue.message}")
    if not report.passed:
        raise click.ClickException(
            f"Audio validation failed with {report.issue_count} issues."
        )


@cli.command(name="generate-audio")
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option(
    "--lesson-set",
    type=click.Choice(["pilot_micro", "pilot_rep", "all", "range"]),
    default="pilot_micro",
    show_default=True,
    help="Lesson selection mode.",
)
@click.option("--lesson", "lesson_id", default=None, help="Specific numeric lesson to generate.")
@click.option("--lesson-min", default=1, help="Minimum numeric lesson for --lesson-set range.")
@click.option("--lesson-max", default=128, help="Maximum numeric lesson for --lesson-set range.")
@click.option(
    "--voice-profile",
    default=None,
    help="Named voice profile from data/ufli/companion/voice_profiles.yaml.",
)
@click.option(
    "--dry-run/--live",
    default=True,
    help="Keep generation offline by default; use --live to call ElevenLabs.",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Regenerate files even if they already exist.",
)
@click.option(
    "--review-packet/--no-review-packet",
    default=False,
    help="Write a timestamped pilot review packet under data/ufli/companion/pilots/.",
)
def generate_audio(
    data_dir: str,
    lesson_set: str,
    lesson_id: str | None,
    lesson_min: int,
    lesson_max: int,
    voice_profile: str | None,
    dry_run: bool,
    force: bool,
    review_packet: bool,
) -> None:
    """Generate ElevenLabs audio for lesson bundles."""
    from corpus.ufli.audio_companion import generate_audio_companion

    summary = generate_audio_companion(
        data_dir=data_dir,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
        voice_profile=voice_profile,
        dry_run=dry_run,
        force=force,
        review_packet=review_packet,
    )
    click.echo(
        "Audio generation summary: "
        f"planned={summary['planned']} "
        f"generated={summary['generated']} "
        f"skipped={summary['skipped']} "
        f"review_packet_dir={summary['review_packet_dir'] or 'n/a'}"
    )
    for profile_name, estimate in summary["voice_profiles"].items():
        click.echo(
            f"Voice {profile_name}: clips={estimate['clip_count']} "
            f"chars={estimate['character_count']} "
            f"costs={estimate['projected_costs_usd']}"
        )


@cli.command(name="index-audio")
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option("--db-path", default="vector_store", help="ChromaDB path.")
@click.option(
    "--lesson-set",
    type=click.Choice(["pilot_micro", "pilot_rep", "all", "range"]),
    default="pilot_micro",
    show_default=True,
    help="Lesson selection mode.",
)
@click.option("--lesson", "lesson_id", default=None, help="Specific numeric lesson to index.")
@click.option("--lesson-min", default=1, help="Minimum numeric lesson for --lesson-set range.")
@click.option("--lesson-max", default=128, help="Maximum numeric lesson for --lesson-set range.")
@click.option(
    "--voice-profile",
    default=None,
    help="Restrict indexing to one generated voice profile.",
)
@click.option(
    "--granularity",
    type=click.Choice(["clips", "lessons", "both"]),
    default="clips",
    show_default=True,
    help="Indexing granularity. Only clips is implemented in Stage 1.",
)
def index_audio(
    data_dir: str,
    db_path: str,
    lesson_set: str,
    lesson_id: str | None,
    lesson_min: int,
    lesson_max: int,
    voice_profile: str | None,
    granularity: str,
) -> None:
    """Index generated audio companion transcripts into ChromaDB."""
    from corpus.ufli.audio_companion import index_audio_companion

    count = index_audio_companion(
        data_dir=data_dir,
        db_path=db_path,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
        voice_profile=voice_profile,
        granularity=granularity,
    )
    click.echo(f"Indexed {count} audio companion clips")


@cli.command(name="judge-audio")
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option(
    "--lesson-set",
    type=click.Choice(["pilot_micro", "pilot_rep", "all", "range"]),
    default="pilot_micro",
    show_default=True,
    help="Lesson selection mode.",
)
@click.option("--lesson", "lesson_id", default=None, help="Specific numeric lesson to judge.")
@click.option("--lesson-min", default=1, help="Minimum numeric lesson for --lesson-set range.")
@click.option("--lesson-max", default=128, help="Maximum numeric lesson for --lesson-set range.")
@click.option(
    "--voice-profile",
    default=None,
    help="Restrict judging to one generated voice profile.",
)
@click.option(
    "--judge-model",
    default="gemini-3-flash-preview",
    show_default=True,
    help="Gemini model used for transcript/script judging.",
)
@click.option(
    "--output-dir",
    default=None,
    help="Optional output root. Defaults to data/ufli/companion/evals.",
)
@click.option(
    "--clip-limit",
    default=None,
    type=int,
    help="Optional limit for a smaller smoke run.",
)
def judge_audio(
    data_dir: str,
    lesson_set: str,
    lesson_id: str | None,
    lesson_min: int,
    lesson_max: int,
    voice_profile: str | None,
    judge_model: str,
    output_dir: str | None,
    clip_limit: int | None,
) -> None:
    """Run Gemini LLM-judge eval over generated audio companion clips."""
    from corpus.ufli.audio_judge import judge_audio_companion

    summary = judge_audio_companion(
        data_dir=data_dir,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
        voice_profile=voice_profile,
        judge_model=judge_model,
        output_dir=output_dir,
        clip_limit=clip_limit,
    )
    click.echo(
        "Audio judge summary: "
        f"clips={summary.clip_count} "
        f"blockers={summary.blocker_count} "
        f"pilot_ready={summary.pilot_ready} "
        f"report_dir={summary.output_dir}"
    )


@cli.command()
@click.option("--data-dir", default="data/ufli", help="Data directory.")
@click.option("--db-path", default="vector_store", help="ChromaDB path.")
@click.option("--output-dir", default="data/ufli/audit", help="Audit report root directory.")
@click.option("--sample-size", default=20, help="Manual review sample size.")
@click.option("--benchmark-size", default=50, help="Retrieval benchmark sample size.")
@click.option("--seed", default=42, help="Deterministic sampling seed.")
@click.option(
    "--use-ai-judge/--no-ai-judge",
    default=False,
    help="Advisory flag only; audit remains offline.",
)
def audit(
    data_dir: str,
    db_path: str,
    output_dir: str,
    sample_size: int,
    benchmark_size: int,
    seed: int,
    use_ai_judge: bool,
) -> None:
    """Run an offline multimodal corpus audit and write timestamped reports."""
    from corpus.ufli.audit import run_audit

    summary = run_audit(
        data_dir=data_dir,
        db_path=db_path,
        output_dir=output_dir,
        sample_size=sample_size,
        benchmark_size=benchmark_size,
        seed=seed,
        use_ai_judge=use_ai_judge,
    )
    click.echo(f"Audit written to {summary.output_dir}")


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
