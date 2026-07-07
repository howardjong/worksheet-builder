"""CLI entry point: transform a worksheet photo into an ADHD-adapted PDF."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import click
from pydantic import BaseModel

# Load .env before anything else
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from adapt.engine import adapt_activity, adapt_lesson
from adapt.rules import build_rules
from adapt.schema import AdaptedActivityModel
from capture.preprocess import preprocess_page
from capture.store import store_master
from companion.schema import load_profile
from extract.heuristics import map_to_source_model
from extract.ocr import extract_text_with_fallback
from extract.schema import SourceWorksheetModel
from extract.vision import extract_with_vision
from render.design_spec import RenderMode, WorksheetDesignSpec, compile_worksheet_design_spec
from render.pdf import render_cover_page
from render.strategies import RenderContext, RenderResult, RenderStrategy, resolve_render_strategy
from skill.extractor import extract_skill
from skill.schema import LiteracySkillModel
from theme.engine import apply_theme, load_theme
from validate.adhd_compliance import validate_adhd_compliance, validate_lesson_time_budget
from validate.ai_review import review_adapted_worksheet
from validate.content_coverage import (
    validate_content_coverage,
    validate_content_coverage_for_package,
)
from validate.print_checks import validate_print_quality
from validate.schema import ValidationResult
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
    render_mode: str = "pdf_classic"
    renderer_id: str = "pdf_classic"
    renderer_experimental: bool = False
    renderer_artifact_paths: list[str] = []


@click.command()
@click.option("--input", "input_path", default=None, help="Path to worksheet photo/scan")
@click.option(
    "--lesson",
    "lesson_number",
    type=int,
    default=None,
    help="UFLI lesson number — build a worksheet from the corpus, no photo needed",
)
@click.option("--profile", "profile_path", required=True, help="Path to learner profile YAML")
@click.option("--theme", "theme_id", default="space", help="Theme name")
@click.option("--output", "output_dir", default="./output", help="Output directory")
@click.option(
    "--render-mode",
    default="image_gen",
    type=click.Choice(["pdf_classic", "hybrid_shell", "image_prompt", "image_gen"]),
    help=(
        "Renderer mode. Defaults to image_gen (full-page AI render, gated and "
        "cached); degrades to pdf_classic offline. Use --render-mode pdf_classic "
        "to force the deterministic renderer."
    ),
)
def transform(
    input_path: str | None,
    lesson_number: int | None,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    render_mode: str,
) -> None:
    """Transform a worksheet photo (or UFLI lesson) into an ADHD-adapted PDF."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Exactly one entry point: a photo (--input) or a lesson number (--lesson).
    if (input_path is None) == (lesson_number is None):
        raise click.UsageError("Provide exactly one of --input or --lesson.")

    output = Path(output_dir)
    artifacts = output / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    if lesson_number is not None:
        run_lesson_pipeline(
            lesson_number=lesson_number,
            profile_path=profile_path,
            theme_id=theme_id,
            output_dir=str(output),
            artifacts_dir=str(artifacts),
            render_mode=render_mode,
        )
    else:
        assert input_path is not None  # guaranteed by the exactly-one check above
        run_pipeline(
            input_path=input_path,
            profile_path=profile_path,
            theme_id=theme_id,
            output_dir=str(output),
            artifacts_dir=str(artifacts),
            render_mode=render_mode,
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
    render_mode: str | None = None,
) -> str:
    """Run the full transformation pipeline. Returns path to the output PDF."""
    run_artifacts = run_pipeline_collect_artifacts(
        input_path=input_path,
        profile_path=profile_path,
        theme_id=theme_id,
        output_dir=output_dir,
        artifacts_dir=artifacts_dir,
        index_results=True,
        render_mode=render_mode,
    )
    return run_artifacts.pdf_paths[0] if run_artifacts.pdf_paths else ""


def _resolve_source_model(
    input_path: str, preprocessed_path: str, image_hash: str
) -> SourceWorksheetModel:
    """Run AI vision (primary) with OCR fallback to extract the source model.

    Vision uses the original image (not preprocessed) because preprocessing can
    destroy content (e.g., warping to an illustration box).
    """
    vision_model = extract_with_vision(input_path, image_hash)
    if vision_model is not None:
        logger.info("  Using AI vision extraction")
        return vision_model
    logger.info("  AI vision unavailable — falling back to OCR...")
    ocr_result = extract_text_with_fallback(preprocessed_path)
    return map_to_source_model(ocr_result, image_hash)


def _source_model_with_cache(
    input_path: str, preprocessed_path: str, image_hash: str
) -> SourceWorksheetModel:
    """Extract the source model, optionally freezing it per image.

    When ``WORKSHEET_EXTRACTION_CACHE`` names a directory, the (non-deterministic)
    vision extraction runs once per image hash and is cached, so repeated runs —
    e.g. every A/B battery cell — consume identical input. Unset ⇒ no cache I/O,
    behaving exactly as before.
    """
    cache_dir = os.environ.get("WORKSHEET_EXTRACTION_CACHE")
    if not cache_dir:
        return _resolve_source_model(input_path, preprocessed_path, image_hash)

    cache_path = Path(cache_dir) / f"{image_hash}.source_model.json"
    if cache_path.exists():
        logger.info("  Using frozen (cached) extraction: %s", cache_path)
        return SourceWorksheetModel.model_validate_json(cache_path.read_text())

    model = _resolve_source_model(input_path, preprocessed_path, image_hash)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(model.model_dump_json(indent=2))
    return model


