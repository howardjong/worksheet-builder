"""Tests for adapt/objective_ledger.py — ObjectiveLedger schema contracts."""

from __future__ import annotations

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
    classify_word_role,
)


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
            practice_role="decode_chain",
            answer_key_text=None,
            response_format="read_aloud",
            is_student_production=True,
            objective_ids=["obj_decode_sh"],
        )

        # Round-trip via model_dump / model_validate
        dumped = evidence.model_dump()
        restored = EvidenceItem.model_validate(dumped)
        assert restored.visible_text == "ship shop chop chip"
        assert restored.practice_role == "decode_chain"
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
