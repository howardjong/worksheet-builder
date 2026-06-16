"""Tests for adapt/objective_ledger.py — ObjectiveLedger schema contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapt.objective_ledger import (
    BlockingGateSpec,
    ClassifiedSourceItem,
    EvidenceItem,
    LedgerWord,
    ObjectiveCell,
    ObjectiveLedger,
    PatternContext,
    build_objective_ledger,
    classify_word_role,
)
from skill.schema import LiteracySkillModel
from tests.objective_corpus_fixture import fixture_corpus_lookup

_FIX = Path(__file__).parent / "fixtures" / "objective_ledger"


def _load(name: str) -> LiteracySkillModel:
    """Load a committed LiteracySkillModel fixture by stem (offline, no live artifacts)."""
    return LiteracySkillModel(**json.loads((_FIX / f"{name}.json").read_text()))


class TestObjectiveLedgerSchema:
    """Test ObjectiveLedger schema round-trips and validation."""

    def test_full_ledger_round_trips(self) -> None:
        """Construct a full ObjectiveLedger from literals, verify serialization round-trip."""
        ledger = ObjectiveLedger(
            ledger_version="objective_sufficiency_v1",
            source_skill_hash="abc123",
            lesson_number=43,
            corpus_status="matched",
            corpus_version="ufli_v2.1_2024",
            corpus_lesson_id="ufli_43",
            primary_pattern="sh",
            objectives=[
                ObjectiveCell(
                    objective_id="obj_decode_sh",
                    objective_type="decode_target_pattern",
                    display_name="Decode sh words",
                    concept="digraph sh",
                    target_pattern="sh",
                    importance="essential",
                    required_forms=["word_chain", "decodable_sentence"],
                    source_item_ids=["item_1"],
                    target_words=["ship", "shop"],
                    contrast_words=["chip"],
                    irregular_words=[],
                    min_practice_count=4,
                    max_recommended_count=10,
                    acceptable_response_formats=["read_aloud", "circle"],
                    sufficiency_rule="≥4 target words in word chain + ≥1 decodable sentence",
                )
            ],
            source_items=[
                ClassifiedSourceItem(
                    source_item_id="item_1",
                    item_type="word_chain",
                    content="ship shop chop chip",
                    normalized_content="ship shop chop chip",
                    coverage_class="required_form",
                    required_form="word_chain",
                    word_roles=[
                        LedgerWord(
                            text="ship",
                            normalized="ship",
                            role="target_pattern",
                            role_confidence="high",
                            role_source="corpus_exact",
                            objective_ids=["obj_decode_sh"],
                            source_item_id="item_1",
                            reason="Exact match in UFLI corpus for sh pattern",
                        )
                    ],
                    objective_ids=["obj_decode_sh"],
                    mandatory=True,
                    notes=["Primary decode chain"],
                )
            ],
            blocking_rules=BlockingGateSpec(
                answer_key_gate=True,
                source_notation_artifact_gate=True,
                instruction_option_answer_gate=True,
                capitalization_gate=True,
            ),
            builder_warnings=[],
        )

        # Round-trip via model_dump / model_validate
        dumped = ledger.model_dump()
        restored = ObjectiveLedger.model_validate(dumped)
        assert restored.source_skill_hash == "abc123"
        assert restored.lesson_number == 43
        assert restored.corpus_version == "ufli_v2.1_2024"
        assert len(restored.objectives) == 1
        assert restored.objectives[0].objective_id == "obj_decode_sh"
        assert restored.objectives[0].objective_type == "decode_target_pattern"
        assert len(restored.source_items) == 1
        assert restored.source_items[0].word_roles[0].role_confidence == "high"
        assert restored.source_items[0].word_roles[0].role_source == "corpus_exact"

        # Round-trip via JSON
        json_str = ledger.model_dump_json()
        restored_json = ObjectiveLedger.model_validate_json(json_str)
        assert restored_json.corpus_status == "matched"
        assert restored_json.objectives[0].target_pattern == "sh"

    def test_objective_type_enum_rejects_bad_value(self) -> None:
        """ObjectiveType Literal rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            ObjectiveCell(
                objective_id="obj_test",
                objective_type="invalid_type",  # type: ignore[arg-type]
                display_name="Test",
                concept="test",
                min_practice_count=1,
                max_recommended_count=5,
                sufficiency_rule="test rule",
            )
        assert "objective_type" in str(exc_info.value)

    def test_source_role_enum_rejects_bad_value(self) -> None:
        """SourceRole Literal rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            LedgerWord(
                text="ship",
                normalized="ship",
                role="invalid_role",  # type: ignore[arg-type]
                role_confidence="high",
                role_source="corpus_exact",
                reason="test",
            )
        assert "role" in str(exc_info.value)

    def test_coverage_class_enum_rejects_bad_value(self) -> None:
        """CoverageClass Literal rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            ClassifiedSourceItem(
                source_item_id="item_1",
                item_type="word_chain",
                content="test",
                normalized_content="test",
                coverage_class="invalid_class",  # type: ignore[arg-type]
                mandatory=True,
            )
        assert "coverage_class" in str(exc_info.value)

    def test_required_form_enum_rejects_bad_value(self) -> None:
        """RequiredForm Literal rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            ClassifiedSourceItem(
                source_item_id="item_1",
                item_type="word_chain",
                content="test",
                normalized_content="test",
                coverage_class="required_form",
                required_form="invalid_form",  # type: ignore[arg-type]
                mandatory=True,
            )
        assert "required_form" in str(exc_info.value)

    def test_ledger_word_requires_role_confidence(self) -> None:
        """LedgerWord must have role_confidence (no default)."""
        with pytest.raises(ValidationError) as exc_info:
            LedgerWord(  # type: ignore[call-arg]
                text="ship",
                normalized="ship",
                role="target_pattern",
                # role_confidence omitted — should fail
                role_source="corpus_exact",
                reason="test",
            )
        assert "role_confidence" in str(exc_info.value)

    def test_ledger_word_requires_role_source(self) -> None:
        """LedgerWord must have role_source (no default)."""
        with pytest.raises(ValidationError) as exc_info:
            LedgerWord(  # type: ignore[call-arg]
                text="ship",
                normalized="ship",
                role="target_pattern",
                role_confidence="high",
                # role_source omitted — should fail
                reason="test",
            )
        assert "role_source" in str(exc_info.value)

    def test_objective_ledger_requires_corpus_version(self) -> None:
        """ObjectiveLedger must have corpus_version (no default)."""
        with pytest.raises(ValidationError) as exc_info:
            ObjectiveLedger(  # type: ignore[call-arg]
                source_skill_hash="abc123",
                lesson_number=43,
                corpus_status="matched",
                # corpus_version omitted — should fail
                objectives=[],
                source_items=[],
            )
        assert "corpus_version" in str(exc_info.value)

    def test_evidence_item_round_trips(self) -> None:
        """EvidenceItem round-trips correctly."""
        evidence = EvidenceItem(
            visible_text="ship shop chop chip",
            practice_role="student_practice",
            answer_key_text=None,
            response_format="read_aloud",
            is_student_production=True,
            objective_ids=["obj_decode_sh"],
        )

        # Round-trip via model_dump / model_validate
        dumped = evidence.model_dump()
        restored = EvidenceItem.model_validate(dumped)
        assert restored.visible_text == "ship shop chop chip"
        assert restored.practice_role == "student_practice"
        assert restored.answer_key_text is None
        assert restored.response_format == "read_aloud"
        assert restored.is_student_production is True
        assert restored.objective_ids == ["obj_decode_sh"]

        # Round-trip via JSON
        json_str = evidence.model_dump_json()
        restored_json = EvidenceItem.model_validate_json(json_str)
        assert restored_json.visible_text == "ship shop chop chip"

    def test_role_confidence_enum_values(self) -> None:
        """RoleConfidence accepts 'high' and 'low', rejects others."""
        # Valid values
        word_high = LedgerWord(
            text="ship",
            normalized="ship",
            role="target_pattern",
            role_confidence="high",
            role_source="corpus_exact",
            reason="test",
        )
        assert word_high.role_confidence == "high"

        word_low = LedgerWord(
            text="ship",
            normalized="ship",
            role="target_pattern",
            role_confidence="low",
            role_source="pattern_rule",
            reason="test",
        )
        assert word_low.role_confidence == "low"

        # Invalid value
        with pytest.raises(ValidationError) as exc_info:
            LedgerWord(
                text="ship",
                normalized="ship",
                role="target_pattern",
                role_confidence="medium",  # type: ignore[arg-type]
                role_source="corpus_exact",
                reason="test",
            )
        assert "role_confidence" in str(exc_info.value)

    def test_role_source_enum_values(self) -> None:
        """RoleSource accepts valid values, rejects invalid ones."""
        # Valid values
        for source in ["corpus_exact", "pattern_rule", "source_context", "unknown"]:
            word = LedgerWord(
                text="ship",
                normalized="ship",
                role="target_pattern",
                role_confidence="high",
                role_source=source,  # type: ignore[arg-type]
                reason="test",
            )
            assert word.role_source == source

        # Invalid value
        with pytest.raises(ValidationError) as exc_info:
            LedgerWord(
                text="ship",
                normalized="ship",
                role="target_pattern",
                role_confidence="high",
                role_source="invalid_source",  # type: ignore[arg-type]
                reason="test",
            )
        assert "role_source" in str(exc_info.value)

    def test_corpus_status_enum_values(self) -> None:
        """corpus_status accepts valid values, rejects invalid ones."""
        # Valid values
        for status in ["matched", "missing", "not_applicable"]:
            ledger = ObjectiveLedger(
                source_skill_hash="abc123",
                lesson_number=43,
                corpus_status=status,  # type: ignore[arg-type]
                corpus_version="v1",
                objectives=[],
                source_items=[],
            )
            assert ledger.corpus_status == status

        # Invalid value
        with pytest.raises(ValidationError) as exc_info:
            ObjectiveLedger(
                source_skill_hash="abc123",
                lesson_number=43,
                corpus_status="invalid_status",  # type: ignore[arg-type]
                corpus_version="v1",
                objectives=[],
                source_items=[],
            )
        assert "corpus_status" in str(exc_info.value)


# ----------------------------------------------------------------------------
# Helpers for the classifier tests
# ----------------------------------------------------------------------------


def _u_e_context(
    *,
    corpus_target_words: frozenset[str] = frozenset(),
    irregular_words: frozenset[str] = frozenset(),
    review_words: frozenset[str] = frozenset(),
    is_contrast_context: bool = False,
    corpus_matched: bool = True,
) -> PatternContext:
    """A u_e (long-u CVCe) lesson context for classifier tests."""
    return PatternContext(
        pattern_key="u_e",
        pattern_kind="vce",
        vowel="u",
        rimes=frozenset(),
        corpus_target_words=corpus_target_words,
        irregular_words=irregular_words,
        review_words=review_words,
        is_contrast_context=is_contrast_context,
        corpus_matched=corpus_matched,
    )


def _oll_context(
    *,
    corpus_target_words: frozenset[str] = frozenset(),
    irregular_words: frozenset[str] = frozenset(),
    review_words: frozenset[str] = frozenset(),
    is_contrast_context: bool = False,
    corpus_matched: bool = True,
) -> PatternContext:
    """An -all/-oll/-ull word-family lesson context for classifier tests."""
    return PatternContext(
        pattern_key="oll",
        pattern_kind="rime",
        vowel=None,
        rimes=frozenset({"all", "oll", "ull"}),
        corpus_target_words=corpus_target_words,
        irregular_words=irregular_words,
        review_words=review_words,
        is_contrast_context=is_contrast_context,
        corpus_matched=corpus_matched,
    )


class TestPatternContext:
    """PatternContext is a typed, frozen, round-trippable data contract."""

    def test_pattern_context_round_trips(self) -> None:
        ctx = _u_e_context(
            corpus_target_words=frozenset({"cube", "mute"}),
            irregular_words=frozenset({"who", "one"}),
        )
        restored = PatternContext.model_validate_json(ctx.model_dump_json())
        assert restored.pattern_key == "u_e"
        assert restored.vowel == "u"
        assert restored.corpus_target_words == frozenset({"cube", "mute"})
        assert restored.irregular_words == frozenset({"who", "one"})

    def test_pattern_context_is_frozen(self) -> None:
        ctx = _u_e_context()
        with pytest.raises(ValidationError):
            ctx.pattern_key = "a_e"


class TestClassifyWordRoleUE:
    """RED cases — u_e (long-u CVCe) lesson context."""

    def test_cute_is_target_pattern_high(self) -> None:
        ctx = _u_e_context(corpus_target_words=frozenset({"cute", "mute"}))
        role, conf, src = classify_word_role("cute", ctx)
        assert role == "target_pattern"
        assert conf == "high"
        assert src in ("corpus_exact", "pattern_rule")

    def test_cute_via_pattern_rule_when_not_in_corpus(self) -> None:
        # No corpus membership for cute → must still resolve via clean CVCe rule.
        ctx = _u_e_context(corpus_target_words=frozenset())
        role, conf, src = classify_word_role("cute", ctx)
        assert role == "target_pattern"
        assert conf == "high"
        assert src == "pattern_rule"

    def test_mute_is_target_pattern_high(self) -> None:
        ctx = _u_e_context(corpus_target_words=frozenset({"cube", "mute"}))
        role, conf, src = classify_word_role("mute", ctx)
        assert role == "target_pattern"
        assert conf == "high"

    def test_who_is_irregular_high_corpus(self) -> None:
        ctx = _u_e_context(irregular_words=frozenset({"who", "one"}))
        assert classify_word_role("who", ctx) == ("irregular_word", "high", "corpus_exact")

    def test_one_is_irregular_high_corpus(self) -> None:
        ctx = _u_e_context(irregular_words=frozenset({"who", "one"}))
        assert classify_word_role("one", ctx) == ("irregular_word", "high", "corpus_exact")

    def test_type_is_ambiguous_low_y_as_vowel(self) -> None:
        ctx = _u_e_context()
        role, conf, _src = classify_word_role("type", ctx)
        assert role == "ambiguous_review_word"
        assert conf == "low"

    def test_gym_is_ambiguous_low_y_as_vowel(self) -> None:
        ctx = _u_e_context()
        role, conf, _src = classify_word_role("gym", ctx)
        assert role == "ambiguous_review_word"
        assert conf == "low"

    def test_corpus_miss_caps_confidence_low(self) -> None:
        # corpus_matched=False → graceful degrade: never high-confidence.
        ctx = _u_e_context(
            corpus_target_words=frozenset({"cute"}),
            corpus_matched=False,
        )
        _role, conf, _src = classify_word_role("cute", ctx)
        assert conf == "low"

    def test_unresolvable_word_is_low(self) -> None:
        # A word that matches nothing and no framing → low confidence.
        ctx = _u_e_context()
        _role, conf, _src = classify_word_role("zxqwv", ctx)
        assert conf == "low"

    def test_irregular_takes_priority_over_visual_pattern(self) -> None:
        # "use" visually contains u_e but is supplied as an irregular/heart word.
        ctx = _u_e_context(irregular_words=frozenset({"use"}))
        role, conf, src = classify_word_role("use", ctx)
        assert role == "irregular_word"
        assert conf == "high"
        assert src == "corpus_exact"

    def test_normalizes_case_and_punctuation(self) -> None:
        ctx = _u_e_context(corpus_target_words=frozenset({"cute"}))
        role, conf, _src = classify_word_role("Cute!", ctx)
        assert role == "target_pattern"
        assert conf == "high"


class TestClassifyWordRoleOll:
    """RED cases — -all/-oll/-ull word-family lesson context."""

    def test_mop_is_not_target_high(self) -> None:
        ctx = _oll_context(corpus_target_words=frozenset({"doll", "roll", "toll"}))
        role, conf, src = classify_word_role("mop", ctx)
        assert role in ("review_word", "contrast_word")
        assert role != "target_pattern"
        assert conf == "high"
        assert src == "pattern_rule"

    def test_jazz_is_not_target_high(self) -> None:
        ctx = _oll_context(corpus_target_words=frozenset({"doll", "roll", "toll"}))
        role, conf, src = classify_word_role("jazz", ctx)
        assert role in ("review_word", "contrast_word")
        assert role != "target_pattern"
        assert conf == "high"
        assert src == "pattern_rule"

    def test_mop_is_contrast_word_under_contrast_framing(self) -> None:
        ctx = _oll_context(is_contrast_context=True)
        role, conf, src = classify_word_role("mop", ctx)
        assert role == "contrast_word"
        assert conf == "high"
        assert src == "pattern_rule"

    def test_roll_is_target_pattern_high(self) -> None:
        ctx = _oll_context(corpus_target_words=frozenset({"doll", "roll", "toll"}))
        role, conf, _src = classify_word_role("roll", ctx)
        assert role == "target_pattern"
        assert conf == "high"

    def test_toll_via_rime_rule_when_not_in_corpus(self) -> None:
        ctx = _oll_context(corpus_target_words=frozenset())
        role, conf, src = classify_word_role("toll", ctx)
        assert role == "target_pattern"
        assert conf == "high"
        assert src == "pattern_rule"


# ----------------------------------------------------------------------------
# T3 — build_objective_ledger (deterministic builder)
# ----------------------------------------------------------------------------


def _cell(ledger: ObjectiveLedger, objective_type: str) -> ObjectiveCell | None:
    """Return the first objective cell of a given type, or None."""
    return next((c for c in ledger.objectives if c.objective_type == objective_type), None)


def _items_of_class(ledger: ObjectiveLedger, coverage_class: str) -> list[ClassifiedSourceItem]:
    return [si for si in ledger.source_items if si.coverage_class == coverage_class]


def _all_words(ledger: ObjectiveLedger) -> list[LedgerWord]:
    return [w for si in ledger.source_items for w in si.word_roles]


class TestBuildObjectiveLedgerCorpusMatched:
    """RED — builder against the committed lesson-58 / lesson-59 fixtures (real corpus)."""

    @pytest.mark.parametrize("name", ["lesson58", "lesson59"])
    def test_manipulation_cell_and_required_chain_forms(self, name: str) -> None:
        ledger = build_objective_ledger(_load(name), corpus_lookup=fixture_corpus_lookup)
        cell = _cell(ledger, "phoneme_grapheme_manipulation")
        assert cell is not None

        chain_items = [
            si for si in ledger.source_items if si.item_type in ("word_chain", "chain_script")
        ]
        assert chain_items, "expected word_chain / chain_script source items"
        for si in chain_items:
            assert si.coverage_class == "required_form"
            assert si.required_form in ("word_chain", "chain_script")
        # The form tag must match the item type.
        for si in chain_items:
            if si.item_type == "word_chain":
                assert si.required_form == "word_chain"
            else:
                assert si.required_form == "chain_script"

    @pytest.mark.parametrize("name", ["lesson58", "lesson59"])
    def test_roll_and_read_samplable_pool_from_corpus(self, name: str) -> None:
        ledger = build_objective_ledger(_load(name), corpus_lookup=fixture_corpus_lookup)
        pools = _items_of_class(ledger, "samplable_pool")
        assert pools, "expected a samplable_pool ClassifiedSourceItem"
        # At least one pool must originate from the corpus Roll-and-Read additional_text.
        assert any("roll" in si.item_type or "roll" in " ".join(si.notes).lower() for si in pools)

    @pytest.mark.parametrize("name", ["lesson58", "lesson59"])
    def test_connected_text_required_passage_from_corpus(self, name: str) -> None:
        ledger = build_objective_ledger(_load(name), corpus_lookup=fixture_corpus_lookup)
        cell = _cell(ledger, "connected_text_fluency")
        assert cell is not None
        passage_items = [
            si for si in ledger.source_items if si.required_form == "decodable_passage"
        ]
        assert passage_items, "expected a decodable_passage required_form item"
        assert all(si.coverage_class == "required_form" for si in passage_items)

    @pytest.mark.parametrize("name", ["lesson58", "lesson59"])
    def test_irregular_cell_words_and_no_leak_into_decode(self, name: str) -> None:
        ledger = build_objective_ledger(_load(name), corpus_lookup=fixture_corpus_lookup)
        irr = _cell(ledger, "irregular_word_reading")
        assert irr is not None
        assert irr.irregular_words, "irregular cell must list its irregular words"

        # Every word attached to the sight_words item is role irregular_word.
        sight_items = [si for si in ledger.source_items if si.item_type == "sight_words"]
        assert sight_items
        for si in sight_items:
            for w in si.word_roles:
                assert w.role == "irregular_word"

        # None of the irregular words leak into the decode cell's target list.
        decode = _cell(ledger, "decode_target_pattern")
        assert decode is not None
        decode_targets = set(decode.target_words)
        for irr_word in irr.irregular_words:
            assert irr_word not in decode_targets

    def test_lesson58_decode_excludes_known_irregulars(self) -> None:
        ledger = build_objective_ledger(_load("lesson58"), corpus_lookup=fixture_corpus_lookup)
        decode = _cell(ledger, "decode_target_pattern")
        assert decode is not None
        # 'one'/'once' are sight words → never in the decode numerator.
        assert "one" not in decode.target_words
        assert "once" not in decode.target_words
        # The decode cell must hold some genuine u_e targets.
        assert any(w in decode.target_words for w in ("cube", "mute", "tune", "rule"))

    def test_lesson59_decode_excludes_who_one(self) -> None:
        ledger = build_objective_ledger(_load("lesson59"), corpus_lookup=fixture_corpus_lookup)
        decode = _cell(ledger, "decode_target_pattern")
        assert decode is not None
        for irr in ("who", "by", "my", "one", "once"):
            assert irr not in decode.target_words

    def test_decode_target_words_are_only_target_pattern_role(self) -> None:
        ledger = build_objective_ledger(_load("lesson58"), corpus_lookup=fixture_corpus_lookup)
        decode = _cell(ledger, "decode_target_pattern")
        assert decode is not None
        target_set = set(decode.target_words)
        # Build a role index from every classified word.
        roles: dict[str, set[str]] = {}
        for w in _all_words(ledger):
            roles.setdefault(w.normalized, set()).add(w.role)
        for tw in target_set:
            assert "target_pattern" in roles.get(tw, set()), f"{tw} not target_pattern role"

    @pytest.mark.parametrize("name", ["lesson58", "lesson59", "lesson43_oll"])
    def test_corpus_version_stamped_and_status_matched(self, name: str) -> None:
        ledger = build_objective_ledger(_load(name), corpus_lookup=fixture_corpus_lookup)
        assert ledger.corpus_status == "matched"
        assert isinstance(ledger.corpus_version, str)
        assert ledger.corpus_version
        assert ledger.corpus_version != "no_corpus"

    @pytest.mark.parametrize("name", ["lesson58", "lesson59", "lesson43_oll"])
    def test_stable_across_calls(self, name: str) -> None:
        skill = _load(name)
        a = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup).model_dump_json()
        b = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup).model_dump_json()
        assert a == b

    def test_no_contrast_cell_for_fixtures(self) -> None:
        # Lessons 58/59/43 have no deliberate contrast task → no contrast cell.
        for name in ("lesson58", "lesson59", "lesson43_oll"):
            ledger = build_objective_ledger(_load(name), corpus_lookup=fixture_corpus_lookup)
            assert _cell(ledger, "contrast_discrimination") is None


class TestBuildObjectiveLedgerOll:
    """RED — the -all/-oll/-ull fixture (lesson 43): contrast WORDS must not count."""

    def test_mop_jazz_not_in_decode_targets(self) -> None:
        ledger = build_objective_ledger(_load("lesson43_oll"), corpus_lookup=fixture_corpus_lookup)
        decode = _cell(ledger, "decode_target_pattern")
        assert decode is not None
        assert "mop" not in decode.target_words
        assert "jazz" not in decode.target_words
        # Genuine rime targets are present.
        assert any(w in decode.target_words for w in ("doll", "roll", "toll"))

    def test_manipulation_cell_exists(self) -> None:
        ledger = build_objective_ledger(_load("lesson43_oll"), corpus_lookup=fixture_corpus_lookup)
        assert _cell(ledger, "phoneme_grapheme_manipulation") is not None


class TestBuildObjectiveLedgerGracefulDegrade:
    """RED — corpus miss / non-UFLI input degrades to low-confidence, no_corpus sentinel."""

    def test_corpus_miss_via_stub(self) -> None:
        ledger = build_objective_ledger(_load("lesson58"), corpus_lookup=lambda n: None)
        assert ledger.corpus_status == "missing"
        assert ledger.corpus_version == "no_corpus"
        words = _all_words(ledger)
        assert words, "expected some classified words even on corpus miss"
        assert all(w.role_confidence == "low" for w in words)

    def test_no_lesson_number_is_not_applicable(self) -> None:
        skill = _load("lesson58").model_copy(update={"lesson_number": None})
        ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
        assert ledger.corpus_status == "not_applicable"
        assert ledger.corpus_version == "no_corpus"
        assert all(w.role_confidence == "low" for w in _all_words(ledger))

    def test_degraded_ledger_is_stable(self) -> None:
        skill = _load("lesson58")
        a = build_objective_ledger(skill, corpus_lookup=lambda n: None).model_dump_json()
        b = build_objective_ledger(skill, corpus_lookup=lambda n: None).model_dump_json()
        assert a == b
