"""Tests for skill/lesson_loader.py — build a skill model from a UFLI lesson number."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import corpus.ufli.lookup as lookup_module
from corpus.ufli.lookup import reset_lookup_cache
from skill.lesson_loader import LessonNotFoundError, skill_model_from_lesson


@pytest.fixture(autouse=True)
def _force_fixture_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force the committed fixture (real corpus absent) for deterministic tests.

    On machines where data/ufli/normalized.jsonl exists it would otherwise win.
    """
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", tmp_path / "no_corpus")
    reset_lookup_cache()
    yield
    reset_lookup_cache()


def test_lesson_74_builds_from_fixture() -> None:
    model = skill_model_from_lesson(74)

    assert model.lesson_number == 74
    assert model.grade_level == "2"  # lessons 71-100
    assert model.domain == "phonics"
    assert model.specific_skill == "vowel_teams"  # fixture concept "ay"
    assert model.template_type == "ufli_word_work"
    assert model.extraction_confidence == 1.0
    assert "play" in model.target_words
    assert "gray" in model.target_words
    # No copyrighted "Roll and Read" header leaked into the words.
    assert "roll" not in model.target_words
    assert "read" not in model.target_words


def test_lesson_source_items_mirror_enrich_from_corpus() -> None:
    model = skill_model_from_lesson(74)
    item_types = {si.item_type for si in model.source_items}
    assert {"word_list", "roll_and_read", "passage", "sentence"} <= item_types

    passages = [si for si in model.source_items if si.item_type == "passage"]
    assert len(passages) == 1
    assert "play" in passages[0].content.lower()

    roll = [si for si in model.source_items if si.item_type == "roll_and_read"]
    assert roll and "day" in roll[0].content.lower()


def test_all_fixture_lessons_build() -> None:
    expected = {31: "digraphs", 49: "cvce", 74: "vowel_teams", 90: "vowel_teams"}
    for lesson, skill in expected.items():
        model = skill_model_from_lesson(lesson)
        assert model.specific_skill == skill
        assert model.target_words
        assert model.learning_objectives


def test_missing_lesson_raises() -> None:
    with pytest.raises(LessonNotFoundError):
        skill_model_from_lesson(9999)


class TestHomePracticeCleaning:
    """The real corpus's home_practice_text is a raw PDF dump — headers, chain
    scripts, arrow chains, word lists, and real sentences concatenated. Only
    chains and clean student sentences may reach the pipeline (observed live:
    the raw dump shipped teacher-script fragments as student items)."""

    # Mirrors the fragments the pedagogical judge quoted from the live
    # lesson-74 run (real corpus, gitignored — reconstructed from the trace).
    RAW = (
        "New Concept and Sample Words Sample Word Work Chain Script y as long e "
        "sunny → funny → bunny → buddy Change the nn to dd. What word is this? "
        "[reading] ________ muddy penny puppy lady tiny New Irregular Words "
        "Sentences forty I will bring a teddy for the baby. The puppy is muddy. "
        "________ → happy → hoppy → poppy → puppy"
    )

    def test_chains_extracted_in_chain_form(self) -> None:
        from skill.lesson_loader import _home_practice_items

        chains, _ = _home_practice_items(self.RAW)
        assert "sunny → funny → bunny → buddy" in chains
        assert "happy → hoppy → poppy → puppy" in chains
        # Blank placeholders never become chain steps.
        assert not any("_" in chain for chain in chains)

    def test_sentences_keep_student_text_only(self) -> None:
        from skill.lesson_loader import _home_practice_items

        _, sentences = _home_practice_items(self.RAW)
        assert "I will bring a teddy for the baby." in sentences
        assert "The puppy is muddy." in sentences
        joined = " ".join(sentences)
        # Headers, scripts, blanks, and word lists never ship to a child.
        assert "New Concept" not in joined
        assert "Chain Script" not in joined
        assert "Change the" not in joined
        assert "What word" not in joined
        assert "[reading]" not in joined
        assert "_" not in joined
        assert "Irregular" not in joined

    def test_clean_fixture_text_passes_through(self) -> None:
        from skill.lesson_loader import _home_practice_items

        chains, sentences = _home_practice_items(
            "We play all day. May will stay in the hay. Ray has gray clay. It is a fun day."
        )
        assert chains == []
        assert sentences == [
            "We play all day.",
            "May will stay in the hay.",
            "Ray has gray clay.",
            "It is a fun day.",
        ]

    def test_source_items_include_extracted_chains(self) -> None:
        from skill.lesson_loader import _home_practice_items  # noqa: F401

        # Fixture lesson 74 home practice is clean sentences with no chains —
        # the sentence item must survive the cleaning intact.
        model = skill_model_from_lesson(74)
        sentence_items = [si for si in model.source_items if si.item_type == "sentence"]
        assert len(sentence_items) == 1
        assert "We play all day." in sentence_items[0].content
