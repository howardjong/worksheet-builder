"""Tests for adapt/llm_planner.py — single-call planner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapt.llm_judge import JudgeVerdict
from adapt.llm_planner import _build_planner_prompt, _corpus_block
from adapt.rules import build_rules
from companion.schema import Accommodations, LearnerProfile
from corpus.ufli.lookup import CorpusLookupResult
from skill.schema import LiteracySkillModel, SourceItem

LONG_SENTENCE = (
    "The little dog likes to ride home in the big red wagon while the cat "
    "naps on the warm stone step beside the gate and dreams of cake."
)


def _skill(lesson_number: int | None = None) -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake", "ride", "home"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="1. tune -> tone -> cone -> cane",
                source_region_index=0,
            ),
            SourceItem(
                item_type="sentence",
                content=LONG_SENTENCE,
                source_region_index=1,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
        lesson_number=lesson_number,
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Ian", grade_level="1", accommodations=Accommodations())


def test_prompt_carries_full_source_items_untruncated() -> None:
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    assert "1. tune -> tone -> cone -> cane" in prompt
    assert LONG_SENTENCE in prompt  # no summarization, no truncation


def test_prompt_states_section_cap_and_item_authoring() -> None:
    rules = build_rules(_profile())
    prompt = _build_planner_prompt(_skill(), _profile(), rules, "default", None)

    assert f"Maximum {rules.max_sections_per_worksheet} sections" in prompt
    assert '"items"' in prompt  # output schema asks for authored items
    assert '"answer"' in prompt


def test_corpus_block_injects_lesson_ground_truth(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_lookup(lesson_number: int) -> CorpusLookupResult:
        assert lesson_number == 84
        return CorpusLookupResult(
            lesson_id="84",
            concept="CVCe a_e",
            decodable_text="A Cake for Tess. Tess had a cake.",
            additional_text="cake lake make take",
            home_practice_text="Read each word: cake, lake, make.",
        )

    monkeypatch.setattr("adapt.llm_planner.lookup_lesson", _fake_lookup)

    block = _corpus_block(_skill(lesson_number=84))

    assert "CVCe a_e" in block
    assert "Read each word: cake, lake, make." in block
    assert "cake lake make take" in block


def test_corpus_block_empty_without_lesson_number() -> None:
    assert _corpus_block(_skill(lesson_number=None)) == ""


def test_planner_chain_prefers_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("WORKSHEET_PLANNER_PROVIDERS", raising=False)
    calls: list[str] = []

    def _fake_openai(prompt: str, max_completion_tokens: int = 1024) -> str:
        calls.append(f"openai:{max_completion_tokens}")
        return "{}"

    monkeypatch.setattr(llm_planner, "_call_openai", _fake_openai)

    text, model = llm_planner._call_planner("prompt")

    assert text == "{}"
    assert model == "gpt-5.4"
    assert calls == ["openai:8192"]


def test_planner_chain_falls_back_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("WORKSHEET_PLANNER_PROVIDERS", raising=False)
    monkeypatch.delenv("WORKSHEET_PLANNER_GEMINI_MODEL", raising=False)
    seen: list[str] = []

    def _fake_gemini(prompt: str, model: str = "gemini-3-flash-preview") -> str:
        seen.append(model)
        return "{}"

    monkeypatch.setattr(llm_planner, "_call_gemini", _fake_gemini)

    text, model = llm_planner._call_planner("prompt")

    assert text == "{}"
    assert model == "gemini-3.5-flash"
    assert seen == ["gemini-3.5-flash"]


def test_planner_chain_respects_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("WORKSHEET_PLANNER_PROVIDERS", "gemini,openai")

    monkeypatch.setattr(llm_planner, "_call_gemini", lambda p, model="": "from-gemini")

    text, model = llm_planner._call_planner("prompt")

    assert text == "from-gemini"
    assert model == "gemini-3.5-flash"


def test_planner_chain_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    text, model = llm_planner._call_planner("prompt")

    assert text is None
    assert model == "none"


_PLAN_JSON = json.dumps(
    {
        "concept_focus": "CVCe magic-e",
        "pedagogical_rationale": "Practice the pattern",
        "worksheets": [
            {
                "title": "Magic E",
                "activities": [
                    {
                        "activity_type": "write",
                        "micro_goal": "Write CVCe words",
                        "words": [],
                        "items": [
                            {"content": "cake", "response_format": "write"},
                            {"content": "ride", "response_format": "write"},
                        ],
                        "instructions": ["Write each word."],
                        "worked_example": "cake -> the e is silent",
                        "response_format": "write",
                        "time_estimate_minutes": 2,
                        "rationale": "Practice writing the pattern",
                    }
                ],
            }
        ],
    }
)


def _verdict(approved: bool, score: float) -> JudgeVerdict:
    return JudgeVerdict(
        approved=approved,
        overall_score=score,
        concept_alignment=score,
        content_coverage=score,
        lesson_flow=score,
        adhd_compliance=score,
        feedback=["ok" if approved else "missing chains"],
        rationale="r",
    )


def _planner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("WORKSHEET_PLANNER_PROVIDERS", raising=False)


def test_planner_ships_approved_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: _verdict(True, 0.9))

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    assert [i.content for i in result[0].chunks[0].items] == ["cake", "ride"]
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["approved"] is True
    assert verdict["planner_version"] == 2
    assert verdict["outcome"] == "planned_approved"
    log_lines = (tmp_path / "llm_adaptation_log.jsonl").read_text().splitlines()
    assert json.loads(log_lines[-1])["outcome"] == "planned_approved"


def test_planner_regenerates_once_with_feedback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    prompts: list[str] = []

    def _fake_call(prompt: str) -> tuple[str, str]:
        prompts.append(prompt)
        return _PLAN_JSON, "gpt-5.4"

    verdicts = iter([_verdict(False, 0.4), _verdict(True, 0.85)])
    monkeypatch.setattr(llm_planner, "_call_planner", _fake_call)
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: next(verdicts))

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    assert len(prompts) == 2
    assert "missing chains" in prompts[1]  # feedback fed back
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["outcome"] == "planned_regen_approved"


def test_planner_falls_back_after_two_rejections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: _verdict(False, 0.4))

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is None
    # No judge_verdict.json: transform must judge what actually ships
    assert not (tmp_path / "judge_verdict.json").exists()
    attempts = json.loads((tmp_path / "planner_attempts.json").read_text())
    assert attempts["outcome"] == "planned_rejected_fallback"
    assert len(attempts["verdicts"]) == 2


def test_planner_ships_unjudged_when_judge_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: None)

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["unjudged"] is True
    assert verdict["outcome"] == "planned_unjudged"


def test_planner_returns_none_without_env_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)

    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is None


def test_planner_returns_none_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is None


def test_planner_never_writes_global_log_under_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: _verdict(True, 0.9))

    llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path / "artifacts"))

    # PYTEST_CURRENT_TEST is set by pytest itself; the global log must not appear
    assert not (tmp_path / "logs").exists()


def test_prompt_demands_individual_coverage_not_bundling() -> None:
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    # Each source word/chain-step/sentence must be practiced as its own item,
    # not crammed into one dense list item (the coverage limiter the judge flags).
    assert "INDIVIDUAL practice" in prompt
    assert "Do NOT bundle" in prompt
    assert "one item per word" in prompt
    # Word chains must be student activities, not just worked examples.
    assert "not only as a worked example" in prompt
