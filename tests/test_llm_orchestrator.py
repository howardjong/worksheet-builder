"""Tests for adapt/llm_orchestrator.py — LLM adaptation retry loop with GPT takeover."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from adapt.llm_judge import JudgeVerdict
from adapt.llm_orchestrator import (
    AdaptationLogEntry,
    _build_retry_prompt_suffix,
    orchestrate_llm_adaptation,
)
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem

# --- Fixtures ---

_PATCH_GEMINI = "adapt.llm_orchestrator._call_gemini"
_PATCH_JUDGE = "adapt.llm_orchestrator.judge_adaptation"
_PATCH_GPT = "adapt.llm_orchestrator._call_openai"


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="consonant_le",
        learning_objectives=["Read words with -le pattern"],
        target_words=["table", "simple", "puzzle"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="table, simple, puzzle",
                source_region_index=1,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="test_child",
        grade_level="1",
        accommodations=Accommodations(),
    )


# Canned Gemini JSON response
_GEMINI_PLAN_JSON = json.dumps({
    "concept_focus": "consonant-le syllable pattern",
    "pedagogical_rationale": "Focus on -le words",
    "worksheets": [{
        "title": "Word Work",
        "activities": [{
            "activity_type": "write",
            "micro_goal": "Write 3 -le words",
            "words": ["table", "simple", "puzzle"],
            "instructions": ["Write each word on the line."],
            "worked_example": '"table" -- I can read this word!',
            "response_format": "write",
            "time_estimate_minutes": 2,
            "rationale": "Practice writing -le words",
        }],
    }],
})


def _approved_verdict() -> JudgeVerdict:
    return JudgeVerdict(
        approved=True,
        overall_score=0.85,
        concept_alignment=0.9,
        content_coverage=0.8,
        lesson_flow=0.85,
        adhd_compliance=0.85,
        feedback=["Good coverage of -le words"],
        rationale="Well-structured worksheet",
    )


def _rejected_verdict() -> JudgeVerdict:
    return JudgeVerdict(
        approved=False,
        overall_score=0.35,
        concept_alignment=0.5,
        content_coverage=0.2,
        lesson_flow=0.4,
        adhd_compliance=0.3,
        feedback=["Missing word chains", "Dropped target words"],
        rationale="Incomplete coverage of source content",
    )


# --- Tests ---


class TestEnvVarGate:
    def test_returns_none_without_env_var(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
        result = orchestrate_llm_adaptation(_skill(), _profile())
        assert result is None

    def test_returns_none_without_api_keys(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = orchestrate_llm_adaptation(_skill(), _profile())
        assert result is None


class TestGeminiApprovedFirstTry:
    def test_returns_worksheets_on_approval(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with (
            patch(_PATCH_GEMINI, return_value=_GEMINI_PLAN_JSON),
            patch(_PATCH_JUDGE, return_value=_approved_verdict()),
        ):
            result = orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        assert result is not None
        assert len(result) >= 1

        log_path = tmp_path / "llm_adaptation_log.jsonl"
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["outcome"] == "gemini_first_try"
        assert entry["gemini_attempts"] == 1
        assert entry["planning_model"] == "gemini-3-flash-preview"


class TestGeminiRetryApproved:
    def test_retry_succeeds_after_first_rejection(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        verdicts = iter([_rejected_verdict(), _approved_verdict()])

        with (
            patch(_PATCH_GEMINI, return_value=_GEMINI_PLAN_JSON),
            patch(_PATCH_JUDGE, side_effect=lambda *a, **kw: next(verdicts)),
        ):
            result = orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        assert result is not None

        log_path = tmp_path / "llm_adaptation_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["outcome"] == "gemini_retry"
        assert entry["gemini_attempts"] == 2


class TestGPTTakeover:
    def test_gpt_takes_over_after_two_rejections(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        verdicts = iter([_rejected_verdict(), _rejected_verdict()])

        with (
            patch(_PATCH_GEMINI, return_value=_GEMINI_PLAN_JSON),
            patch(_PATCH_JUDGE, side_effect=lambda *a, **kw: next(verdicts)),
            patch(_PATCH_GPT, return_value=_GEMINI_PLAN_JSON),
        ):
            result = orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        assert result is not None

        log_path = tmp_path / "llm_adaptation_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["outcome"] == "gpt_takeover"
        assert entry["planning_model"] == "gpt-5.4"
        assert entry["gemini_attempts"] == 2


class TestGeminiOnlyNoJudge:
    def test_accepts_gemini_without_judge(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with patch(_PATCH_GEMINI, return_value=_GEMINI_PLAN_JSON):
            result = orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        assert result is not None

        log_path = tmp_path / "llm_adaptation_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["outcome"] == "gemini_first_try"


class TestGPTOnlyNoGemini:
    def test_gpt_plans_directly_without_gemini(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with patch(_PATCH_GPT, return_value=_GEMINI_PLAN_JSON):
            result = orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        assert result is not None

        log_path = tmp_path / "llm_adaptation_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["outcome"] == "gpt_takeover"
        assert entry["gemini_attempts"] == 0


class TestRetryPromptFeedback:
    def test_feedback_included_in_retry_suffix(self) -> None:
        verdict = _rejected_verdict()
        suffix = _build_retry_prompt_suffix(verdict)
        assert "Missing word chains" in suffix
        assert "Dropped target words" in suffix
        assert "0.20" in suffix  # content_coverage
        assert "Incomplete coverage" in suffix
        assert "REJECTED" in suffix


class TestJudgeVerdictWritten:
    def test_verdict_json_written_to_artifacts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with (
            patch(_PATCH_GEMINI, return_value=_GEMINI_PLAN_JSON),
            patch(_PATCH_JUDGE, return_value=_approved_verdict()),
        ):
            orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        verdict_path = tmp_path / "judge_verdict.json"
        assert verdict_path.exists()
        verdict = json.loads(verdict_path.read_text())
        assert verdict["approved"] is True
        assert verdict["overall_score"] == 0.85


class TestLogEntryModel:
    def test_log_entry_serializes(self) -> None:
        entry = AdaptationLogEntry(
            timestamp="2026-03-24T00:00:00Z",
            skill_domain="phonics",
            specific_skill="consonant_le",
            template_type="ufli_word_work",
            outcome="gemini_first_try",
            gemini_attempts=1,
            judge_verdicts=[],
            final_score=0.85,
            planning_model="gemini-3-flash-preview",
        )
        data = json.loads(entry.model_dump_json())
        assert data["outcome"] == "gemini_first_try"
        assert data["final_score"] == 0.85


class TestGeminiParseFailure:
    def test_parse_failure_triggers_gpt_takeover(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with (
            patch(_PATCH_GEMINI, return_value="not valid json at all"),
            patch(_PATCH_GPT, return_value=_GEMINI_PLAN_JSON),
        ):
            result = orchestrate_llm_adaptation(
                _skill(), _profile(), artifacts_dir=str(tmp_path),
            )

        assert result is not None

        log_path = tmp_path / "llm_adaptation_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["outcome"] == "gpt_takeover"