def run_pipeline_collect_artifacts(
    input_path: str,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    artifacts_dir: str,
    *,
    index_results: bool,
    render_mode: str | None = None,
) -> RunArtifacts:
    """Run the full pipeline and return RunArtifacts, optionally indexing them."""
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
    source_model = _source_model_with_cache(input_path, preprocessed_path, master.image_hash)

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

    return _run_from_skill_model(
        skill_model,
        profile_path=profile_path,
        theme_id=theme_id,
        output=output,
        artifacts=artifacts,
        source_image_path=preprocessed_path,
        source_image_hash=master.image_hash,
        extracted_text=source_model.raw_text,
        template_type=source_model.template_type,
        ocr_engine=source_model.ocr_engine,
        region_count=len(source_model.regions),
        index_results=index_results,
        render_mode=render_mode,
    )


def _run_from_skill_model(
    skill_model: LiteracySkillModel,
    *,
    profile_path: str,
    theme_id: str,
    output: Path,
    artifacts: Path,
    source_image_path: str,
    source_image_hash: str,
    extracted_text: str,
    template_type: str,
    ocr_engine: str,
    region_count: int,
    index_results: bool,
    render_mode: str | None = None,
) -> RunArtifacts:
    """Adapt → theme → render → validate from a ready skill model.

    Shared by the photo pipeline and the ``--lesson`` entry point. The caller has
    already produced the skill model (OCR extraction or corpus lookup) plus the
    source provenance fields; this runs everything downstream of skill extraction.
    """
    selected_strategy = resolve_render_strategy(render_mode)
    selected_render_mode = cast(RenderMode, selected_strategy.renderer_id)

    # Stage 5: ADHD adaptation
    logger.info("Stage 5: Adapting for ADHD...")
    profile = load_profile(profile_path)

    # Stage 6: Load theme
    logger.info("Stage 6: Loading theme...")
    theme = load_theme(theme_id)

    # Stage 4b: Optional RAG retrieval (skill + content)
    rag_prior_adaptations: list[dict[str, object]] | None = None
    rag_curriculum_references: list[dict[str, object]] | None = None
    use_live_rag = os.environ.get("WORKSHEET_USE_RAG") == "1"
    rag_is_available = False
    rag_debug: dict[str, object] = {
        "enabled": False,
        "reason": "WORKSHEET_USE_RAG not set",
    }
    if use_live_rag:
        rag_is_available = rag_available()
        rag_debug = {"enabled": rag_is_available}
    if use_live_rag and rag_is_available:
        try:
            from rag.retrieval import retrieve_context

            skill_desc = f"{skill_model.domain}: {skill_model.specific_skill}"
            rag_context = retrieve_context(
                skill_description=skill_desc,
                extracted_text=extracted_text,
                grade_level=skill_model.grade_level,
            )
            rag_prior_adaptations, rag_debug = _select_rag_adaptation_context(rag_context)
            rag_curriculum_references = _select_rag_curriculum_context(rag_context)
            if rag_prior_adaptations:
                selected_source = str(rag_debug.get("selected_source", "unknown"))
                logger.info(
                    "  RAG: %s contexts selected from %s",
                    len(rag_prior_adaptations),
                    selected_source,
                )
            if rag_curriculum_references:
                logger.info(
                    "  RAG: %s curriculum references available",
                    len(rag_curriculum_references),
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
            source_image_path=source_image_path,
            source_image_hash=source_image_hash,
            extracted_text=extracted_text,
            template_type=template_type,
            ocr_engine=ocr_engine,
            region_count=region_count,
            output=output,
            artifacts=artifacts,
            rag_prior_adaptations=rag_prior_adaptations,
            rag_curriculum_references=rag_curriculum_references,
            render_mode=selected_render_mode,
        )
    else:
        run_artifacts = _run_single_worksheet_pipeline(
            skill_model=skill_model,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            source_image_path=source_image_path,
            source_image_hash=source_image_hash,
            extracted_text=extracted_text,
            template_type=template_type,
            ocr_engine=ocr_engine,
            region_count=region_count,
            output=output,
            artifacts=artifacts,
            rag_prior_adaptations=rag_prior_adaptations,
            rag_curriculum_references=rag_curriculum_references,
            render_mode=selected_render_mode,
        )

    # Stage 9: Optional RAG indexing
    if index_results and use_live_rag and rag_is_available:
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

    return run_artifacts


