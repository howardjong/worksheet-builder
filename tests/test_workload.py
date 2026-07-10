"""Tests for adapt/workload.py — evidence-based per-lesson package budget."""

from __future__ import annotations

from adapt.rules import build_rules
from adapt.workload import (
    GRADE_WORKLOAD,
    derive_package_budget,
    resolve_package_cap,
)
from companion.schema import Accommodations, LearnerProfile, OperationalSignals
from skill.schema import LiteracySkillModel, SourceItem


def _skill(grade: str = "2", words: str = "sunny, funny, bunny, muddy") -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level=grade,
        domain="phonics",
        specific_skill="vowel_teams",
        learning_objectives=["Read y-as-long-e words"],
        target_words=[w.strip() for w in words.split(",")],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content=words, source_region_index=0),
            SourceItem(
                item_type="passage",
                content="The sunny puppy is funny. The bunny is muddy.",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sentence",
                content="The puppy is muddy. The bunny is funny.",
                source_region_index=2,
            ),
        ],
        extraction_confidence=1.0,
        template_type="ufli_word_work",
        lesson_number=None,  # corpus miss → ledger degrades gracefully
    )


def _profile(grade: str = "2", **kwargs: object) -> LearnerProfile:
    return LearnerProfile(name="Test", grade_level=grade, **kwargs)  # type: ignore[arg-type]


class TestDerivePackageBudget:
    def test_attention_ceiling_matches_grade_table(self) -> None:
        for grade, (segment, session) in GRADE_WORKLOAD.items():
            profile = _profile(grade)
            budget = derive_package_budget(_skill(grade), profile, build_rules(profile))
            assert budget.segment_minutes == segment
            assert budget.session_minutes == session
            assert budget.attention_max_worksheets == session // segment
            assert 1 <= budget.max_worksheets <= budget.attention_max_worksheets

    def test_light_lesson_earns_fewer_sheets_than_ceiling(self) -> None:
        """A lesson whose objectives fit one sheet is capped at 1, not padded to 3."""
        skill = _skill("2")
        skill = skill.model_copy(
            update={"source_items": [skill.source_items[0]]}  # word list only
        )
        profile = _profile("2")
        budget = derive_package_budget(skill, profile, build_rules(profile))
        assert budget.max_worksheets < budget.attention_max_worksheets

    def test_objectives_overflow_caps_at_ceiling_and_flags(self) -> None:
        """Dense objective demand is capped at the attention ceiling, loudly."""
        many_words = ", ".join(f"word{i}y" for i in range(60))
        skill = _skill("K", words=many_words)
        profile = _profile("K")
        budget = derive_package_budget(skill, profile, build_rules(profile))
        assert budget.max_worksheets == budget.attention_max_worksheets == 2
        assert budget.objectives_overflow is True
        assert "OVERFLOW" in budget.rationale

    def test_observed_session_duration_lowers_budget(self) -> None:
        profile = _profile(
            "2", operational_signals=OperationalSignals(avg_session_duration=9.0)
        )
        budget = derive_package_budget(_skill("2"), profile, build_rules(profile))
        assert budget.session_minutes == 9
        assert budget.attention_max_worksheets == 1  # 9 // 8

    def test_small_chunking_drops_one_segment(self) -> None:
        profile = _profile("2", accommodations=Accommodations(chunking_level="small"))
        budget = derive_package_budget(_skill("2"), profile, build_rules(profile))
        assert budget.session_minutes == 16  # 24 - 8
        assert budget.attention_max_worksheets == 2


class TestResolvePackageCap:
    def test_auto_returns_budget(self) -> None:
        profile = _profile("2")
        cap, budget = resolve_package_cap("auto", _skill("2"), profile, build_rules(profile))
        assert budget is not None
        assert cap == budget.max_worksheets

    def test_fixed_int(self) -> None:
        profile = _profile("2")
        cap, budget = resolve_package_cap("3", _skill("2"), profile, build_rules(profile))
        assert cap == 3
        assert budget is None

    def test_unset_zero_and_junk_mean_no_cap(self) -> None:
        profile = _profile("2")
        rules = build_rules(profile)
        for raw in ("", "0", "-1", "junk"):
            cap, budget = resolve_package_cap(raw, _skill("2"), profile, rules)
            assert cap is None
            assert budget is None
