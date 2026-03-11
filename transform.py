"""CLI entry point: transform a worksheet photo into an ADHD-adapted PDF."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import click
from pydantic import BaseModel

# Load .env before anything else
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from adapt.engine import adapt_activity, adapt_lesson
from adapt.schema import AdaptedActivityModel
from capture.preprocess import preprocess_page
from capture.store import store_master
from companion.schema import load_profile
from extract.heuristics import map_to_source_model
from extract.ocr import extract_text_with_fallback
from extract.vision import extract_with_vision
from render.pdf import render_worksheet
from skill.extractor import extract_skill
from theme.engine import apply_theme, load_theme
from validate.adhd_compliance import validate_adhd_compliance
from validate.ai_review import review_adapted_worksheet
from validate.print_checks import validate_print_quality
from validate.skill_parity import validate_age_band, validate_skill_parity

logger = logging.getLogger(__name__)


class RunArtifacts(BaseModel):
    """Collected artifacts from a pipeline run, used for optional RAG indexing."""

    source_image_path: str
    source_image_hash: str
    extracted_text: str
    template_type: str
    ocr_engine: str
    region_count: int
    skill_domain: str
    skill_name: str
    grade_level: str
    theme_id: str
    worksheet_mode: str
    adapted_summaries: list[dict[str, str | int | float | bool]]
    pdf_paths: list[str]
    validation_results: dict[str, bool]
    profile_name: str | None = None


@click.command()
@click.option("--input", "input_path", required=True, help="Path to worksheet photo/scan")
@click.option("--profile", "profile_path", required=True, help="Path to learner profile YAML")
@click.option("--theme", "theme_id", default="space", help="Theme name")
@click.option("--output", "output_dir", default="./output", help="Output directory")
def transform(
    input_path: str,
    profile_path: str,
    theme_id: str,
    output_dir: str,
) -> None:
    """Transform a worksheet photo into an ADHD-adapted, themed, print-ready PDF."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    output = Path(output_dir)
    artifacts = output / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    run_pipeline(
        input_path=input_path,
        profile_path=profile_path,
        theme_id=theme_id,
        output_dir=str(output),
        artifacts_dir=str(artifacts),
    )


def rag_available() -> bool:
    """Check if RAG is configured (Vertex AI project set)."""
    try:
        from rag.client import rag_available as _rag_available
    except ImportError:
        return False
    return _rag_available()


