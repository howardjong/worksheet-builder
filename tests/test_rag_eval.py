"""Tests for the RAG evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from extract.schema import PIPELINE_VERSION, SourceRegion, SourceWorksheetModel
from rag.eval import evaluate
from rag.retrieval import RAGContext, RetrievalResult
from skill.schema import LiteracySkillModel, SourceItem


def test_evaluate_builds_report_with_aggregate_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_dir = tmp_path / "inputs"
    test_dir.mkdir()
    (test_dir / "one.jpg").write_bytes(b"img")
    (test_dir / "two.jpg").write_bytes(b"img")

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

    monkeypatch.setattr(
        "rag.eval._freeze_source_and_skill",
        lambda input_path, freeze_dir: {
            "input_path": str(input_path),
            "preprocessed_path": str(freeze_dir / "preprocessed.png"),
            "source_image_hash": "hash123",
            "source_model": source,
            "skill_model": skill,
        },
    )
    monkeypatch.setattr("rag.eval.load_profile", lambda _path: SimpleNamespace(name="Ian"))
    monkeypatch.setattr("rag.eval.load_theme", lambda _theme: SimpleNamespace(multi_worksheet=True))
    monkeypatch.setattr(
        "rag.eval.retrieve_context",
        lambda **kwargs: RAGContext(
            curated_exemplars=[
                RetrievalResult(
                    doc_id="ex1",
                    score=0.9,
                    metadata={"domain": "phonics", "distractor_words": "cat,dog"},
                    document="",
                ),
                RetrievalResult(
                    doc_id="ex2",
                    score=0.8,
                    metadata={"domain": "phonics"},
                    document="",
                ),
            ],
            prior_adaptations=[
                RetrievalResult(
                    doc_id="ad1",
                    score=0.7,
                    metadata={"domain": "fluency"},
                    document="",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "rag.eval._run_variant_from_frozen",
        lambda variant, case_dir, **kwargs: _variant_result(variant, case_dir),
    )

    report = evaluate(
        test_dir=str(test_dir),
        profile_path="profiles/ian.yaml",
        output_root=str(tmp_path / "eval"),
    )

    assert report.case_count == 2
    assert report.retrieval_at_3_mean == 2 / 3
    assert report.unique_rag_format_sets == 1
    assert report.format_changed_rate == 1.0
    assert report.distractor_novelty_mean == 0.5
    assert report.baseline_validator_pass_rate == 1.0
    assert report.rag_validator_pass_rate == 1.0
    assert report.cases[0].rag_selected_source == "curated_exemplars"
    assert (tmp_path / "eval").exists()


def _variant_result(variant: str, case_dir: Path) -> dict[str, object]:
    variant_root = case_dir / variant
    output_dir = variant_root / "output"
    artifacts_dir = variant_root / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    distractors = ["cat", "dog"] if variant == "A_no_rag" else ["cat", "sun"]
    adapted_path = artifacts_dir / "adapted_model_1.json"
    payload: dict[str, Any] = {
        "source_hash": "hash123",
        "skill_model_hash": "skillhash",
        "learner_profile_hash": "profilehash",
        "grade_level": "1",
        "domain": "phonics",
        "specific_skill": "cvce_pattern",
        "chunks": [
            {
                "chunk_id": 1,
                "micro_goal": "Find the right word",
                "instructions": [{"number": 1, "text": "Circle the right answer."}],
                "worked_example": {"instruction": "Try this", "content": "grade"},
                "items": [
                    {
                        "item_id": 1,
                        "content": "grade",
                        "response_format": "circle",
                        "options": ["grade", distractors[0], distractors[1]],
                        "answer": "grade",
                        "metadata": {},
                    }
                ],
                "response_format": "circle",
                "time_estimate": "About 3 minutes",
                "reward_event": None,
            }
        ],
        "scaffolding": {
            "show_worked_example": True,
            "fade_after_chunk": 1,
            "hint_level": "full",
        },
        "theme_id": "roblox_obby",
        "decoration_zones": [],
        "avatar_prompts": None,
        "self_assessment": ["I can read CVCe words."],
        "worksheet_number": 1,
        "worksheet_count": 1,
        "worksheet_title": "Word Discovery",
        "break_prompt": None,
    }
    adapted_path.write_text(json.dumps(payload))

    return {
        "variant": variant,
        "output_dir": str(output_dir),
        "validation": {"all_validators_passed": True},
        "all_validators_passed": True,
        "response_formats": ["circle"] if variant == "A_no_rag" else ["circle", "trace"],
        "response_format_count": 1 if variant == "A_no_rag" else 2,
        "rag_debug": {"selected_source": "curated_exemplars", "selected_count": 2},
    }