def run_lesson_pipeline(
    lesson_number: int,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    artifacts_dir: str,
    render_mode: str | None = None,
) -> str:
    """Run the lesson-number pipeline. Returns the path to the output PDF."""
    run_artifacts = run_lesson_pipeline_collect_artifacts(
        lesson_number=lesson_number,
        profile_path=profile_path,
        theme_id=theme_id,
        output_dir=output_dir,
        artifacts_dir=artifacts_dir,
        index_results=True,
        render_mode=render_mode,
    )
    return run_artifacts.pdf_paths[0] if run_artifacts.pdf_paths else ""


def run_lesson_pipeline_collect_artifacts(
    lesson_number: int,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    artifacts_dir: str,
    *,
    index_results: bool,
    render_mode: str | None = None,
) -> RunArtifacts:
    """Build a skill model from a UFLI lesson number and run the rest of the pipeline.

    Skips capture/OCR entirely (no photo). Idempotent: the synthetic source hash
    is a pure function of the lesson number, so repeated runs land on the same
    ``lesson_<hash>.pdf``.

    Defaults the adapt stage to the single-call planner (WORKSHEET_PLANNER_V2=1
    plus its prerequisite WORKSHEET_LLM_ADAPT=1 — the planner is a no-op without
    it) rather than the legacy Gemini-plan/GPT-judge/retry loop. This is scoped
    to lesson mode only — the photo workflow's own default is untouched, since
    that path has its own historical A/B gate history (see .claude/worksheet-
    project-context.md, decisions D30/D31). Lesson mode is new and has no such
    history; the legacy loop was observed live on a full UFLI lesson producing
    an over-cap 10-worksheet package after a rejected pedagogical judge verdict —
    exactly the failure mode planner-v2 was built to fix. Explicitly set
    WORKSHEET_PLANNER_V2=0 to opt back into the legacy loop, or
    WORKSHEET_LLM_ADAPT=0 to disable LLM adaptation entirely (deterministic
    engine, zero adapt-stage LLM calls).
    """
    from skill.lesson_loader import skill_model_from_lesson

    output = Path(output_dir)
    artifacts = Path(artifacts_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Lesson mode: building skill model from UFLI lesson %s (no capture/OCR)",
        lesson_number,
    )
    skill_model = skill_model_from_lesson(lesson_number)
    skill_json = artifacts / "skill_model.json"
    skill_json.write_text(skill_model.model_dump_json(indent=2))
    logger.info("  Domain: %s, Skill: %s", skill_model.domain, skill_model.specific_skill)

    # Deterministic source hash for the content-hash chain (transform.py content_hash).
    source_image_hash = hashlib.sha256(f"ufli_lesson:{lesson_number}".encode()).hexdigest()[:16]

    # Scoped, restorable defaults — each only takes effect if the caller hasn't
    # set that variable themselves, and never leaks beyond this call (important
    # since os.environ is process-global and shared across tests in the same
    # session). WORKSHEET_LLM_ADAPT must be defaulted alongside PLANNER_V2:
    # plan_lesson_llm() is a no-op without it, and silently falling to the
    # deterministic engine reproduces the 10-worksheet overflow this default
    # exists to prevent.
    lesson_mode_defaults = {"WORKSHEET_PLANNER_V2": "1", "WORKSHEET_LLM_ADAPT": "1"}
    applied: list[str] = []
    for key, value in lesson_mode_defaults.items():
        if key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    try:
        return _run_from_skill_model(
            skill_model,
            profile_path=profile_path,
            theme_id=theme_id,
            output=output,
            artifacts=artifacts,
            source_image_path=f"ufli_lesson:{lesson_number}",
            source_image_hash=source_image_hash,
            extracted_text="",
            template_type=skill_model.template_type,
            ocr_engine="none",
            region_count=0,
            index_results=index_results,
            render_mode=render_mode,
        )
    finally:
        for key in applied:
            os.environ.pop(key, None)


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
    rag_curriculum_references: list[dict[str, object]] | None,
    render_mode: RenderMode = "pdf_classic",
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
        rag_curriculum_references=rag_curriculum_references,
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
    strategy = resolve_render_strategy(render_mode)
    design_spec = compile_worksheet_design_spec(adapted, theme, profile, render_mode=render_mode)
    render_result = strategy.render(
        RenderContext(
            design_spec=design_spec,
            adapted=adapted,
            theme=theme,
            output_path=Path(pdf_path),
            artifacts_dir=artifacts,
            avatar_image=avatar_path,
        )
    )
    manifest_path = _write_renderer_manifest(artifacts, render_result, design_spec)
    renderer_artifact_paths = _merge_artifact_paths(
        render_result.artifact_paths,
        [manifest_path],
    )
    if render_result.pdf_path:
        logger.info("  Output: %s", render_result.pdf_path)
    else:
        logger.info("  Output: prompt artifacts only")

    logger.info("Stage 8: Running validation...")
    if render_result.pdf_path:
        validation_results = _validate_and_report(
            skill_model,
            adapted,
            profile,
            render_result.pdf_path,
            artifacts,
        )
        pdf_paths = [render_result.pdf_path]
    else:
        validation_results = _validate_non_pdf_and_report(skill_model, adapted, profile, artifacts)
        pdf_paths = []
    validation_results["ai_review_passed"] = ai_review_passed
    validation_results["renderer_produces_pdf"] = render_result.produces_pdf
    validation_results["renderer_experimental"] = render_result.experimental
    validation_results["all_validators_passed"] = (
        validation_results.get("all_validators_passed", False)
        and ai_review_passed
        and render_result.produces_pdf
    )

    logger.info("Done! Render mode %s complete", render_result.renderer_id)
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
        pdf_paths=pdf_paths,
        validation_results=validation_results,
        profile_name=profile.name,
        render_mode=render_mode,
        renderer_id=render_result.renderer_id,
        renderer_experimental=render_result.experimental,
        renderer_artifact_paths=renderer_artifact_paths,
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
    rag_curriculum_references: list[dict[str, object]] | None,
    render_mode: RenderMode = "pdf_classic",
) -> RunArtifacts:
    """Multi-worksheet pipeline — produces 2-3 mini-worksheets per lesson."""
    from companion.character_identity import resolve_character_identity
    from companion.schema import LearnerProfile
    from render.asset_gen import compute_worksheet_hash, generate_worksheet_assets
    from render.pose_planner import plan_scenes, plan_word_pictures
    from skill.schema import LiteracySkillModel
    from theme.schema import ThemeConfig

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(profile, LearnerProfile)
    assert isinstance(theme, ThemeConfig)
    char_spec = theme.character_spec if theme.character_spec.art_style else None
    character_identity = resolve_character_identity(
        profile,
        theme_id,
        character_spec=char_spec,
    )

    worksheets = adapt_lesson(
        skill_model,
        profile,
        theme_id=theme_id,
        rag_prior_adaptations=rag_prior_adaptations,
        rag_curriculum_references=rag_curriculum_references,
        artifacts_dir=str(artifacts),
        character_identity=character_identity,
    )
    logger.info("  Generated %s mini-worksheets", len(worksheets))

    # Stage 5c: Pedagogical judge verdict
    # When the LLM orchestrator ran, it already judged the adaptation and
    # wrote judge_verdict.json. Read it back if present; otherwise run the
    # judge as advisory-only (e.g., when the deterministic engine was used).
    judge_json = artifacts / "judge_verdict.json"
    judge_result: dict[str, object]
    pedagogical_judge_passed: bool | None = None
    if judge_json.exists():
        judge_result = json.loads(judge_json.read_text())
        approved = judge_result.get("approved")
        if isinstance(approved, bool):
            pedagogical_judge_passed = approved
        score = judge_result.get("overall_score")
        if approved is True:
            logger.info("  Pedagogical judge: APPROVED (%.2f)", score)
        elif approved is False:
            logger.warning(
                "  Pedagogical judge: NOT APPROVED (%.2f) — %s",
                score,
                judge_result.get("rationale", ""),
            )
    else:
        judge_result = {"enabled": False}
        try:
            from adapt.llm_judge import judge_adaptation

            verdict = judge_adaptation(skill_model, worksheets)
            if verdict is not None:
                judge_result = verdict.model_dump()
                pedagogical_judge_passed = verdict.approved
                if verdict.approved:
                    logger.info("  Pedagogical judge: APPROVED (%.2f)", verdict.overall_score)
                else:
                    logger.warning(
                        "  Pedagogical judge: NOT APPROVED (%.2f) — %s",
                        verdict.overall_score,
                        verdict.rationale,
                    )
        except Exception as exc:
            logger.warning("  Pedagogical judge skipped: %s", exc)
        judge_json.write_text(json.dumps(judge_result, indent=2))

    skip_review = _skip_ai_review(judge_result)

    pdf_paths: list[str] = []
    adapted_summaries: list[dict[str, str | int | float | bool]] = []
    validation_runs: list[dict[str, bool]] = []
    ai_review_passed = True
    content_hash = hashlib.sha256(
        f"{source_image_hash}:{profile.name}:{theme_id}".encode()
    ).hexdigest()[:12]
    strategy = resolve_render_strategy(render_mode)
    renderer_artifact_paths: list[str] = []
    render_results: list[RenderResult] = []
    last_design_spec = None
    last_render_result = None

    for i, adapted in enumerate(worksheets, start=1):
        ws_title = adapted.worksheet_title or "Untitled"
        logger.info("  Processing worksheet %s/%s: %s", i, len(worksheets), ws_title)

        adapted_json = artifacts / f"adapted_model_{i}.json"
        adapted_json.write_text(adapted.model_dump_json(indent=2))

        if skip_review:
            logger.info(
                "  AI quality review skipped for worksheet %s/%s (planner-v2 already judged)",
                i,
                len(worksheets),
            )
        else:
            logger.info("  AI quality review for worksheet %s/%s...", i, len(worksheets))
            adapted, reviews = review_adapted_worksheet(adapted)
            review_json = artifacts / f"ai_review_{i}.json"
            review_json.write_text(json.dumps([review.to_dict() for review in reviews], indent=2))
            if reviews:
                latest_review = reviews[-1]
                ai_review_passed = ai_review_passed and latest_review.passed
                if latest_review.passed:
                    logger.info("  AI quality review_%s: PASSED", i)
                else:
                    logger.warning(
                        "  AI quality review_%s: %s issues remaining after %s iterations",
                        i,
                        len(latest_review.issues),
                        len(reviews),
                    )
            adapted_json.write_text(adapted.model_dump_json(indent=2))
            worksheets[i - 1] = adapted

        apply_theme(adapted, theme)

        # Pass theme character spec for theme-aware scene prompts
        identity = resolve_character_identity(
            profile,
            theme_id,
            character_spec=char_spec,
        )
        asset_manifest = None
        if _should_generate_chunk_assets(render_mode):
            try:
                scenes = plan_scenes(adapted, character_spec=char_spec)
                word_prompts = plan_word_pictures(adapted)
                ws_hash = compute_worksheet_hash(
                    adapted.source_hash,
                    i,
                    theme_id,
                    identity_version=identity.identity_version,
                )

                # Pass style sheet for theme-accurate character rendering
                style_sheet = None
                if profile.avatar and profile.avatar.style_sheet:
                    style_sheet = profile.avatar.style_sheet

                asset_manifest = generate_worksheet_assets(
                    scenes,
                    word_prompts,
                    ws_hash,
                    character_name=(
                        profile.avatar.base_character if profile.avatar else "rainbow_roblox"
                    ),
                    style_sheet=style_sheet,
                    character_spec=char_spec,
                    profile=profile,
                    theme_id=theme_id,
                    identity=identity,
                )
            except Exception as exc:
                logger.warning("  Asset generation skipped: %s", exc)
        else:
            logger.info("  Asset generation skipped (image_gen renders full pages)")

        pdf_filename = f"worksheet_{content_hash}_{i}of{len(worksheets)}.pdf"
        pdf_path = str(output / pdf_filename)
        render_artifacts_dir = _render_artifacts_dir(artifacts, strategy, i)
        design_spec = compile_worksheet_design_spec(
            adapted,
            theme,
            profile,
            render_mode=render_mode,
        )
        last_design_spec = design_spec
        render_result = strategy.render(
            RenderContext(
                design_spec=design_spec,
                adapted=adapted,
                theme=theme,
                output_path=Path(pdf_path),
                artifacts_dir=render_artifacts_dir,
                asset_manifest=asset_manifest,
                character_identity=identity,
            )
        )
        last_render_result = render_result
        render_results.append(render_result)
        renderer_artifact_paths.extend(render_result.artifact_paths)
        if render_result.pdf_path:
            pdf_paths.append(render_result.pdf_path)
            logger.info("  Output: %s", render_result.pdf_path)
            ws_validation = _validate_and_report(
                skill_model,
                adapted,
                profile,
                render_result.pdf_path,
                artifacts,
                suffix=f"_{i}",
                run_content_coverage=False,
            )
        else:
            logger.info("  Output: prompt artifacts only")
            ws_validation = _validate_non_pdf_and_report(
                skill_model,
                adapted,
                profile,
                artifacts,
                suffix=f"_{i}",
            )
        validation_runs.append(ws_validation)
        adapted_summaries.append(_build_adapted_summary(adapted))

    _validate_format_variety(worksheets)

    validation_results = _aggregate_validation_results(validation_runs)
    content_result = _validate_package_content_coverage(skill_model, worksheets, artifacts)
    time_budget_result = validate_lesson_time_budget(worksheets)
    time_budget_json = artifacts / "validation_lesson_time_budget.json"
    time_budget_json.write_text(
        json.dumps({"lesson_time_budget": time_budget_result.model_dump()}, indent=2)
    )
    for violation in time_budget_result.violations:
        if violation.severity == "warning":
            logger.warning("  Lesson time budget: %s", violation.message)

    validation_results["content_coverage_passed"] = content_result.passed
    validation_results["lesson_time_budget_passed"] = time_budget_result.passed
    validation_results["ai_review_passed"] = ai_review_passed
    validation_results["renderer_produces_pdf"] = strategy.produces_pdf
    validation_results["renderer_experimental"] = strategy.experimental
    if pedagogical_judge_passed is not None:
        validation_results["pedagogical_judge_passed"] = pedagogical_judge_passed
    validation_results["all_validators_passed"] = (
        validation_results.get("all_validators_passed", False)
        and content_result.passed
        and time_budget_result.passed
        and ai_review_passed
        and (pedagogical_judge_passed if pedagogical_judge_passed is not None else True)
        and strategy.produces_pdf
    )

    # Generate cover image + cover page + merge into single PDF
    if strategy.produces_pdf:
        pdf_paths = _merge_lesson_package(
            skill_model=skill_model,
            worksheets=worksheets,
            theme=theme,
            theme_id=theme_id,
            profile=profile,
            content_hash=content_hash,
            pdf_paths=pdf_paths,
            output=output,
        )
        renderer_artifact_paths = pdf_paths
        final_print_result = _validate_final_print_quality(pdf_paths[0], artifacts)
        validation_results["print_quality_passed"] = (
            validation_results.get("print_quality_passed", False) and final_print_result.passed
        )
        validation_results["all_validators_passed"] = (
            validation_results.get("all_validators_passed", False) and final_print_result.passed
        )

    if last_design_spec is not None and last_render_result is not None:
        renderer_artifact_paths = _merge_artifact_paths(
            renderer_artifact_paths,
            [_write_renderer_manifest(artifacts, last_render_result, last_design_spec)],
        )

    logger.info(
        "Done! Render mode %s complete (%s worksheets)",
        strategy.renderer_id,
        len(worksheets),
    )
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
        render_mode=render_mode,
        renderer_id=_aggregate_renderer_id(render_results, strategy.renderer_id),
        renderer_experimental=strategy.experimental,
        renderer_artifact_paths=renderer_artifact_paths,
    )


