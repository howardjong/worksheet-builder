"""Backfill existing pipeline artifacts into the RAG vector store."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import click

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from adapt.schema import AdaptedActivityModel
from extract.schema import SourceWorksheetModel
from rag.indexer import index_run
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)

_ARTIFACT_INDEX_RE = re.compile(r"_(\d+)\.json$")
_PDF_INDEX_RE = re.compile(r"_(\d+)of(\d+)\.pdf$")


def backfill(
    artifacts_dir: str,
    output_dir: str,
    db_path: str = "vector_store",
) -> int:
    """Index saved artifact directories into the RAG vector store."""
    artifacts_root = Path(artifacts_dir)
    output_root = Path(output_dir)

    if not artifacts_root.exists():
        raise FileNotFoundError(f"Artifacts directory not found: {artifacts_root}")
    if not output_root.exists():
        raise FileNotFoundError(f"Output directory not found: {output_root}")

    indexed_runs = 0
    artifact_paths = sorted({path.parent for path in artifacts_root.rglob("source_model.json")})
    for artifact_path in artifact_paths:
        if _index_artifact_dir(artifact_path, artifacts_root, output_root, db_path):
            indexed_runs += 1

    logger.info("Backfilled %s artifact run(s) into %s", indexed_runs, db_path)
    return indexed_runs


def _index_artifact_dir(
    artifact_path: Path,
    artifacts_root: Path,
    output_root: Path,
    db_path: str,
) -> bool:
    source_file = artifact_path / "source_model.json"
    skill_file = artifact_path / "skill_model.json"
    image_path = artifact_path / "preprocessed.png"

    if not source_file.exists() or not skill_file.exists():
        logger.warning("Skipping %s: missing source/skill model", artifact_path)
        return False

    adapted_models = _load_adapted_models(artifact_path)
    if not adapted_models:
        logger.warning("Skipping %s: no adapted model artifacts found", artifact_path)
        return False

    source_model = SourceWorksheetModel.model_validate_json(source_file.read_text())
    skill_model = LiteracySkillModel.model_validate_json(skill_file.read_text())
    validation_results = _load_validation_results(artifact_path)
    resolved_output_dir = _resolve_output_dir(artifact_path, artifacts_root, output_root)
    pdf_paths = [str(path) for path in _find_pdf_paths(resolved_output_dir)]
    worksheet_mode = "multi" if len(adapted_models) > 1 else "single"

    index_run(
        source_image_path=str(image_path),
        source_image_hash=source_model.source_image_hash,
        extracted_text=source_model.raw_text,
        template_type=source_model.template_type,
        ocr_engine=source_model.ocr_engine,
        region_count=len(source_model.regions),
        skill_domain=skill_model.domain,
        skill_name=skill_model.specific_skill,
        grade_level=skill_model.grade_level,
        adapted_summaries=[_build_adapted_summary(model) for model in adapted_models],
        pdf_paths=pdf_paths,
        theme_id=adapted_models[0].theme_id,
        validation_results=validation_results,
        worksheet_mode=worksheet_mode,
        db_path=db_path,
    )
    logger.info("Backfilled %s from %s", source_model.source_image_hash, artifact_path)
    return True


def _resolve_output_dir(
    artifact_path: Path,
    artifacts_root: Path,
    output_root: Path,
) -> Path:
    if artifact_path == artifacts_root:
        return output_root

    try:
        relative = artifact_path.relative_to(artifacts_root)
    except ValueError:
        return output_root

    parts = list(relative.parts)
    if parts and parts[-1] == "artifacts":
        parts = parts[:-1]

    return output_root.joinpath(*parts) if parts else output_root


def _load_adapted_models(artifact_path: Path) -> list[AdaptedActivityModel]:
    adapted_files = sorted(
        artifact_path.glob("adapted_model*.json"),
        key=_artifact_file_index,
    )
    return [
        AdaptedActivityModel.model_validate_json(path.read_text())
        for path in adapted_files
    ]


def _load_validation_results(artifact_path: Path) -> dict[str, bool]:
    validation_files = sorted(
        artifact_path.glob("validation*.json"),
        key=_artifact_file_index,
    )
    if not validation_files:
        return {
            "skill_parity_passed": False,
            "age_band_passed": False,
            "adhd_compliance_passed": False,
            "print_quality_passed": False,
            "all_validators_passed": False,
        }

    per_run = [_parse_validation_flags(path) for path in validation_files]
    keys = {key for run in per_run for key in run}
    return {key: all(run.get(key, False) for run in per_run) for key in keys}


def _parse_validation_flags(path: Path) -> dict[str, bool]:
    payload = json.loads(path.read_text())
    return {
        "skill_parity_passed": bool(payload.get("skill_parity", {}).get("passed", False)),
        "age_band_passed": bool(payload.get("age_band", {}).get("passed", False)),
        "adhd_compliance_passed": bool(
            payload.get("adhd_compliance", {}).get("passed", False)
        ),
        "print_quality_passed": bool(payload.get("print_quality", {}).get("passed", False)),
        "all_validators_passed": all(
            bool(payload.get(name, {}).get("passed", False))
            for name in ("skill_parity", "age_band", "adhd_compliance", "print_quality")
        ),
    }


def _find_pdf_paths(output_dir: Path) -> list[Path]:
    return sorted(output_dir.glob("worksheet*.pdf"), key=_pdf_file_index)


def _artifact_file_index(path: Path) -> int:
    if path.name == "adapted_model.json" or path.name == "validation.json":
        return 1
    match = _ARTIFACT_INDEX_RE.search(path.name)
    if not match:
        return 999
    return int(match.group(1))


def _pdf_file_index(path: Path) -> int:
    match = _PDF_INDEX_RE.search(path.name)
    if not match:
        return 1
    return int(match.group(1))


def _build_adapted_summary(
    adapted: AdaptedActivityModel,
) -> dict[str, str | int | float | bool]:
    total_items = sum(len(chunk.items) for chunk in adapted.chunks)
    response_formats = sorted({chunk.response_format for chunk in adapted.chunks})
    estimated_minutes = sum(
        _extract_estimated_minutes(chunk.time_estimate)
        for chunk in adapted.chunks
    )
    distractors = sorted(_extract_distractor_words(adapted))

    return {
        "worksheet_title": adapted.worksheet_title or "Untitled",
        "worksheet_number": adapted.worksheet_number,
        "chunk_count": len(adapted.chunks),
        "total_items": total_items,
        "response_formats": ",".join(response_formats),
        "estimated_minutes": estimated_minutes,
        "distractor_words": ",".join(distractors),
    }


def _extract_estimated_minutes(time_estimate: str) -> int:
    match = re.search(r"(\d+)", time_estimate)
    if not match:
        return 0
    return int(match.group(1))


def _extract_distractor_words(adapted: AdaptedActivityModel) -> set[str]:
    distractors: set[str] = set()
    for chunk in adapted.chunks:
        for item in chunk.items:
            if item.response_format != "circle" or not item.options:
                continue

            answers = {
                answer.strip().lower()
                for answer in (item.answer or "").split(",")
                if answer.strip()
            }
            for option in item.options:
                normalized = option.strip().lower()
                if normalized and normalized not in answers:
                    distractors.add(normalized)
    return distractors


@click.command()
@click.option("--artifacts-dir", required=True, help="Path to artifacts directory root.")
@click.option("--output-dir", required=True, help="Path to output PDF directory root.")
@click.option("--db-path", default="vector_store", help="Vector store path.")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def main(artifacts_dir: str, output_dir: str, db_path: str, verbose: bool) -> None:
    """Index existing pipeline artifacts into the RAG vector store."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    count = backfill(artifacts_dir=artifacts_dir, output_dir=output_dir, db_path=db_path)
    click.echo(f"Backfilled {count} run(s)")


if __name__ == "__main__":
    main()
