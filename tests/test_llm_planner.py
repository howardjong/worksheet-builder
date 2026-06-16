"""Tests for adapt/llm_planner.py — single-call planner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapt.llm_judge import JudgeVerdict
from adapt.llm_planner import (
    _build_planner_prompt,
    _corpus_block,
    _objective_authoring_block,
)
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


def test_prompt_requires_correct_worked_example() -> None:
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    lowered = prompt.lower()
    assert "real word" in lowered  # worked example must produce a real word
    # never model a wrong attempt / self-refuting "No"
    assert "wrong" in lowered or "incorrect" in lowered


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
    monkeypatch.setattr(
        llm_planner, "judge_adaptation_samples", lambda s, w, n: _verdict(True, 0.9)
    )

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
    monkeypatch.setattr(llm_planner, "judge_adaptation_samples", lambda s, w, n: next(verdicts))

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
    monkeypatch.setattr(
        llm_planner, "judge_adaptation_samples", lambda s, w, n: _verdict(False, 0.4)
    )

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
    monkeypatch.setattr(llm_planner, "judge_adaptation_samples", lambda s, w, n: None)

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
    monkeypatch.setattr(
        llm_planner, "judge_adaptation_samples", lambda s, w, n: _verdict(True, 0.9)
    )

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


def test_prompt_omits_coverage_contract_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSHEET_PLANNER_SLOT_CONTRACT", raising=False)
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    assert "Coverage contract" not in prompt
    assert "covered_source_item_ids" not in prompt


def test_prompt_carries_coverage_ledger_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_PLANNER_SLOT_CONTRACT", "1")
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    assert "Coverage contract" in prompt
    # required ledger ids are listed
    assert "word_001" in prompt
    assert "chain_001_step_1" in prompt
    assert "sentence_001" in prompt
    # exact text appears next to its id so the model can author it verbatim
    assert "tone" in prompt
    # the output schema asks each item to declare the ids it covers
    assert "covered_source_item_ids" in prompt


def test_contract_repairs_dropped_source_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setenv("WORKSHEET_PLANNER_SLOT_CONTRACT", "1")
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation_samples", lambda s, w, n: _verdict(True, 0.9)
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    contents = [i.content for ws in result for chunk in ws.chunks for i in chunk.items]
    # _PLAN_JSON drops "home" (and the chain + sentence); the contract repairs them in.
    assert "home" in contents


def test_contract_off_leaves_dropped_source_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.delenv("WORKSHEET_PLANNER_SLOT_CONTRACT", raising=False)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation_samples", lambda s, w, n: _verdict(True, 0.9)
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    contents = [i.content for ws in result for chunk in ws.chunks for i in chunk.items]
    assert "home" not in contents
    assert contents == ["cake", "ride"]


# --- T8.5: objective-authoring block (author IN the required forms) -----------

_OBJ_HEADER = "## Objective coverage (author each objective IN its required form)"


def test_objective_block_empty_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKSHEET_OBJECTIVE_COVERAGE", raising=False)
    assert _objective_authoring_block(_skill()) == ""


def test_objective_block_nonempty_with_header_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")
    block = _objective_authoring_block(_skill())
    assert block != ""
    assert _OBJ_HEADER in block


def test_prompt_omits_objective_authoring_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSHEET_OBJECTIVE_COVERAGE", raising=False)
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    assert _OBJ_HEADER not in prompt
    assert "ordered build/transformation" not in prompt
    assert "do not include every" not in prompt


def test_prompt_authors_chain_in_required_form_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    assert _OBJ_HEADER in prompt
    # An objective_id from the built ledger appears so the model can target the cell.
    assert "obj_manipulation" in prompt

    # 1. Author the chain IN its form: an ordered build/transformation, with the
    #    chain's own words present in the step guidance (not scattered write items).
    lowered = prompt.lower()
    assert "transformation" in lowered
    assert "ordered" in lowered
    assert "change" in lowered
    assert "tone" in prompt  # chain step word surfaced in the chain-form guidance

    # 2. Sample samplable pools to threshold, not exhaustively.
    assert "sample" in lowered
    assert "do not include every" in lowered

    # 3. Do NOT dilute target-pattern cells with contrast/review/irregular words.
    assert "contrast" in lowered
    assert "must not pad" in lowered


# --- T9: objective-sufficiency coverage path in plan_lesson_llm (flagged) ------

from adapt.llm_judge import (  # noqa: E402
    ObjectiveJudgeCellScore,
    ObjectiveJudgeVerdict,
    SevereDefect,
)
from adapt.objective_ledger import ObjectiveCell, ObjectiveLedger  # noqa: E402
from validate.blocking_gates import BlockingGateResult, BlockingViolation  # noqa: E402
from validate.objective_coverage import (  # noqa: E402
    ObjectiveCoverageResult,
    PackageBoundResult,
)


def _tiny_ledger() -> ObjectiveLedger:
    """A controlled ledger with a single essential decode cell (obj_decode)."""
    return ObjectiveLedger(
        source_skill_hash="h",
        lesson_number=84,
        corpus_status="matched",
        corpus_version="v",
        primary_pattern="a_e",
        objectives=[
            ObjectiveCell(
                objective_id="obj_decode",
                objective_type="decode_target_pattern",
                display_name="Decode a_e words",
                concept="cvce",
                target_pattern="a_e",
                importance="essential",
                required_forms=[],
                target_words=["cake", "ride"],
                min_practice_count=4,
                max_recommended_count=12,
                sufficiency_rule="rule",
            )
        ],
        source_items=[],
    )


def _gates(passed: bool) -> BlockingGateResult:
    violations = (
        []
        if passed
        else [
            BlockingViolation(
                gate="answer_key",
                severity="blocker",
                item_id="ws0_chunk0_item0",
                message="answer not in options",
            )
        ]
    )
    return BlockingGateResult(passed=passed, violations=violations)


def _coverage(status: str) -> ObjectiveCoverageResult:
    return ObjectiveCoverageResult(
        status=status,  # type: ignore[arg-type]
        passed=(status == "pass"),
        objective_results=[],
        package_bounds=PackageBoundResult(
            passed=True,
            total_estimated_minutes=4,
            total_item_count=2,
            dense_text_block_count=0,
            max_objectives_in_a_worksheet=1,
        ),
    )


def _obj_verdict(
    cell_quality: float, defects: list[SevereDefect] | None = None
) -> ObjectiveJudgeVerdict:
    """A judge sample scoring obj_decode at the given quality (overall/adhd healthy)."""
    return ObjectiveJudgeVerdict(
        objective_scores=[
            ObjectiveJudgeCellScore(
                objective_id="obj_decode",
                quality=cell_quality,
                severe_defects=defects or [],
                rationale="r",
            )
        ],
        objective_sufficiency=0.8,
        skill_form_fidelity=0.8,
        structured_literacy_alignment=0.8,
        adhd_cognitive_load_fit=0.8,
        lesson_flow_and_usability=0.8,
        overall_score=0.8,
        approval_recommendation="approve",
        feedback=["ok"],
    )


def _objective_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _planner_env(monkeypatch)
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")
    monkeypatch.delenv("WORKSHEET_PLANNER_SLOT_CONTRACT", raising=False)


def test_objective_gate_block_rejects_and_skips_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _objective_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "build_objective_ledger", lambda s: _tiny_ledger())
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "run_blocking_gates", lambda w, ld: _gates(False))

    judged: list[bool] = []

    def _no_judge(*args: object, **kwargs: object) -> list[ObjectiveJudgeVerdict]:
        judged.append(True)
        raise AssertionError("judge must not be called after a gate block")

    monkeypatch.setattr(llm_planner, "judge_objective_adaptation_samples", _no_judge)

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is None
    assert judged == []
    attempts = json.loads((tmp_path / "planner_attempts.json").read_text())
    assert "gate" in attempts["outcome"]
    assert not (tmp_path / "judge_verdict.json").exists()


def test_objective_clean_plan_approved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from adapt import llm_planner

    _objective_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "build_objective_ledger", lambda s: _tiny_ledger())
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "run_blocking_gates", lambda w, ld: _gates(True))
    monkeypatch.setattr(
        llm_planner, "evaluate_objective_coverage", lambda ld, e, w: _coverage("pass")
    )
    monkeypatch.setattr(
        llm_planner,
        "judge_objective_adaptation_samples",
        lambda ld, g, c, w, e, n: [_obj_verdict(0.8)],
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    assert [i.content for i in result[0].chunks[0].items] == ["cake", "ride"]
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["outcome"] == "objective_approved"
    log_lines = (tmp_path / "llm_adaptation_log.jsonl").read_text().splitlines()
    assert json.loads(log_lines[-1])["outcome"] == "objective_approved"


def test_objective_abstains_to_fallback_when_judge_unavailable_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEFAULT (no opt-in flag): empty judge samples → abstain to deterministic fallback.

    The judge being unavailable must NOT ship LLM-authored material unjudged by
    default. Gates + coverage passing is not a substitute for the Phase-2 quality
    review, so the path abstains (return None) and the deterministic engine takes
    over — transform.py then judges what actually ships.
    """
    from adapt import llm_planner

    _objective_env(monkeypatch)
    monkeypatch.delenv("WORKSHEET_ALLOW_UNJUDGED_OBJECTIVE_PLAN", raising=False)
    monkeypatch.setattr(llm_planner, "build_objective_ledger", lambda s: _tiny_ledger())
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "run_blocking_gates", lambda w, ld: _gates(True))
    monkeypatch.setattr(
        llm_planner, "evaluate_objective_coverage", lambda ld, e, w: _coverage("pass")
    )
    # Judge unavailable: empty per-sample list. By default this now ABSTAINS.
    monkeypatch.setattr(
        llm_planner,
        "judge_objective_adaptation_samples",
        lambda ld, g, c, w, e, n: [],
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is None  # routed to deterministic fallback, not shipped unjudged
    # No judge_verdict.json: nothing shipped, transform must judge what does ship.
    assert not (tmp_path / "judge_verdict.json").exists()
    attempts = json.loads((tmp_path / "planner_attempts.json").read_text())
    assert attempts["outcome"] == "objective_abstain_judge_unavailable"
    log_lines = (tmp_path / "llm_adaptation_log.jsonl").read_text().splitlines()
    last = json.loads(log_lines[-1])
    assert last["outcome"] == "objective_abstain_judge_unavailable"
    assert last["final_output_judged"] is False


def test_objective_ships_unjudged_when_judge_unavailable_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OPT-IN (WORKSHEET_ALLOW_UNJUDGED_OBJECTIVE_PLAN=1): ship unjudged when judge down.

    With the explicit opt-in flag, the old behavior is preserved: gates + coverage
    passed, the empty-samples guard (judge unavailable) ships the deterministically
    vetted plan with an unjudged verdict artifact.
    """
    from adapt import llm_planner

    _objective_env(monkeypatch)
    monkeypatch.setenv("WORKSHEET_ALLOW_UNJUDGED_OBJECTIVE_PLAN", "1")
    monkeypatch.setattr(llm_planner, "build_objective_ledger", lambda s: _tiny_ledger())
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "run_blocking_gates", lambda w, ld: _gates(True))
    monkeypatch.setattr(
        llm_planner, "evaluate_objective_coverage", lambda ld, e, w: _coverage("pass")
    )
    # Judge unavailable: empty per-sample list. Opt-in flag keeps the ship-unjudged path.
    monkeypatch.setattr(
        llm_planner,
        "judge_objective_adaptation_samples",
        lambda ld, g, c, w, e, n: [],
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None  # worksheets shipped despite no verdict
    assert [i.content for i in result[0].chunks[0].items] == ["cake", "ride"]
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["outcome"] == "objective_planned_unjudged"
    assert verdict["unjudged"] is True
    assert verdict["approved"] is None  # no approve verdict was claimed
    assert verdict["pedagogical_judge_ran"] is False
    assert verdict["planner_version"] == 2
    log_lines = (tmp_path / "llm_adaptation_log.jsonl").read_text().splitlines()
    last = json.loads(log_lines[-1])
    assert last["outcome"] == "objective_planned_unjudged"
    assert last["final_output_judged"] is False  # ship-path is unjudged


def test_objective_low_quality_cell_abstains_to_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _objective_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "build_objective_ledger", lambda s: _tiny_ledger())
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "run_blocking_gates", lambda w, ld: _gates(True))
    monkeypatch.setattr(
        llm_planner, "evaluate_objective_coverage", lambda ld, e, w: _coverage("pass")
    )
    # Essential cell quality 0.58 (in [0.50, 0.65)), no severe defect → ABSTAIN.
    monkeypatch.setattr(
        llm_planner,
        "judge_objective_adaptation_samples",
        lambda ld, g, c, w, e, n: [_obj_verdict(0.58)],
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is None  # routed to fallback
    assert not (tmp_path / "judge_verdict.json").exists()
    attempts = json.loads((tmp_path / "planner_attempts.json").read_text())
    assert "abstain" in attempts["outcome"]  # distinct from a clean reject
    assert "reject" not in attempts["outcome"]
    log_lines = (tmp_path / "llm_adaptation_log.jsonl").read_text().splitlines()
    assert "abstain" in json.loads(log_lines[-1])["outcome"]


def test_objective_path_not_taken_when_flag_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.delenv("WORKSHEET_OBJECTIVE_COVERAGE", raising=False)

    def _no_obj_judge(*args: object, **kwargs: object) -> list[ObjectiveJudgeVerdict]:
        raise AssertionError("objective judge must not run when the flag is off")

    monkeypatch.setattr(llm_planner, "judge_objective_adaptation_samples", _no_obj_judge)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation_samples", lambda s, w, n: _verdict(True, 0.9)
    )

    result = llm_planner.plan_lesson_llm(_skill(), _profile(), artifacts_dir=str(tmp_path))

    assert result is not None
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["outcome"] == "planned_approved"  # old path unchanged


def test_objective_and_slot_contract_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")
    monkeypatch.setenv("WORKSHEET_PLANNER_SLOT_CONTRACT", "1")

    with pytest.raises((RuntimeError, ValueError)):
        llm_planner.plan_lesson_llm(_skill(), _profile())