def _render_artifacts_dir(artifacts: Path, strategy: RenderStrategy, worksheet_number: int) -> Path:
    """Per-worksheet artifact isolation for renderers that emit diagnostics."""
    if strategy.produces_pdf and not strategy.experimental:
        return artifacts
    return artifacts / f"render_{worksheet_number}"


def _merge_lesson_package(
    skill_model: object,
    worksheets: list[AdaptedActivityModel],
    theme: object,
    theme_id: str,
    profile: object,
    content_hash: str,
    pdf_paths: list[str],
    output: Path,
) -> list[str]:
    """Generate cover page + merge all worksheets into a single lesson PDF.

    Returns updated pdf_paths (single merged file).
    """
    from companion.character_identity import resolve_character_identity
    from companion.schema import LearnerProfile
    from render.asset_gen import generate_cover_image
    from render.merge import merge_worksheet_package
    from skill.schema import LiteracySkillModel
    from theme.schema import ThemeConfig

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(profile, LearnerProfile)
    assert isinstance(theme, ThemeConfig)
    avatar = getattr(profile, "avatar", None)
    identity = resolve_character_identity(
        profile,
        theme_id,
        pose="celebrating",
        character_spec=theme.character_spec if theme.character_spec.art_style else None,
    )

    # Generate cover image (optional — falls back gracefully)
    cover_image_path = generate_cover_image(
        skill_description=f"{skill_model.domain}: {skill_model.specific_skill}",
        target_words=skill_model.target_words[:10],
        theme_spec=theme.character_spec if theme.character_spec.art_style else None,
        worksheet_hash=content_hash,
        character_name=avatar.base_character if avatar else "rainbow_roblox",
        style_sheet=(avatar.style_sheet if avatar and avatar.style_sheet else None),
        profile=profile,
        theme_id=theme_id,
        identity=identity,
    )

    # Render cover page PDF
    cover_path = str(output / f"_cover_{content_hash}.pdf")
    render_cover_page(
        skill_model=skill_model,
        worksheets=worksheets,
        theme=theme,
        output_path=cover_path,
        cover_image_path=cover_image_path,
        profile_name=getattr(profile, "name", None),
    )

    # Merge into single PDF
    merged_filename = f"lesson_{content_hash}.pdf"
    merged_path = str(output / merged_filename)
    merge_worksheet_package(cover_path, pdf_paths, merged_path, cleanup=True)

    return [merged_path]


