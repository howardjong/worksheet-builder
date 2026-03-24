"""Tests for artifact backfill into the RAG store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from extract.schema import PIPELINE_VERSION, SourceRegion, SourceWorksheetModel
from rag.backfill import backfill
from skill.schema import LiteracySkillModel, SourceItem


def test_backfill_reconstructs_index_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_root = tmp_path / "outputs"
    run_dir = artifacts_root / "lesson59"
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True)

    source = SourceWorksheetModel(
        source_image_hash="hash123",
        pipeline_version=PIPELINE_VERSION,
        template_type="ufli_word_work",
        regions=[
            SourceRegion(
                type="word_list",
                content="grade chase",
                bbox=(0, 0, 10, 10),
                confidence=0.9,
                metadata={},
            )
        ],
        raw_text="grade chase slide",
        ocr_engine="gemini_vision",
        low_confidence_flags=[],
    )
    skill = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["grade", "chase"],
        response_types=["circle", "trace"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade chase",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.9,
        template_type="ufli_word_work",
    )
    adapted_one = _adapted_model(worksheet_number=1, worksheet_count=2, title="Word Discovery")
    adapted_two = _adapted_model(worksheet_number=2, worksheet_count=2, title="Word Builder")

    (artifact_dir / "source_model.json").write_text(source.model_dump_json(indent=2))
    (artifact_dir / "skill_model.json").write_text(skill.model_dump_json(indent=2))
    (artifact_dir / "adapted_model_1.json").write_text(adapted_one.model_dump_json(indent=2))
    (artifact_dir / "adapted_model_2.json").write_text(adapted_two.model_dump_json(indent=2))
    (artifact_dir / "validation_1.json").write_text(_validation_json(True))
    (artifact_dir / "validation_2.json").write_text(_validation_json(False))
    (artifact_dir / "preprocessed.png").write_bytes(b"png")
    (run_dir / "worksheet_hash_1of2.pdf").write_bytes(b"%PDF-1.4\n")
    (run_dir / "worksheet_hash_2of2.pdf").write_bytes(b"%PDF-1.4\n")

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("rag.backfill.index_run", lambda **kwargs: calls.append(kwargs))

    count = backfill(
        artifacts_dir=str(artifacts_root),
        output_dir=str(artifacts_root),
        db_path=str(tmp_path / "vector_store"),
    )

    assert count == 1
    assert len(calls) == 1
    payload = calls[0]
    assert payload["worksheet_mode"] == "multi"
    assert payload["theme_id"] == "roblox_obby"
    assert payload["pdf_paths"] == [
        str(run_dir / "worksheet_hash_1of2.pdf"),
        str(run_dir / "worksheet_hash_2of2.pdf"),
    ]
    assert payload["validation_results"]["skill_parity_passed"] is False
    assert payload["validation_results"]["all_validators_passed"] is False
    assert len(payload["adapted_summaries"]) == 2
    assert payload["adapted_summaries"][0]["response_formats"] == "circle"


def _adapted_model(
    worksheet_number: int,
    worksheet_count: int,
    title: str,
) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="hash123",
        skill_model_hash="skillhash",
        learner_profile_hash="profilehash",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Find the right word",
                instructions=[Step(number=1, text="Circle the right answer.")],
                worked_example=Example(instruction="Try this", content="grade"),
                items=[
                    ActivityItem(
                        item_id=1,
                        content="grade",
                        response_format="circle",
                        options=["grade", "gride", "cat"],
                        answer="grade",
                    ),
                    ActivityItem(
                        item_id=2,
                        content="trace grade",
                        response_format="trace",
                    ),
                ],
                response_format="circle",
                time_estimate="About 3 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="roblox_obby",
        decoration_zones=[],
        self_assessment=["I can read CVCe words."],
        worksheet_number=worksheet_number,
        worksheet_count=worksheet_count,
        worksheet_title=title,
    )


def _validation_json(passed: bool) -> str:
    payload = {
        "skill_parity": {"passed": passed, "violations": []},
        "age_band": {"passed": True, "violations": []},
        "adhd_compliance": {"passed": True, "violations": []},
        "print_quality": {"passed": True, "violations": []},
    }
    return json.dumps(payload)
