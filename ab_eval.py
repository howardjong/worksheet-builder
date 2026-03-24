"""Run a narrow causal harness for whether retrieval is helping at all."""

from __future__ import annotations

import json
import logging
import os
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

import click

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from capture.preprocess import preprocess_page
from capture.store import store_master
from companion.schema import load_profile
from extract.heuristics import map_to_source_model
from extract.ocr import extract_text, extract_text_with_fallback
from extract.schema import SourceWorksheetModel
from extract.vision import extract_with_vision
from skill.extractor import extract_skill
from skill.schema import LiteracySkillModel
from theme.engine import load_theme
from transform import (
    _rag_result_to_metadata,
    _run_multi_worksheet_pipeline,
    _run_single_worksheet_pipeline,
    _select_rag_adaptation_context,
    _select_rag_curriculum_context,
    rag_available,
    run_pipeline,
)

logger = logging.getLogger(__name__)

ExtractionMode = Literal["vision_only", "auto", "paddle", "tesseract"]
RagVariantMode = Literal["selected", "negative_control"]


@click.command()
@click.option("--input-dir", required=True, help="Input image directory")
@click.option("--profile", "profile_path", required=True, help="Learner profile YAML")
@click.option("--theme", "theme_id", default="roblox_obby", help="Theme name")
@click.option("--output-root", default="./samples/output/ab_eval", help="Root output dir")
@click.option("--include", "include_pattern", default="IMG_*", help="Glob pattern in input dir")
@click.option(
    "--target",
    "targets",
    multiple=True,
    help="Holdout target image(s), basename or absolute path. Repeatable.",
)
@click.option("--db-path", default="vector_store", help="Vector store path")
@click.option("--seed/--no-seed", default=False, help="Seed store with non-target inputs")
@click.option("--images/--no-images", default=False, help="Enable AI image generation")
@click.option(
    "--negative-control/--no-negative-control",
    default=True,
    help="Run an intentionally weaker retrieval control arm.",
)
@click.option(
    "--extract-mode",
    type=click.Choice(["vision_only", "auto", "paddle", "tesseract"], case_sensitive=False),
    default="vision_only",
    show_default=True,
    help=(
        "Extraction backend for eval freezing. "
        "'vision_only' fails fast if Gemini vision is unavailable; "
        "'auto' restores OCR fallback."
    ),
)
@click.option(
    "--clean-db",
    is_flag=True,
    default=False,
    help="Delete vector store before seeding (destructive)",
)
def main(
    input_dir: str,
    profile_path: str,
    theme_id: str,
    output_root: str,
    include_pattern: str,
    targets: tuple[str, ...],
    db_path: str,
    seed: bool,
    images: bool,
    negative_control: bool,
    extract_mode: str,
    clean_db: bool,
) -> None:
    """Run the causal check: no-RAG vs RAG, with optional weak-RAG control."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    in_dir = Path(input_dir)
    files = sorted(in_dir.glob(include_pattern))
    if not files:
        raise click.ClickException(f"No files matched {include_pattern} in {in_dir}")

    target_paths = _resolve_targets(files, targets)
    if not target_paths:
        raise click.ClickException("No target files resolved for A/B run")

    run_root = Path(output_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    logger.info("A/B output root: %s", run_root)

    normalized_extract_mode = cast(ExtractionMode, extract_mode.lower())

    if clean_db:
        db = Path(db_path)
        if db.exists():
            shutil.rmtree(db)
            logger.info("Deleted vector store: %s", db)

    seed_inputs = [path for path in files if path not in target_paths]
    if seed:
        if normalized_extract_mode != "auto":
            raise click.ClickException(
                "--seed currently requires --extract-mode auto because seeding "
                "uses the full pipeline indexer."
            )
        if not rag_available():
            logger.warning(
                "RAG unavailable (no Gemini API key or Vertex project configured) — skipping seed"
            )
        elif seed_inputs:
            _seed_store(
                seed_inputs,
                profile_path,
                theme_id,
                run_root / "seed_runs",
                images,
                normalized_extract_mode,
            )
        else:
            logger.info("No seed inputs (all matched files are targets)")

    profile = load_profile(profile_path)
    theme = load_theme(theme_id)
    if not theme.multi_worksheet:
        logger.warning(
            "Theme %s is single-worksheet mode; AI review in prod path can add variability.",
            theme_id,
        )

    comparisons: list[dict[str, Any]] = []
    for target in target_paths:
        logger.info("Evaluating holdout target: %s", target.name)
        case_dir = run_root / target.stem
        frozen = _freeze_source_and_skill(
            target,
            case_dir / "frozen",
            extract_mode=normalized_extract_mode,
        )
        result_a = _run_variant_from_frozen(
            variant="A_no_rag",
            case_dir=case_dir,
            frozen=frozen,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            use_rag=False,
            images=images,
        )
        result_b = _run_variant_from_frozen(
            variant="B_with_rag",
            case_dir=case_dir,
            frozen=frozen,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            use_rag=True,
            images=images,
        )
        result_c: dict[str, Any] | None = None
        if negative_control:
            result_c = _run_variant_from_frozen(
                variant="C_bad_rag",
                case_dir=case_dir,
                frozen=frozen,
                profile=profile,
                theme=theme,
                theme_id=theme_id,
                use_rag=True,
                images=images,
                rag_mode="negative_control",
            )
        comparisons.append(_build_pair_summary(target.name, result_a, result_b, result_c))

    report = _build_scorecard(
        run_root=run_root,
        input_dir=in_dir,
        include_pattern=include_pattern,
        targets=target_paths,
        seed_count=len(seed_inputs) if seed else 0,
        images=images,
        db_path=db_path,
        negative_control=negative_control,
        comparisons=comparisons,
    )
    report_path = run_root / "scorecard.md"
    report_path.write_text(report)
    (run_root / "scorecard.json").write_text(json.dumps(comparisons, indent=2))
    logger.info("Scorecard: %s", report_path)


def _resolve_targets(files: list[Path], targets: tuple[str, ...]) -> list[Path]:
    if targets:
        by_name = {path.name: path for path in files}
        selected: list[Path] = []
        for value in targets:
            candidate = Path(value)
            if candidate.exists():
                selected.append(candidate.resolve())
                continue
            if value in by_name:
                selected.append(by_name[value])
                continue
            raise click.ClickException(f"Target not found in matched files: {value}")
        return sorted(set(selected))

    default = [path for path in files if path.name == "IMG_0004.JPG"]
    if default:
        return default
    return [files[0]]


def _seed_store(
    seed_inputs: list[Path],
    profile_path: str,
    theme_id: str,
    seed_root: Path,
    images: bool,
    extract_mode: ExtractionMode,
) -> None:
    seed_root.mkdir(parents=True, exist_ok=True)
    logger.info("Seeding vector store from %s input(s)...", len(seed_inputs))
    profile = load_profile(profile_path)
    theme = load_theme(theme_id)
    with _asset_generation(images):
        for path in seed_inputs:
            file_root = seed_root / path.stem
            file_root.mkdir(parents=True, exist_ok=True)
            if extract_mode == "auto":
                run_pipeline(
                    input_path=str(path),
                    profile_path=profile_path,
                    theme_id=theme_id,
                    output_dir=str(file_root / "output"),
                    artifacts_dir=str(file_root / "artifacts"),
                )
                continue

            frozen = _freeze_source_and_skill(
                path,
                file_root / "frozen",
                extract_mode=extract_mode,
            )
            _run_variant_from_frozen(
                variant="seed",
                case_dir=file_root,
                frozen=frozen,
                profile=profile,
                theme=theme,
                theme_id=theme_id,
                use_rag=False,
                images=images,
            )


def _freeze_source_and_skill(
    input_path: Path,
    freeze_dir: Path,
    extract_mode: ExtractionMode = "vision_only",
) -> dict[str, Any]:
    freeze_dir.mkdir(parents=True, exist_ok=True)
    artifacts = freeze_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    masters = freeze_dir / "masters"
    masters.mkdir(parents=True, exist_ok=True)

    preprocessed_path = artifacts / "preprocessed.png"
    preprocess_page(str(input_path), str(preprocessed_path))
    master = store_master(str(preprocessed_path), str(masters))
    source_model = _extract_source_model(
        str(preprocessed_path),
        master.image_hash,
        extract_mode=extract_mode,
    )

    skill_model = extract_skill(source_model)

    (artifacts / "source_model.json").write_text(source_model.model_dump_json(indent=2))
    (artifacts / "skill_model.json").write_text(skill_model.model_dump_json(indent=2))

    return {
        "input_path": str(input_path),
        "preprocessed_path": str(preprocessed_path),
        "source_image_hash": master.image_hash,
        "source_model": source_model,
        "skill_model": skill_model,
    }


def _extract_source_model(
    image_path: str,
    source_image_hash: str,
    extract_mode: ExtractionMode = "vision_only",
) -> SourceWorksheetModel:
    """Extract a source model using the requested eval backend."""
    normalized_mode = cast(ExtractionMode, extract_mode.lower())

    if normalized_mode in {"vision_only", "auto"}:
        source_model = extract_with_vision(image_path, source_image_hash)
        if source_model is not None:
            return source_model
        if normalized_mode == "vision_only":
            raise RuntimeError(
                "Gemini vision extraction is unavailable. "
                "Rerun with --extract-mode auto, paddle, or tesseract to allow OCR."
            )

    if normalized_mode == "auto":
        ocr_result = extract_text_with_fallback(image_path)
    elif normalized_mode == "paddle":
        ocr_result = extract_text(image_path, engine="paddleocr")
    elif normalized_mode == "tesseract":
        ocr_result = extract_text(image_path, engine="tesseract")
    else:
        raise ValueError(f"Unsupported extract mode: {extract_mode}")

    return map_to_source_model(ocr_result, source_image_hash)


def _run_variant_from_frozen(
    variant: str,
    case_dir: Path,
    frozen: dict[str, Any],
    profile: object,
    theme: object,
    theme_id: str,
    use_rag: bool,
    images: bool,
    rag_mode: RagVariantMode = "selected",
) -> dict[str, Any]:
    variant_dir = case_dir / variant
    output = variant_dir / "output"
    artifacts = variant_dir / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    source_model = frozen["source_model"]
    skill_model = frozen["skill_model"]
    source_hash = str(frozen["source_image_hash"])
    preprocessed = str(frozen["preprocessed_path"])

    rag_prior_adaptations: list[dict[str, object]] | None = None
    rag_curriculum_references: list[dict[str, object]] | None = None
    rag_debug: dict[str, object] = {"enabled": use_rag}
    if use_rag and rag_available():
        try:
            from rag.retrieval import retrieve_context

            assert isinstance(source_model, SourceWorksheetModel)
            assert isinstance(skill_model, LiteracySkillModel)
            skill_desc = f"{skill_model.domain}: {skill_model.specific_skill}"
            context = retrieve_context(
                skill_description=skill_desc,
                extracted_text=source_model.raw_text,
                grade_level=skill_model.grade_level,
            )
            if rag_mode == "negative_control":
                rag_prior_adaptations, rag_debug = _select_negative_control_context(context)
                rag_curriculum_references = None
            else:
                rag_prior_adaptations, rag_debug = _select_rag_adaptation_context(context)
                rag_curriculum_references = _select_rag_curriculum_context(context)
        except Exception as exc:
            rag_debug = {"enabled": True, "error": str(exc)}
    (artifacts / "rag_context.json").write_text(json.dumps(rag_debug, indent=2))

    with _asset_generation(images):
        if getattr(theme, "multi_worksheet", False):
            run_artifacts = _run_multi_worksheet_pipeline(
                skill_model=skill_model,
                profile=profile,
                theme=theme,
                theme_id=theme_id,
                source_image_path=preprocessed,
                source_image_hash=source_hash,
                extracted_text=source_model.raw_text,
                template_type=source_model.template_type,
                ocr_engine=source_model.ocr_engine,
                region_count=len(source_model.regions),
                output=output,
                artifacts=artifacts,
                rag_prior_adaptations=rag_prior_adaptations,
                rag_curriculum_references=rag_curriculum_references,
            )
        else:
            run_artifacts = _run_single_worksheet_pipeline(
                skill_model=skill_model,
                profile=profile,
                theme=theme,
                theme_id=theme_id,
                source_image_path=preprocessed,
                source_image_hash=source_hash,
                extracted_text=source_model.raw_text,
                template_type=source_model.template_type,
                ocr_engine=source_model.ocr_engine,
                region_count=len(source_model.regions),
                output=output,
                artifacts=artifacts,
                rag_prior_adaptations=rag_prior_adaptations,
                rag_curriculum_references=rag_curriculum_references,
            )

    response_formats: set[str] = set()
    total_chunks = 0
    total_items = 0
    for summary in run_artifacts.adapted_summaries:
        formats = str(summary.get("response_formats", "")).split(",")
        response_formats.update(fmt for fmt in formats if fmt)
        total_chunks += int(summary.get("chunk_count", 0))
        total_items += int(summary.get("total_items", 0))
    curriculum_supported_items = sum(
        int(summary.get("curriculum_supported_items", 0))
        for summary in run_artifacts.adapted_summaries
    )
    curriculum_support_rate = (
        curriculum_supported_items / total_items if total_items > 0 else 0.0
    )

    return {
        "variant": variant,
        "output_dir": str(output),
        "pdf_paths": run_artifacts.pdf_paths,
        "validation": run_artifacts.validation_results,
        "all_validators_passed": bool(
            run_artifacts.validation_results.get("all_validators_passed", False),
        ),
        "response_formats": sorted(response_formats),
        "response_format_count": len(response_formats),
        "total_chunks": total_chunks,
        "total_items": total_items,
        "curriculum_supported_items": curriculum_supported_items,
        "curriculum_support_rate": curriculum_support_rate,
        "rag_debug": rag_debug,
    }


def _build_pair_summary(
    target_name: str,
    result_a: dict[str, Any],
    result_b: dict[str, Any],
    result_c: dict[str, Any] | None,
) -> dict[str, Any]:
    a_validation = result_a["validation"]
    b_validation = result_b["validation"]
    a_score = _variant_score(result_a)
    b_score = _variant_score(result_b)

    return {
        "target": target_name,
        "A_no_rag": result_a,
        "B_with_rag": result_b,
        "C_bad_rag": result_c,
        "delta": {
            "score": b_score - a_score,
            "all_validators_passed": int(bool(result_b["all_validators_passed"]))
            - int(bool(result_a["all_validators_passed"])),
            "response_format_count": int(result_b["response_format_count"])
            - int(result_a["response_format_count"]),
            "curriculum_supported_items": int(result_b["curriculum_supported_items"])
            - int(result_a["curriculum_supported_items"]),
            "curriculum_support_rate": float(result_b["curriculum_support_rate"])
            - float(result_a["curriculum_support_rate"]),
            "skill_parity_passed": int(bool(b_validation.get("skill_parity_passed", False)))
            - int(bool(a_validation.get("skill_parity_passed", False))),
            "adhd_compliance_passed": int(bool(b_validation.get("adhd_compliance_passed", False)))
            - int(bool(a_validation.get("adhd_compliance_passed", False))),
        },
        "control_delta": _build_control_delta(result_b, result_c),
    }


def _variant_score(result: dict[str, Any]) -> int:
    validation = result["validation"]
    pass_flags = [
        "skill_parity_passed",
        "age_band_passed",
        "adhd_compliance_passed",
        "print_quality_passed",
    ]
    pass_score = sum(1 for key in pass_flags if bool(validation.get(key, False)))
    curriculum_bonus = int(result.get("curriculum_supported_items", 0))
    return pass_score * 100 + curriculum_bonus * 10 + int(result["response_format_count"])


def _build_control_delta(
    result_b: dict[str, Any],
    result_c: dict[str, Any] | None,
) -> dict[str, float | int] | None:
    if result_c is None:
        return None

    return {
        "score": _variant_score(result_b) - _variant_score(result_c),
        "all_validators_passed": int(bool(result_b["all_validators_passed"]))
        - int(bool(result_c["all_validators_passed"])),
        "response_format_count": int(result_b["response_format_count"])
        - int(result_c["response_format_count"]),
        "curriculum_supported_items": int(result_b["curriculum_supported_items"])
        - int(result_c["curriculum_supported_items"]),
        "curriculum_support_rate": float(result_b["curriculum_support_rate"])
        - float(result_c["curriculum_support_rate"]),
    }


def _build_scorecard(
    run_root: Path,
    input_dir: Path,
    include_pattern: str,
    targets: list[Path],
    seed_count: int,
    images: bool,
    db_path: str,
    negative_control: bool,
    comparisons: list[dict[str, Any]],
) -> str:
    b_better = sum(1 for row in comparisons if int(row["delta"]["score"]) > 0)
    ties = sum(1 for row in comparisons if int(row["delta"]["score"]) == 0)
    a_better = sum(1 for row in comparisons if int(row["delta"]["score"]) < 0)
    b_beats_control = sum(
        1
        for row in comparisons
        if row["control_delta"] is not None and int(row["control_delta"]["score"]) > 0
    )

    lines = [
        "# A/B Scorecard",
        "",
        f"- Run root: `{run_root}`",
        f"- Input dir: `{input_dir}` (pattern `{include_pattern}`)",
        f"- Targets: {', '.join(path.name for path in targets)}",
        f"- Seed inputs indexed: {seed_count}",
        f"- Image generation enabled: {images}",
        f"- Vector store path: `{db_path}`",
        f"- Negative-control arm enabled: {negative_control}",
        "",
        "## Aggregate",
        "",
        f"- RAG beats no-RAG: {b_better}",
        f"- RAG ties no-RAG: {ties}",
        f"- No-RAG beats RAG: {a_better}",
        (
            f"- RAG beats weak-retrieval control: {b_beats_control}"
            if negative_control
            else "- RAG beats weak-retrieval control: n/a"
        ),
        "",
        "## Per Target",
        "",
        (
            "| Target | A pass | B pass | B source | B count | "
            "A curriculum | B curriculum | B-A score | B-C score |"
        ),
        "|---|---:|---:|---|---:|---:|---:|---:|---:|",
    ]

    for row in comparisons:
        a = row["A_no_rag"]
        b = row["B_with_rag"]
        b_debug = b.get("rag_debug", {})
        control_delta = row.get("control_delta")
        control_score = "n/a"
        if control_delta is not None:
            control_score = str(int(control_delta["score"]))
        row_fmt = (
            "| {target} | {a_pass} | {b_pass} | {source} | {count} | "
            "{a_curriculum:.2f} | {b_curriculum:.2f} | {delta} | {control_delta} |"
        )
        lines.append(
            row_fmt.format(
                target=row["target"],
                a_pass=int(bool(a["all_validators_passed"])),
                b_pass=int(bool(b["all_validators_passed"])),
                source=b_debug.get("selected_source", "none"),
                count=int(b_debug.get("selected_count", 0) or 0),
                a_curriculum=float(a.get("curriculum_support_rate", 0.0)),
                b_curriculum=float(b.get("curriculum_support_rate", 0.0)),
                delta=int(row["delta"]["score"]),
                control_delta=control_score,
            )
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            (
                "- `rag/eval.py` is the primary experiment harness; "
                "this command is the narrow causal check."
            ),
            "- This protocol freezes Stage 1-4 (capture/extraction/skill) once per target.",
            "- A/B differences should come from adaptation + retrieval, not extraction drift.",
            "- Curriculum support rates come from item metadata marked `curriculum_supported`.",
            "- Inspect each variant's `artifacts/rag_context.json` for retrieval provenance.",
        ]
    )
    return "\n".join(lines) + "\n"


def _select_negative_control_context(
    rag_context: object,
) -> tuple[list[dict[str, object]] | None, dict[str, object]]:
    """Choose intentionally weaker context for a retrieval negative-control arm."""
    try:
        from rag.retrieval import RAGContext, RetrievalResult
    except ImportError:
        return None, {"enabled": False, "selected_source": "none"}

    if not isinstance(rag_context, RAGContext):
        return None, {"enabled": False, "selected_source": "none"}

    candidate_groups: list[tuple[str, list[RetrievalResult]]] = [
        ("negative_control_similar_skills", rag_context.similar_skills),
        ("negative_control_similar_worksheets", rag_context.similar_worksheets),
        ("negative_control_prior_adaptations", list(reversed(rag_context.prior_adaptations))),
        ("negative_control_curated_exemplars", list(reversed(rag_context.curated_exemplars))),
    ]

    selected_source = "none"
    selected_results: list[RetrievalResult] = []
    for source_name, results in candidate_groups:
        if results:
            selected_source = source_name
            selected_results = results
            break

    selected_metadata = [_rag_result_to_metadata(result) for result in selected_results]
    scores = [float(result.score) for result in selected_results]
    avg_score = (sum(scores) / len(scores)) if scores else None
    diagnostics: dict[str, object] = {
        "enabled": True,
        "selected_source": selected_source,
        "selected_count": len(selected_results),
        "selected_avg_score": avg_score,
        "counts": {
            "similar_worksheets": len(rag_context.similar_worksheets),
            "similar_skills": len(rag_context.similar_skills),
            "prior_adaptations": len(rag_context.prior_adaptations),
            "curated_exemplars": len(rag_context.curated_exemplars),
            "curriculum_references": len(rag_context.curriculum_references),
        },
        "selected_doc_ids": [result.doc_id for result in selected_results],
        "control_mode": "negative_control",
    }

    if not selected_metadata:
        return None, diagnostics
    return selected_metadata, diagnostics


@contextmanager
def _asset_generation(images: bool) -> Any:
    key = "WORKSHEET_SKIP_ASSET_GEN"
    old_value = os.environ.get(key)
    if images:
        os.environ.pop(key, None)
    else:
        os.environ[key] = "1"
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value


if __name__ == "__main__":
    main()