def _skip_ai_review(judge_result: dict[str, object]) -> bool:
    """Planner-v2 output was already judged on full item text.

    The legacy ai_review loop (up to 3 LLM calls per worksheet) only adds
    value for deterministic/legacy output, where OCR artifacts are real and
    no full-text judge gated the content.
    """
    return judge_result.get("planner_version") == 2


def _should_generate_chunk_assets(render_mode: str) -> bool:
    """Per-chunk scene/word images only serve pdf_classic-style layouts.

    The image_gen renderer generates full pages and never reads the asset
    manifest; if it falls back to pdf_classic mid-run, that worksheet renders
    with the deterministic local art (same degradation as asset-gen failure).
    """
    return render_mode != "image_gen"


def _validate_and_report(
    skill_model: object,
    adapted: object,
    profile: object,
    pdf_path: str,
    artifacts: Path,
    suffix: str = "",
    run_content_coverage: bool = True,
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
    adhd_result = validate_adhd_compliance(adapted, rules=build_rules(profile))
    print_result = validate_print_quality(pdf_path)

    results = [
        ("Skill parity", "skill_parity", parity_result),
        ("Age band", "age_band", age_result),
        ("ADHD compliance", "adhd_compliance", adhd_result),
        ("Print quality", "print_quality", print_result),
    ]
    if run_content_coverage:
        content_result = validate_content_coverage(skill_model, adapted)
        results.insert(1, ("Content coverage", "content_coverage", content_result))

    validation = {key: result.model_dump() for _, key, result in results}
    val_json = artifacts / f"validation{suffix}.json"
    val_json.write_text(json.dumps(validation, indent=2))

    all_passed = all(result.passed for _, _, result in results)

    if all_passed:
        logger.info("  All validations passed%s!", suffix)
    else:
        for name, _, result in results:
            if not result.passed:
                for violation in result.violations:
                    if violation.severity == "error":
                        logger.error("  %s%s: %s", name, suffix, violation.message)

    for name, _, result in results:
        for violation in result.violations:
            if violation.severity == "warning":
                logger.warning("  %s%s: %s", name, suffix, violation.message)

    flags = {
        "skill_parity_passed": parity_result.passed,
        "age_band_passed": age_result.passed,
        "adhd_compliance_passed": adhd_result.passed,
        "print_quality_passed": print_result.passed,
        "all_validators_passed": all_passed,
    }
    if run_content_coverage:
        flags["content_coverage_passed"] = validation["content_coverage"]["passed"]
    return flags


def _write_renderer_manifest(
    artifacts: Path,
    render_result: RenderResult,
    design_spec: WorksheetDesignSpec,
) -> str:
    """Persist renderer provenance for the current render run."""
    manifest_path = artifacts / "renderer_manifest.json"
    manifest: dict[str, object] = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text())
            if isinstance(loaded, dict):
                manifest.update(loaded)
        except json.JSONDecodeError:
            manifest = {}

    if render_result.renderer_id == "image_prompt":
        manifest.setdefault("provider", "offline_prompt_only")

    manifest.update(
        {
            "renderer_id": render_result.renderer_id,
            "render_mode": design_spec.render_mode,
            "experimental": render_result.experimental,
            "produces_pdf": render_result.produces_pdf,
            "pdf_path": render_result.pdf_path,
            "artifact_paths": render_result.artifact_paths,
            "spec_version": design_spec.spec_version,
            "source_hash": design_spec.source_hash,
            "skill_model_hash": design_spec.skill_model_hash,
            "learner_profile_hash": design_spec.learner_profile_hash,
            "theme_id": design_spec.theme_id,
            "worksheet_number": design_spec.worksheet_number,
            "worksheet_count": design_spec.worksheet_count,
            "required_text_count": len(design_spec.required_text),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return str(manifest_path)


def _aggregate_renderer_id(results: list[RenderResult], requested: str) -> str:
    """Report the requested renderer only if every worksheet actually used it.

    Any per-worksheet fallback (e.g., image_gen -> pdf_classic) surfaces the
    fallback id so downstream consumers (render battery, RAG metadata) see it.
    """
    for result in results:
        if result.renderer_id != requested:
            return result.renderer_id
    return requested


def _merge_artifact_paths(primary: list[str], extra: list[str]) -> list[str]:
    merged: list[str] = []
    for path in [*primary, *extra]:
        if path not in merged:
            merged.append(path)
    return merged


def _validate_non_pdf_and_report(
    skill_model: object,
    adapted: object,
    profile: object,
    artifacts: Path,
    suffix: str = "",
) -> dict[str, bool]:
    """Run non-PDF validations for prompt-only experimental renderers."""
    from adapt.schema import AdaptedActivityModel
    from companion.schema import LearnerProfile
    from skill.schema import LiteracySkillModel

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(adapted, AdaptedActivityModel)
    assert isinstance(profile, LearnerProfile)

    parity_result = validate_skill_parity(skill_model, adapted)
    content_result = validate_content_coverage(skill_model, adapted)
    age_result = validate_age_band(adapted, profile.grade_level)
    adhd_result = validate_adhd_compliance(adapted, rules=build_rules(profile))

    validation = {
        "skill_parity": parity_result.model_dump(),
        "content_coverage": content_result.model_dump(),
        "age_band": age_result.model_dump(),
        "adhd_compliance": adhd_result.model_dump(),
        "print_quality": {
            "validator": "print_quality",
            "passed": False,
            "checks_run": 0,
            "violations": [
                {
                    "check": "pdf_not_produced",
                    "message": "Prompt-only renderer did not produce a print-ready PDF.",
                    "severity": "error",
                    "details": {},
                }
            ],
        },
    }
    val_json = artifacts / f"validation{suffix}.json"
    val_json.write_text(json.dumps(validation, indent=2))

    return {
        "skill_parity_passed": parity_result.passed,
        "content_coverage_passed": content_result.passed,
        "age_band_passed": age_result.passed,
        "adhd_compliance_passed": adhd_result.passed,
        "print_quality_passed": False,
        "all_validators_passed": False,
    }


def _validate_package_content_coverage(
    skill_model: object,
    worksheets: Sequence[AdaptedActivityModel],
    artifacts: Path,
) -> ValidationResult:
    """Run package-level content coverage for multi-worksheet output."""
    from skill.schema import LiteracySkillModel

    assert isinstance(skill_model, LiteracySkillModel)

    result = validate_content_coverage_for_package(skill_model, worksheets)
    validation = {"content_coverage": result.model_dump()}
    val_json = artifacts / "validation_content_coverage.json"
    val_json.write_text(json.dumps(validation, indent=2))

    if not result.passed:
        for violation in result.violations:
            if violation.severity == "error":
                logger.error("  Content coverage package: %s", violation.message)

    for violation in result.violations:
        if violation.severity == "warning":
            logger.warning("  Content coverage package: %s", violation.message)

    return result


def _validate_final_print_quality(pdf_path: str, artifacts: Path) -> ValidationResult:
    """Run print checks on the final merged lesson PDF and persist diagnostics."""
    result = validate_print_quality(pdf_path)
    validation = {"print_quality": result.model_dump()}
    val_json = artifacts / "validation_final_print_quality.json"
    val_json.write_text(json.dumps(validation, indent=2))

    if not result.passed:
        for violation in result.violations:
            if violation.severity == "error":
                logger.error("  Print quality final package: %s", violation.message)

    for violation in result.violations:
        if violation.severity == "warning":
            logger.warning("  Print quality final package: %s", violation.message)

    return result


def _aggregate_validation_results(
    validations: Sequence[dict[str, bool]],
) -> dict[str, bool]:
    """Aggregate per-worksheet validation flags across a run."""
    if not validations:
        return {
            "skill_parity_passed": False,
            "content_coverage_passed": False,
            "age_band_passed": False,
            "adhd_compliance_passed": False,
            "print_quality_passed": False,
            "all_validators_passed": False,
        }

    keys: set[str] = set()
    for run in validations:
        keys.update(run.keys())

    aggregated = {key: all(run.get(key, False) for run in validations) for key in keys}
    validator_keys = [
        key for key in aggregated if key.endswith("_passed") and key != "all_validators_passed"
    ]
    aggregated["all_validators_passed"] = all(aggregated[key] for key in validator_keys)
    return aggregated


def _build_adapted_summary(
    adapted: AdaptedActivityModel,
) -> dict[str, str | int | float | bool]:
    """Build a compact adaptation summary for RAG indexing metadata."""
    total_items = sum(len(chunk.items) for chunk in adapted.chunks)
    response_formats = sorted({chunk.response_format for chunk in adapted.chunks})
    estimated_minutes = sum(
        _extract_estimated_minutes(chunk.time_estimate) for chunk in adapted.chunks
    )
    distractors = sorted(_extract_distractor_words(adapted))
    curriculum_supported_items, curriculum_lesson_ids = _extract_curriculum_support(adapted)

    return {
        "worksheet_title": adapted.worksheet_title or "Untitled",
        "worksheet_number": adapted.worksheet_number,
        "chunk_count": len(adapted.chunks),
        "total_items": total_items,
        "response_formats": ",".join(response_formats),
        "estimated_minutes": estimated_minutes,
        "distractor_words": ",".join(distractors),
        "curriculum_supported_items": curriculum_supported_items,
        "curriculum_lesson_ids": ",".join(curriculum_lesson_ids),
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
                    answer.strip().lower() for answer in item.answer.split(",") if answer.strip()
                }

            for option in item.options:
                normalized = option.strip().lower()
                if normalized and normalized not in answers:
                    distractors.add(normalized)

    return distractors


def _extract_curriculum_support(
    adapted: AdaptedActivityModel,
) -> tuple[int, list[str]]:
    """Extract curriculum-support annotations from adapted item metadata."""
    supported_items = 0
    lesson_ids: set[str] = set()

    for chunk in adapted.chunks:
        for item in chunk.items:
            if item.metadata.get("curriculum_supported") is True:
                supported_items += 1
            raw_lesson_ids = str(item.metadata.get("curriculum_lesson_ids", ""))
            for lesson_id in raw_lesson_ids.split(","):
                normalized = lesson_id.strip()
                if normalized:
                    lesson_ids.add(normalized)

    return supported_items, sorted(lesson_ids)


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
        selected_metadata.append(_rag_result_to_metadata(result))

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
    }

    if not selected_metadata:
        return None, diagnostics
    return selected_metadata, diagnostics


def _select_rag_curriculum_context(
    rag_context: object,
) -> list[dict[str, object]] | None:
    """Return curriculum references with metadata and document text preserved."""
    try:
        from rag.retrieval import RAGContext
    except ImportError:
        return None

    if not isinstance(rag_context, RAGContext):
        return None

    if not rag_context.curriculum_references:
        return None

    return [_rag_result_to_metadata(result) for result in rag_context.curriculum_references]


def _rag_result_to_metadata(result: object) -> dict[str, object]:
    """Flatten retrieval metadata for downstream adaptation hooks."""
    try:
        from rag.retrieval import RetrievalResult
    except ImportError:
        return {}

    if not isinstance(result, RetrievalResult):
        return {}

    metadata = {key: value for key, value in result.metadata.items()}
    metadata["_rag_score"] = float(result.score)
    metadata["_rag_doc_id"] = result.doc_id
    if result.document:
        metadata["_rag_document"] = result.document
    return metadata


if __name__ == "__main__":
    transform()
