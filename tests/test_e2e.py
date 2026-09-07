"""Offline semantic golden tests for source-agnostic objective preservation."""

from pathlib import Path

import pytest

from adapt.engine import adapt_lesson
from adapt.objective_ledger import build_objective_ledger
from companion.schema import Accommodations, LearnerProfile
from render.pdf import render_worksheet
from skill.schema import LiteracySkillModel, SourceItem
from theme.engine import load_theme
from validate.objective_coverage import build_evidence_index, evaluate_objective_coverage
from validate.print_checks import validate_print_quality


def test_non_corpus_drop_e_objective_semantic_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    monkeypatch.setenv("WORKSHEET_SKIP_ASSET_GEN", "1")
    monkeypatch.setenv("WORKSHEET_MAX_WORKSHEETS", "auto")
    monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)

    skill = LiteracySkillModel(
        grade_level="2",
        domain="phonics",
        specific_skill="drop_e_rule",
        learning_objectives=[
            "Read derived words",
            "Spell derived words by dropping final e",
            "Read the pattern in connected text",
        ],
        target_words=["smiled", "smiling", "closed", "closing", "cuter", "cutest"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="smile -> smiled -> smiling",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="close -> closed -> closing",
                source_region_index=1,
            ),
            SourceItem(
                item_type="word_chain",
                content="cute -> cuter -> cutest",
                source_region_index=2,
            ),
            SourceItem(
                item_type="passage",
                content=(
                    "A Calm Race\n\nMia smiled at the start. She was smiling as she ran. "
                    "The gate closed behind her. A friend was closing the next gate."
                ),
                source_region_index=3,
            ),
        ],
        extraction_confidence=1.0,
        template_type="unknown",
    )
    profile = LearnerProfile(
        name="Test",
        grade_level="2",
        accommodations=Accommodations(
            chunking_level="medium", response_format_prefs=["write", "circle"]
        ),
    )

    worksheets = adapt_lesson(skill, profile, theme_id="space", artifacts_dir=str(tmp_path))
    items = [item for worksheet in worksheets for chunk in worksheet.chunks for item in chunk.items]
    transformation_items = [item for item in items if item.transformation is not None]
    transformations = [item.transformation for item in transformation_items]
    assert all(transformation is not None for transformation in transformations)
    golden = {
        "rule_ids": sorted(
            {transformation.rule_id for transformation in transformations if transformation}
        ),
        "answers": [item.answer for item in transformation_items],
        "has_picture_match": any(item.response_format == "match" for item in items),
    }
    assert golden == {
        "rule_ids": ["drop_e_rule"],
        "answers": ["smiling", "closed", "closing", "cuter", "cutest"],
        "has_picture_match": False,
    }
    assert all(item.answer not in item.content for item in transformation_items if item.answer)

    ledger = build_objective_ledger(skill, corpus_lookup=lambda _lesson: None)
    coverage = evaluate_objective_coverage(
        ledger, build_evidence_index(worksheets, ledger), worksheets=worksheets
    )
    assert coverage.status == "pass"

    theme = load_theme("space")
    for index, worksheet in enumerate(worksheets, start=1):
        pdf_path = tmp_path / f"golden-{index}.pdf"
        render_worksheet(worksheet, theme, str(pdf_path))
        assert validate_print_quality(str(pdf_path)).passed
