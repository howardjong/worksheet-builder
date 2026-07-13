"""Tests for skill/lesson_loader.py — build a skill model from a UFLI lesson number."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import corpus.ufli.lookup as lookup_module
from corpus.ufli.lookup import reset_lookup_cache
from skill.lesson_loader import LessonNotFoundError, skill_model_from_lesson
from skill.schema import LiteracySkillModel


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

    def test_make_the_word_is_teacher_script_not_sentence(self) -> None:
        from skill.lesson_loader import _home_practice_items

        _, sentences = _home_practice_items(
            "Make the word slow. Are you older than your brother? Add the ending to tall."
        )
        assert sentences == ["Are you older than your brother?"]


class TestWordPoolHygiene:
    """The real corpus's Roll and Read blocks are raw PDF-grid extractions and
    can contain truncated fragments (observed live: lesson 74 shipped "la" —
    a fragment, not a word — into the cover title and match/write sections).
    The engine parser (adapt.engine._parse_roll_and_read) blocklists known
    fragments; the loader must mirror it AND drop tokens that don't conform
    to the lesson's target pattern."""

    # Mirrors the live lesson-74 defect: "la" (blocklisted fragment) leads the
    # Roll and Read block; "twen" (truncated "twenty") exercises the pattern
    # filter for fragments the static blocklist can't anticipate.
    RAW_Y_BLOCK = (
        "Roll and Read\nLesson 74: y /ē/\nla\nfluffy\nangry\njelly\nbumpy\n"
        "lady\nhappy\nmy\nsunny\ntwen"
    )

    def _model_for(
        self,
        monkeypatch: pytest.MonkeyPatch,
        concept: str,
        additional_text: str,
    ) -> LiteracySkillModel:
        import skill.lesson_loader as loader_module
        from corpus.ufli.lookup import CorpusLookupResult

        record = CorpusLookupResult(
            lesson_id="74",
            concept=concept,
            decodable_text="",
            additional_text=additional_text,
            home_practice_text="",
        )
        monkeypatch.setattr(loader_module, "lookup_lesson", lambda _n: record)
        return skill_model_from_lesson(74)

    def test_blocklisted_fragments_dropped_by_parser(self) -> None:
        # Parser parity with adapt.engine._parse_roll_and_read.
        from skill.lesson_loader import _roll_and_read_words

        words = _roll_and_read_words("Roll and Read\nla\nle\nre\nde\nel\nal\nfluffy")
        assert words == ["fluffy"]

    def test_concept_patterns_plain_grapheme(self) -> None:
        from skill.lesson_loader import _concept_patterns, _filter_pattern_words

        patterns = _concept_patterns("y /ē/")
        kept, dropped = _filter_pattern_words(["fluffy", "angry", "my", "lady", "twenty"], patterns)
        # 2-letter legit word "my" survives; nothing conforming is dropped.
        assert kept == ["fluffy", "angry", "my", "lady", "twenty"]
        assert dropped == []

    def test_concept_patterns_split_vowel(self) -> None:
        from skill.lesson_loader import _concept_patterns, _filter_pattern_words

        patterns = _concept_patterns("a_e")
        kept, dropped = _filter_pattern_words(["cake", "gate", "cat", "name"], patterns)
        assert kept == ["cake", "gate", "name"]
        assert dropped == ["cat"]

    def test_concept_patterns_multi_grapheme(self) -> None:
        from skill.lesson_loader import _concept_patterns, _filter_pattern_words

        patterns = _concept_patterns("oa, ow")
        kept, dropped = _filter_pattern_words(["boat", "coat", "snow", "grow", "cat"], patterns)
        assert kept == ["boat", "coat", "snow", "grow"]
        assert dropped == ["cat"]

    def test_underivable_concept_disables_filter(self) -> None:
        from skill.lesson_loader import _concept_patterns, _filter_pattern_words

        # Pure phoneme notation (non-ASCII) yields no graphemes — no filtering.
        assert _concept_patterns("/ē/") == []
        kept, dropped = _filter_pattern_words(["la", "fluffy"], [])
        assert kept == ["la", "fluffy"]
        assert dropped == []

    def test_safety_valve_keeps_all_when_drop_ratio_high(self) -> None:
        from skill.lesson_loader import _concept_patterns, _filter_pattern_words

        # A grid with a legit review column: half the words don't match the
        # target pattern. Dropping >25% means the pattern read is untrustworthy.
        patterns = _concept_patterns("ay")
        words = ["play", "day", "ship", "fish"]
        kept, dropped = _filter_pattern_words(words, patterns)
        assert kept == words
        assert dropped == []

    def test_fragment_dropped_from_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = self._model_for(monkeypatch, "y /ē/", self.RAW_Y_BLOCK)

        # "la" dies at the parser blocklist; "twen" dies at the pattern filter.
        assert "la" not in model.target_words
        assert "twen" not in model.target_words
        assert "fluffy" in model.target_words
        assert "my" in model.target_words

        # The word_list source_item mirrors the filtered pool and records
        # pattern-filter drops for debuggability.
        word_lists = [si for si in model.source_items if si.item_type == "word_list"]
        assert len(word_lists) == 1
        assert "la" not in word_lists[0].content.split(", ")
        assert word_lists[0].metadata.get("dropped_tokens") == "twen"

    def test_roll_and_read_item_rebuilt_from_filtered_words(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The adapt engine re-parses this item's raw text at consumption time —
        # if the raw block ships, the fragment re-enters through that path.
        model = self._model_for(monkeypatch, "y /ē/", self.RAW_Y_BLOCK)

        rolls = [si for si in model.source_items if si.item_type == "roll_and_read"]
        assert len(rolls) == 1
        tokens = rolls[0].content.split("\n")
        assert "la" not in tokens
        assert "twen" not in tokens
        assert "fluffy" in tokens


def test_lesson_100_classified_as_suffix_lesson() -> None:
    skill = skill_model_from_lesson(100)
    assert skill.specific_skill == "suffix_er_est"
    assert "r controlled" not in skill.specific_skill
