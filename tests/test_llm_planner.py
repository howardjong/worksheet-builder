"""Tests for adapt/llm_planner.py — single-call planner."""

from __future__ import annotations

import pytest

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