def run_pipeline(
    input_path: str,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    artifacts_dir: str,
) -> str:
    """Run the full transformation pipeline. Returns path to the output PDF."""
    output = Path(output_dir)
    artifacts = Path(artifacts_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    # Stage 1: Preprocess
    logger.info("Stage 1: Preprocessing image...")
    preprocessed_path = str(artifacts / "preprocessed.png")
    preprocess_page(input_path, preprocessed_path)

    # Stage 2: Store master
    logger.info("Stage 2: Storing master image...")
    masters_dir = output / "masters"
    masters_dir.mkdir(parents=True, exist_ok=True)
    master = store_master(preprocessed_path, str(masters_dir))

    # Stage 3: Source extraction (AI vision primary, OCR fallback)
    logger.info("Stage 3: Extracting source content...")
    source_model = None

    vision_model = extract_with_vision(preprocessed_path, master.image_hash)
    if vision_model is not None:
        source_model = vision_model
        logger.info("  Using AI vision extraction")
    else:
        logger.info("  AI vision unavailable — falling back to OCR...")
        ocr_result = extract_text_with_fallback(preprocessed_path)
        source_model = map_to_source_model(ocr_result, master.image_hash)

    source_json = artifacts / "source_model.json"
    source_json.write_text(source_model.model_dump_json(indent=2))
    logger.info(
        "  Template: %s, Regions: %s",
        source_model.template_type,
        len(source_model.regions),
    )

    # Stage 4: Skill extraction
    logger.info("Stage 4: Extracting literacy skill...")
    skill_model = extract_skill(source_model)

    skill_json = artifacts / "skill_model.json"
    skill_json.write_text(skill_model.model_dump_json(indent=2))
    logger.info("  Domain: %s, Skill: %s", skill_model.domain, skill_model.specific_skill)

    # Stage 5: ADHD adaptation
    logger.info("Stage 5: Adapting for ADHD...")
    profile = load_profile(profile_path)

    # Stage 6: Load theme
    logger.info("Stage 6: Loading theme...")
    theme = load_theme(theme_id)

    # Stage 4b: Optional RAG retrieval (skill + content)
    rag_prior_adaptations: list[dict[str, object]] | None = None
    rag_debug: dict[str, object] = {"enabled": rag_available()}
    if rag_available():
        try:
            from rag.retrieval import retrieve_context

            skill_desc = f"{skill_model.domain}: {skill_model.specific_skill}"
            rag_context = retrieve_context(
                skill_description=skill_desc,
                extracted_text=source_model.raw_text,
                grade_level=skill_model.grade_level,
            )
            rag_prior_adaptations, rag_debug = _select_rag_adaptation_context(rag_context)
            if rag_prior_adaptations:
                selected_source = str(rag_debug.get("selected_source", "unknown"))
                logger.info(
                    "  RAG: %s contexts selected from %s",
                    len(rag_prior_adaptations),
                    selected_source,
                )
        except Exception as exc:
            rag_debug = {"enabled": True, "error": str(exc)}
            logger.warning("  RAG retrieval skipped: %s", exc)

    rag_json = artifacts / "rag_context.json"
    rag_json.write_text(json.dumps(rag_debug, indent=2))

    # Branch into single or multi worksheet pipeline
    if theme.multi_worksheet:
        run_artifacts = _run_multi_worksheet_pipeline(
            skill_model=skill_model,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            source_image_path=preprocessed_path,
            source_image_hash=master.image_hash,
            extracted_text=source_model.raw_text,
            template_type=source_model.template_type,
            ocr_engine=source_model.ocr_engine,
            region_count=len(source_model.regions),
            output=output,
            artifacts=artifacts,
            rag_prior_adaptations=rag_prior_adaptations,
        )
    else:
        run_artifacts = _run_single_worksheet_pipeline(
            skill_model=skill_model,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            source_image_path=preprocessed_path,
            source_image_hash=master.image_hash,
            extracted_text=source_model.raw_text,
            template_type=source_model.template_type,
            ocr_engine=source_model.ocr_engine,
            region_count=len(source_model.regions),
            output=output,
            artifacts=artifacts,
            rag_prior_adaptations=rag_prior_adaptations,
        )

    # Stage 9: Optional RAG indexing
    if rag_available():
        try:
            from rag.indexer import index_run

            index_run(
                source_image_path=run_artifacts.source_image_path,
                source_image_hash=run_artifacts.source_image_hash,
                extracted_text=run_artifacts.extracted_text,
                template_type=run_artifacts.template_type,
                ocr_engine=run_artifacts.ocr_engine,
                region_count=run_artifacts.region_count,
                skill_domain=run_artifacts.skill_domain,
                skill_name=run_artifacts.skill_name,
                grade_level=run_artifacts.grade_level,
                adapted_summaries=run_artifacts.adapted_summaries,
                pdf_paths=run_artifacts.pdf_paths,
                theme_id=run_artifacts.theme_id,
                validation_results=run_artifacts.validation_results,
                worksheet_mode=run_artifacts.worksheet_mode,
                profile_name=run_artifacts.profile_name,
            )
            logger.info("Stage 9: Indexed run artifacts into RAG store")
        except Exception as exc:
            logger.warning("  RAG indexing skipped: %s", exc)

    return run_artifacts.pdf_paths[0] if run_artifacts.pdf_paths else ""


def _run_single_worksheet_pipeline(
    skill_model: object,
    profile: object,
    theme: object,
    theme_id: str,
    source_image_path: str,
    source_image_hash: str,
    extracted_text: str,
    template_type: str,
    ocr_engine: str,
    region_count: int,
    output: Path,
    artifacts: Path,
    rag_prior_adaptations: list[dict[str, object]] | None,
) -> RunArtifacts:
    """Single-worksheet pipeline."""
    from companion.avatar import compose_avatar
    from companion.schema import LearnerProfile
    from skill.schema import LiteracySkillModel
    from theme.schema import ThemeConfig

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(profile, LearnerProfile)
    assert isinstance(theme, ThemeConfig)

    adapted = adapt_activity(
        skill_model,
        profile,
        theme_id=theme_id,
        rag_prior_adaptations=rag_prior_adaptations,
    )

    adapted_json = artifacts / "adapted_model.json"
    adapted_json.write_text(adapted.model_dump_json(indent=2))
    logger.info("  Chunks: %s, Grade: %s", len(adapted.chunks), adapted.grade_level)

    # Stage 5b: AI quality review (iterative)
    logger.info("Stage 5b: AI quality review...")
    adapted, reviews = review_adapted_worksheet(adapted)

    review_data = [r.to_dict() for r in reviews]
    review_json = artifacts / "ai_review.json"
    review_json.write_text(json.dumps(review_data, indent=2))

    ai_review_passed = True
    if reviews and reviews[-1].passed:
        logger.info("  AI quality review: PASSED")
    elif reviews:
        ai_review_passed = False
        logger.warning(
            "  AI quality review: %s issues remaining after %s iterations",
            len(reviews[-1].issues),
            len(reviews),
        )

    adapted_json.write_text(adapted.model_dump_json(indent=2))

    apply_theme(adapted, theme)

    avatar_path: str | None = None
    if profile.avatar:
        logger.info("Stage 6b: Composing avatar...")
        avatar_result = compose_avatar(profile, size="companion", theme_id=theme_id)
        if avatar_result:
            avatar_path = str(avatar_result)
            logger.info("  Avatar: %s -> %s", profile.avatar.base_character, avatar_path)

    logger.info("Stage 7: Rendering PDF...")
    content_hash = hashlib.sha256(
        f"{source_image_hash}:{profile.name}:{theme_id}".encode()
    ).hexdigest()[:12]
    pdf_filename = f"worksheet_{content_hash}.pdf"
    pdf_path = str(output / pdf_filename)
    render_worksheet(adapted, theme, pdf_path, avatar_image=avatar_path)
    logger.info("  Output: %s", pdf_path)

    logger.info("Stage 8: Running validation...")
    validation_results = _validate_and_report(skill_model, adapted, profile, pdf_path, artifacts)
    validation_results["ai_review_passed"] = ai_review_passed
    validation_results["all_validators_passed"] = (
        validation_results.get("all_validators_passed", False) and ai_review_passed
    )

    logger.info("Done! PDF saved to: %s", pdf_path)
    return RunArtifacts(
        source_image_path=source_image_path,
        source_image_hash=source_image_hash,
        extracted_text=extracted_text,
        template_type=template_type,
        ocr_engine=ocr_engine,
        region_count=region_count,
        skill_domain=skill_model.domain,
        skill_name=skill_model.specific_skill,
        grade_level=skill_model.grade_level,
        theme_id=theme_id,
        worksheet_mode="single",
        adapted_summaries=[_build_adapted_summary(adapted)],
        pdf_paths=[pdf_path],
        validation_results=validation_results,
        profile_name=profile.name,
    )


def _run_multi_worksheet_pipeline(
    skill_model: object,
    profile: object,
    theme: object,
    theme_id: str,
    source_image_path: str,
    source_image_hash: str,
    extracted_text: str,
    template_type: str,
    ocr_engine: str,
    region_count: int,
    output: Path,
    artifacts: Path,
    rag_prior_adaptations: list[dict[str, object]] | None,
) -> RunArtifacts:
    """Multi-worksheet pipeline — produces 2-3 mini-worksheets per lesson."""
    from companion.schema import LearnerProfile
    from render.asset_gen import compute_worksheet_hash, generate_worksheet_assets
    from render.pose_planner import plan_scenes, plan_word_pictures
    from skill.schema import LiteracySkillModel
    from theme.schema import ThemeConfig

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(profile, LearnerProfile)
    assert isinstance(theme, ThemeConfig)

    worksheets = adapt_lesson(
        skill_model,
        profile,
        theme_id=theme_id,
        rag_prior_adaptations=rag_prior_adaptations,
    )
    logger.info("  Generated %s mini-worksheets", len(worksheets))

    pdf_paths: list[str] = []
    adapted_summaries: list[dict[str, str | int | float | bool]] = []
    validation_runs: list[dict[str, bool]] = []
    content_hash = hashlib.sha256(
        f"{source_image_hash}:{profile.name}:{theme_id}".encode()
    ).hexdigest()[:12]

    for i, adapted in enumerate(worksheets, start=1):
        ws_title = adapted.worksheet_title or "Untitled"
        logger.info("  Processing worksheet %s/%s: %s", i, len(worksheets), ws_title)

        adapted_json = artifacts / f"adapted_model_{i}.json"
        adapted_json.write_text(adapted.model_dump_json(indent=2))

        apply_theme(adapted, theme)

        asset_manifest = None
        try:
            scenes = plan_scenes(adapted)
            word_prompts = plan_word_pictures(adapted)
            ws_hash = compute_worksheet_hash(adapted.source_hash, i, theme_id)
            asset_manifest = generate_worksheet_assets(scenes, word_prompts, ws_hash)
        except Exception as exc:
            logger.warning("  Asset generation skipped: %s", exc)

        pdf_filename = f"worksheet_{content_hash}_{i}of{len(worksheets)}.pdf"
        pdf_path = str(output / pdf_filename)
        render_worksheet(adapted, theme, pdf_path, asset_manifest=asset_manifest)
        pdf_paths.append(pdf_path)
        logger.info("  Output: %s", pdf_path)

        ws_validation = _validate_and_report(
            skill_model,
            adapted,
            profile,
            pdf_path,
            artifacts,
            suffix=f"_{i}",
        )
        validation_runs.append(ws_validation)
        adapted_summaries.append(_build_adapted_summary(adapted))

    _validate_format_variety(worksheets)

    validation_results = _aggregate_validation_results(validation_runs)
    validation_results["ai_review_passed"] = True
    validation_results["all_validators_passed"] = validation_results.get(
        "all_validators_passed",
        False,
    )

    logger.info("Done! %s PDFs saved to: %s", len(pdf_paths), output)
    return RunArtifacts(
        source_image_path=source_image_path,
        source_image_hash=source_image_hash,
        extracted_text=extracted_text,
        template_type=template_type,
        ocr_engine=ocr_engine,
        region_count=region_count,
        skill_domain=skill_model.domain,
        skill_name=skill_model.specific_skill,
        grade_level=skill_model.grade_level,
        theme_id=theme_id,
        worksheet_mode="multi",
        adapted_summaries=adapted_summaries,
        pdf_paths=pdf_paths,
        validation_results=validation_results,
        profile_name=profile.name,
    )


def _validate_and_report(
    skill_model: object,
    adapted: object,
    profile: object,
    pdf_path: str,
    artifacts: Path,
    suffix: str = "",
) -> dict[str, bool]:
    """Run validation checks, persist results, and return pass/fail flags."""
    from adapt.schema import AdaptedActivityModel
    from companion.schema import LearnerProfile
    from skill.schema import LiteracySkillModel

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(adapted, AdaptedActivityModel)
    assert isinstance(profile, LearnerProfile)

    parity_result = validate_skill_parity(skill_model, adapted)
    age_result = validate_age_band(adapted, profile.grade_level)
    adhd_result = validate_adhd_compliance(adapted)
    print_result = validate_print_quality(pdf_path)

    validation = {
        "skill_parity": parity_result.model_dump(),
        "age_band": age_result.model_dump(),
        "adhd_compliance": adhd_result.model_dump(),
        "print_quality": print_result.model_dump(),
    }
    val_json = artifacts / f"validation{suffix}.json"
    val_json.write_text(json.dumps(validation, indent=2))

    all_passed = all([
        parity_result.passed,
        age_result.passed,
        adhd_result.passed,
        print_result.passed,
    ])

    if all_passed:
        logger.info("  All validations passed%s!", suffix)
    else:
        for name, result in [
            ("Skill parity", parity_result),
            ("Age band", age_result),
            ("ADHD compliance", adhd_result),
            ("Print quality", print_result),
        ]:
            if not result.passed:
                for violation in result.violations:
                    if violation.severity == "error":
                        logger.error("  %s%s: %s", name, suffix, violation.message)

    for name, result in [
        ("Skill parity", parity_result),
        ("Age band", age_result),
        ("ADHD compliance", adhd_result),
        ("Print quality", print_result),
    ]:
        for violation in result.violations:
            if violation.severity == "warning":
                logger.warning("  %s%s: %s", name, suffix, violation.message)

    return {
        "skill_parity_passed": parity_result.passed,
        "age_band_passed": age_result.passed,
        "adhd_compliance_passed": adhd_result.passed,
        "print_quality_passed": print_result.passed,
        "all_validators_passed": all_passed,
    }


def _aggregate_validation_results(
    validations: Sequence[dict[str, bool]],
) -> dict[str, bool]:
    """Aggregate per-worksheet validation flags across a run."""
    if not validations:
        return {
            "skill_parity_passed": False,
            "age_band_passed": False,
            "adhd_compliance_passed": False,
            "print_quality_passed": False,
            "all_validators_passed": False,
        }

    keys: set[str] = set()
    for run in validations:
        keys.update(run.keys())

    return {
        key: all(run.get(key, False) for run in validations)
        for key in keys
    }


def _build_adapted_summary(
    adapted: AdaptedActivityModel,
) -> dict[str, str | int | float | bool]:
    """Build a compact adaptation summary for RAG indexing metadata."""
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
    """Parse minute count from chunk time estimate text."""
    match = re.search(r"(\d+)", time_estimate)
    if not match:
        return 0
    return int(match.group(1))


def _extract_distractor_words(adapted: AdaptedActivityModel) -> set[str]:
    """Extract distractor options used in circle-format items."""
    distractors: set[str] = set()

    for chunk in adapted.chunks:
        for item in chunk.items:
            if item.response_format != "circle" or not item.options:
                continue

            answers: set[str] = set()
            if item.answer:
                answers = {
                    answer.strip().lower()
                    for answer in item.answer.split(",")
                    if answer.strip()
                }

            for option in item.options:
                normalized = option.strip().lower()
                if normalized and normalized not in answers:
                    distractors.add(normalized)

    return distractors


def _validate_format_variety(worksheets: Sequence[AdaptedActivityModel]) -> None:
    """Check that the multi-worksheet set has response format variety."""
    all_formats: set[str] = set()
    for worksheet in worksheets:
        for chunk in worksheet.chunks:
            all_formats.add(chunk.response_format)

    if len(all_formats) < 2:
        logger.warning(
            "  Format variety: only %s format(s) used across %s worksheets. "
            "Recommend at least 2 different formats.",
            len(all_formats),
            len(worksheets),
        )


def _select_rag_adaptation_context(
    rag_context: object,
) -> tuple[list[dict[str, object]] | None, dict[str, object]]:
    """Choose RAG context for adaptation with quality-first preference."""
    try:
        from rag.retrieval import RAGContext
    except ImportError:
        return None, {"enabled": False, "selected_source": "none"}

    if not isinstance(rag_context, RAGContext):
        return None, {"enabled": False, "selected_source": "none"}

    selected_source = "none"
    selected_results = rag_context.curated_exemplars
    if selected_results:
        selected_source = "curated_exemplars"
    elif rag_context.prior_adaptations:
        selected_results = rag_context.prior_adaptations
        selected_source = "prior_adaptations"

    selected_metadata: list[dict[str, object]] = []
    for result in selected_results:
        metadata = {key: value for key, value in result.metadata.items()}
        metadata["_rag_score"] = float(result.score)
        metadata["_rag_doc_id"] = result.doc_id
        selected_metadata.append(metadata)

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
        },
        "selected_doc_ids": [result.doc_id for result in selected_results],
    }

    if not selected_metadata:
        return None, diagnostics
    return selected_metadata, diagnostics


if __name__ == "__main__":
    transform()
