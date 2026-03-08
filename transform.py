"""CLI entry point: transform a worksheet photo into an ADHD-adapted PDF."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import click

from adapt.engine import adapt_activity
from capture.preprocess import preprocess_page
from capture.store import store_master
from companion.schema import load_profile
from extract.heuristics import map_to_source_model
from extract.ocr import extract_text_with_fallback
from render.pdf import render_worksheet
from skill.extractor import extract_skill
from theme.engine import apply_theme, load_theme
from validate.adhd_compliance import validate_adhd_compliance
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

    # Stage 3: OCR + Source extraction
    logger.info("Stage 3: Running OCR and source extraction...")
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
    adapted = adapt_activity(skill_model, profile, theme_id=theme_id)

    adapted_json = artifacts / "adapted_model.json"
    adapted_json.write_text(adapted.model_dump_json(indent=2))
    logger.info(f"  Chunks: {len(adapted.chunks)}, Grade: {adapted.grade_level}")

    # Stage 6: Apply theme
    logger.info("Stage 6: Applying theme...")
    theme = load_theme(theme_id)
    apply_theme(adapted, theme)  # validates theme + adapted compatibility

    # Stage 7: Render PDF
    logger.info("Stage 7: Rendering PDF...")
    # Generate deterministic output filename
    content_hash = hashlib.sha256(
        f"{master.image_hash}:{profile.name}:{theme_id}".encode()
    ).hexdigest()[:12]
    pdf_filename = f"worksheet_{content_hash}.pdf"
    pdf_path = str(output / pdf_filename)
    render_worksheet(adapted, theme, pdf_path)
    logger.info(f"  Output: {pdf_path}")

    # Stage 8: Validate
    logger.info("Stage 8: Running validation...")

    # Skill parity
    parity_result = validate_skill_parity(skill_model, adapted)
    age_result = validate_age_band(adapted, profile.grade_level)
    adhd_result = validate_adhd_compliance(adapted)
    print_result = validate_print_quality(pdf_path)

    # Persist validation results
    validation = {
        "skill_parity": parity_result.model_dump(),
        "age_band": age_result.model_dump(),
        "adhd_compliance": adhd_result.model_dump(),
        "print_quality": print_result.model_dump(),
    }
    val_json = artifacts / "validation.json"
    val_json.write_text(json.dumps(validation, indent=2))

    # Report results
    all_passed = all([
        parity_result.passed,
        age_result.passed,
        adhd_result.passed,
        print_result.passed,
    ])

    if all_passed:
        logger.info("All validations passed!")
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
                        logger.error(f"  {name}: {v.message}")

    # Report warnings
    for name, res in [
        ("Skill parity", parity_result),
        ("Age band", age_result),
        ("ADHD compliance", adhd_result),
        ("Print quality", print_result),
    ]:
        for v in res.violations:
            if v.severity == "warning":
                logger.warning(f"  {name}: {v.message}")

    logger.info(f"Done! PDF saved to: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    transform()
