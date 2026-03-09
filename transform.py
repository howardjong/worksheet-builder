"""CLI entry point: transform a worksheet photo into an ADHD-adapted PDF."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import click

# Load .env before anything else
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from adapt.engine import adapt_activity, adapt_lesson
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


def run_pipeline(
    input_path: str,
    profile_path: str,
    theme_id: str,
    output_dir: str,
    artifacts_dir: str,
) -> str:
    """Run the full transformation pipeline. Returns path to the output PDF.

    Stages:
    1. Preprocess image → clean page
    2. Store master image
    3. OCR → SourceWorksheetModel
    4. Extract skill → LiteracySkillModel
    5. Adapt for ADHD → AdaptedActivityModel
    6. Apply theme → ThemedModel
    7. Render → PDF
    8. Validate → skill-parity, ADHD compliance, print quality
    9. Persist all artifacts
    """
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

    # Try AI vision first (much faster and more accurate on phone photos)
    vision_model = extract_with_vision(preprocessed_path, master.image_hash)
    if vision_model is not None:
        source_model = vision_model
        logger.info("  Using AI vision extraction")
    else:
        # Fall back to OCR if no AI API key available
        logger.info("  AI vision unavailable — falling back to OCR...")
        ocr_result = extract_text_with_fallback(preprocessed_path)
        source_model = map_to_source_model(ocr_result, master.image_hash)

    # Persist source model
    source_json = artifacts / "source_model.json"
    source_json.write_text(source_model.model_dump_json(indent=2))
    logger.info(f"  Template: {source_model.template_type}, Regions: {len(source_model.regions)}")

    # Stage 4: Skill extraction
    logger.info("Stage 4: Extracting literacy skill...")
    skill_model = extract_skill(source_model)

    skill_json = artifacts / "skill_model.json"
    skill_json.write_text(skill_model.model_dump_json(indent=2))
    logger.info(f"  Domain: {skill_model.domain}, Skill: {skill_model.specific_skill}")

    # Stage 5: ADHD adaptation
    logger.info("Stage 5: Adapting for ADHD...")
    profile = load_profile(profile_path)

    # Stage 6: Load theme (needed before deciding single vs multi)
    logger.info("Stage 6: Loading theme...")
    theme = load_theme(theme_id)

    # Determine single vs multi-worksheet mode
    if theme.multi_worksheet:
        return _run_multi_worksheet_pipeline(
            skill_model, profile, theme, theme_id,
            master.image_hash, output, artifacts,
        )
    else:
        return _run_single_worksheet_pipeline(
            skill_model, profile, theme, theme_id,
            master.image_hash, output, artifacts, profile_path,
        )


def _run_single_worksheet_pipeline(
    skill_model: object,
    profile: object,
    theme: object,
    theme_id: str,
    image_hash: str,
    output: Path,
    artifacts: Path,
    profile_path: str,
) -> str:
    """Original single-worksheet pipeline (backward compatible)."""
    from companion.avatar import compose_avatar
    from companion.schema import LearnerProfile
    from skill.schema import LiteracySkillModel
    from theme.schema import ThemeConfig

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(profile, LearnerProfile)
    assert isinstance(theme, ThemeConfig)

    adapted = adapt_activity(skill_model, profile, theme_id=theme_id)

    adapted_json = artifacts / "adapted_model.json"
    adapted_json.write_text(adapted.model_dump_json(indent=2))
    logger.info(f"  Chunks: {len(adapted.chunks)}, Grade: {adapted.grade_level}")

    # Stage 5b: AI quality review (iterative)
    logger.info("Stage 5b: AI quality review...")
    adapted, reviews = review_adapted_worksheet(adapted)

    # Persist review results
    review_data = [r.to_dict() for r in reviews]
    review_json = artifacts / "ai_review.json"
    review_json.write_text(json.dumps(review_data, indent=2))

    if reviews and reviews[-1].passed:
        logger.info("  AI quality review: PASSED")
    elif reviews:
        logger.warning(
            f"  AI quality review: {len(reviews[-1].issues)} issues remaining "
            f"after {len(reviews)} iterations"
        )

    # Re-persist adapted model (may have been modified by AI review)
    adapted_json.write_text(adapted.model_dump_json(indent=2))

    # Apply theme
    apply_theme(adapted, theme)

    # Compose avatar
    avatar_path: str | None = None
    if profile.avatar:
        logger.info("Stage 6b: Composing avatar...")
        avatar_result = compose_avatar(profile, size="companion", theme_id=theme_id)
        if avatar_result:
            avatar_path = str(avatar_result)
            logger.info(f"  Avatar: {profile.avatar.base_character} -> {avatar_path}")

    # Stage 7: Render PDF
    logger.info("Stage 7: Rendering PDF...")
    content_hash = hashlib.sha256(
        f"{image_hash}:{profile.name}:{theme_id}".encode()
    ).hexdigest()[:12]
    pdf_filename = f"worksheet_{content_hash}.pdf"
    pdf_path = str(output / pdf_filename)
    render_worksheet(adapted, theme, pdf_path, avatar_image=avatar_path)
    logger.info(f"  Output: {pdf_path}")

    # Stage 8: Validate
    logger.info("Stage 8: Running validation...")
    _validate_and_report(skill_model, adapted, profile, pdf_path, artifacts)

    logger.info(f"Done! PDF saved to: {pdf_path}")
    return pdf_path


def _run_multi_worksheet_pipeline(
    skill_model: object,
    profile: object,
    theme: object,
    theme_id: str,
    image_hash: str,
    output: Path,
    artifacts: Path,
) -> str:
    """Multi-worksheet pipeline — produces 2-3 mini-worksheets per lesson."""
    from companion.schema import LearnerProfile
    from render.asset_gen import (
        compute_worksheet_hash,
        generate_worksheet_assets,
    )
    from render.pose_planner import plan_scenes, plan_word_pictures
    from skill.schema import LiteracySkillModel
    from theme.schema import ThemeConfig

    assert isinstance(skill_model, LiteracySkillModel)
    assert isinstance(profile, LearnerProfile)
    assert isinstance(theme, ThemeConfig)

    worksheets = adapt_lesson(skill_model, profile, theme_id=theme_id)
    logger.info(f"  Generated {len(worksheets)} mini-worksheets")

    pdf_paths: list[str] = []
    content_hash = hashlib.sha256(
        f"{image_hash}:{profile.name}:{theme_id}".encode()
    ).hexdigest()[:12]

    for i, adapted in enumerate(worksheets):
        ws_num = i + 1
        ws_title = adapted.worksheet_title or "Untitled"
        logger.info(
            f"  Processing worksheet {ws_num}/{len(worksheets)}: "
            f"{ws_title}"
        )

        # Persist adapted model
        adapted_json = artifacts / f"adapted_model_{ws_num}.json"
        adapted_json.write_text(adapted.model_dump_json(indent=2))

        # Apply theme
        apply_theme(adapted, theme)

        # Stage 6c: Generate AI assets (scenes + word pictures)
        asset_manifest = None
        try:
            scenes = plan_scenes(adapted)
            word_prompts = plan_word_pictures(adapted)
            ws_hash = compute_worksheet_hash(adapted.source_hash, ws_num, theme_id)
            asset_manifest = generate_worksheet_assets(scenes, word_prompts, ws_hash)
        except Exception as e:
            logger.warning(f"  Asset generation skipped: {e}")

        # Stage 7: Render PDF
        pdf_filename = f"worksheet_{content_hash}_{ws_num}of{len(worksheets)}.pdf"
        pdf_path = str(output / pdf_filename)
        render_worksheet(adapted, theme, pdf_path, asset_manifest=asset_manifest)
        pdf_paths.append(pdf_path)
        logger.info(f"  Output: {pdf_path}")

        # Stage 8: Validate each worksheet
        _validate_and_report(
            skill_model, adapted, profile,
            pdf_path, artifacts, suffix=f"_{ws_num}",
        )

    # Validate format variety across the set
    _validate_format_variety(worksheets)

    logger.info(f"Done! {len(pdf_paths)} PDFs saved to: {output}")
    return pdf_paths[0] if pdf_paths else ""


def _validate_and_report(
    skill_model: object,
    adapted: object,
    profile: object,
    pdf_path: str,
    artifacts: Path,
    suffix: str = "",
) -> None:
    """Run validation checks and persist results."""
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
        logger.info(f"  All validations passed{suffix}!")
    else:
        for name, res in [
            ("Skill parity", parity_result),
            ("Age band", age_result),
            ("ADHD compliance", adhd_result),
            ("Print quality", print_result),
        ]:
            if not res.passed:
                for v in res.violations:
                    if v.severity == "error":
                        logger.error(f"  {name}{suffix}: {v.message}")

    for name, res in [
        ("Skill parity", parity_result),
        ("Age band", age_result),
        ("ADHD compliance", adhd_result),
        ("Print quality", print_result),
    ]:
        for v in res.violations:
            if v.severity == "warning":
                logger.warning(f"  {name}{suffix}: {v.message}")


def _validate_format_variety(worksheets: list[object]) -> None:
    """Check that the multi-worksheet set has response format variety."""
    from adapt.schema import AdaptedActivityModel

    all_formats: set[str] = set()
    for ws in worksheets:
        assert isinstance(ws, AdaptedActivityModel)
        for chunk in ws.chunks:
            all_formats.add(chunk.response_format)

    if len(all_formats) < 2:
        logger.warning(
            f"  Format variety: only {len(all_formats)} format(s) used across "
            f"{len(worksheets)} worksheets. Recommend at least 2 different formats."
        )


if __name__ == "__main__":
    transform()
