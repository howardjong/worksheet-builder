"""Tests for validate/skill_parity.py and validate/adhd_compliance.py."""

from __future__ import annotations

import pytest

from adapt.engine import adapt_activity
from adapt.rules import build_rules
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    FeedbackPanel,
    ScaffoldConfig,
    Step,
)
from companion.schema import Accommodations, LearnerProfile, Preferences
from skill.schema import LiteracySkillModel, SourceItem
from validate.adhd_compliance import validate_adhd_compliance
from validate.ai_review import _apply_suggestions, review_adapted_worksheet
from validate.schema import ValidationResult
from validate.skill_parity import validate_age_band, validate_skill_parity

# --- Fixtures ---


def _phonics_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc_blending",
        learning_objectives=["Blend CVC words"],
        target_words=["tall", "call", "wall", "fall"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(item_type="word_list", content="tall, call, wall", source_region_index=0),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _fluency_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="fluency",
        specific_skill="decodable_text_cvce",
        learning_objectives=["Read a decodable passage"],
        target_words=["june", "flute", "tune"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(item_type="passage", content="June has a flute.", source_region_index=0),
        ],
        extraction_confidence=0.92,
        template_type="ufli_decodable_story",
    )


def _grade_1_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test",
        grade_level="1",
        accommodations=Accommodations(chunking_level="medium"),
    )


def _valid_adapted(skill: LiteracySkillModel) -> AdaptedActivityModel:
    """Generate a valid adapted model from a skill model."""
    return adapt_activity(skill, _grade_1_profile())


def _make_adapted(
    domain: str = "phonics",
    specific_skill: str = "cvc_blending",
    grade_level: str = "1",
    items_per_chunk: int = 3,
    num_chunks: int = 1,
    response_format: str = "write",
    has_worked_example: bool = True,
    has_feedback: bool = True,
    decoration_zones: list[tuple[float, float, float, float]] | None = None,
) -> AdaptedActivityModel:
    """Build a custom adapted model for testing specific violations."""
    chunks = []
    for c in range(1, num_chunks + 1):
        items = [
            ActivityItem(item_id=i, content=f"word{i}", response_format=response_format)
            for i in range(1, items_per_chunk + 1)
        ]
        chunks.append(
            ActivityChunk(
                chunk_id=c,
                micro_goal=f"Practice (Part {c})",
                instructions=[
                    Step(number=1, text="Read each word."),
                    Step(number=2, text="Write it down."),
                ],
                worked_example=None,
                items=items,
                response_format=response_format,
                time_estimate="About 5 minutes",
            )
        )

    if has_worked_example and chunks:
        from adapt.schema import Example

        chunks[0].worked_example = Example(
            instruction="Watch how I do it:", content='"word1" — I can read this!'
        )

    return AdaptedActivityModel(
        source_hash="test_source",
        skill_model_hash="test_skill",
        learner_profile_hash="test_profile",
        grade_level=grade_level,
        domain=domain,
        specific_skill=specific_skill,
        chunks=chunks,
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=decoration_zones or [(0.85, 0.0, 1.0, 0.12)],
        feedback=(FeedbackPanel(goal_statement="I can read CVC words") if has_feedback else None),
    )


# --- Skill Parity Tests ---


class TestSkillParity:
    def test_valid_adaptation_passes(self) -> None:
        skill = _phonics_skill()
        adapted = _valid_adapted(skill)
        result = validate_skill_parity(skill, adapted)
        assert result.passed
        assert result.checks_run >= 5

    def test_catches_domain_drift(self) -> None:
        skill = _phonics_skill()
        adapted = _make_adapted(domain="comprehension")
        result = validate_skill_parity(skill, adapted)
        assert not result.passed
        violations = [v for v in result.violations if v.check == "domain_preserved"]
        assert len(violations) == 1

    def test_warns_skill_drift(self) -> None:
        skill = _phonics_skill()
        adapted = _make_adapted(specific_skill="digraphs")
        result = validate_skill_parity(skill, adapted)
        # Skill drift is a warning, not an error
        warnings = [v for v in result.violations if v.check == "skill_preserved"]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_catches_grade_band_violation(self) -> None:
        skill = _phonics_skill()  # grade 1
        adapted = _make_adapted(grade_level="3")  # 2 levels apart
        result = validate_skill_parity(skill, adapted)
        assert not result.passed
        violations = [v for v in result.violations if v.check == "grade_appropriate"]
        assert len(violations) == 1

    def test_allows_adjacent_grade(self) -> None:
        skill = _phonics_skill()  # grade 1
        adapted = _make_adapted(grade_level="2")  # 1 level apart — OK
        result = validate_skill_parity(skill, adapted)
        grade_violations = [v for v in result.violations if v.check == "grade_appropriate"]
        assert len(grade_violations) == 0

    def test_catches_empty_adaptation(self) -> None:
        skill = _phonics_skill()
        adapted = _make_adapted(items_per_chunk=0)
        result = validate_skill_parity(skill, adapted)
        assert not result.passed
        violations = [v for v in result.violations if v.check == "non_empty"]
        assert len(violations) == 1

    def test_valid_format_substitution_passes(self) -> None:
        skill = _phonics_skill()
        # Circle instead of write — still valid for phonics
        adapted = _make_adapted(response_format="circle")
        result = validate_skill_parity(skill, adapted)
        format_violations = [v for v in result.violations if v.check == "response_types_compatible"]
        assert len(format_violations) == 0

    def test_passes_restructured_content(self) -> None:
        skill = _phonics_skill()
        # Different item count, same domain and skill
        adapted = _make_adapted(items_per_chunk=2, num_chunks=3)
        result = validate_skill_parity(skill, adapted)
        assert result.passed


class TestAgeBand:
    def test_matching_grade_passes(self) -> None:
        adapted = _make_adapted(grade_level="1")
        result = validate_age_band(adapted, "1")
        assert result.passed

    def test_mismatched_grade_warns(self) -> None:
        adapted = _make_adapted(grade_level="2")
        result = validate_age_band(adapted, "1")
        warnings = [v for v in result.violations if v.check == "grade_match"]
        assert len(warnings) == 1

    def test_excessive_items_flagged(self) -> None:
        adapted = _make_adapted(items_per_chunk=12)
        result = validate_age_band(adapted, "1")
        violations = [v for v in result.violations if v.check == "item_count_sanity"]
        assert len(violations) == 1


# --- ADHD Compliance Tests ---


class TestAdhdCompliance:
    def test_valid_adapted_passes(self) -> None:
        skill = _phonics_skill()
        adapted = _valid_adapted(skill)
        result = validate_adhd_compliance(adapted)
        assert result.passed
        assert result.checks_run >= 10

    def test_chunk_size_violation(self) -> None:
        # Grade K max large = 3, put 5 items
        adapted = _make_adapted(grade_level="K", items_per_chunk=5)
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "chunk_size_limit"]
        assert len(violations) == 1

    def test_chunk_size_uses_supplied_small_profile_rules(self) -> None:
        adapted = _make_adapted(grade_level="1", items_per_chunk=4)
        profile = LearnerProfile(
            name="Small chunks",
            grade_level="1",
            accommodations=Accommodations(chunking_level="small"),
        )
        rules = build_rules(profile)

        result = validate_adhd_compliance(adapted, rules=rules)

        violations = [v for v in result.violations if v.check == "chunk_size_limit"]
        assert len(violations) == 1
        assert violations[0].details["max"] == rules.max_items_per_chunk

    def test_numbered_instructions_violation(self) -> None:
        adapted = _make_adapted()
        # Corrupt instruction numbering
        adapted.chunks[0].instructions[0].number = 5
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "numbered_instructions"]
        assert len(violations) >= 1

    def test_decoration_budget_violation(self) -> None:
        adapted = _make_adapted(
            decoration_zones=[
                (0.0, 0.0, 0.1, 0.1),
                (0.5, 0.0, 0.6, 0.1),
                (0.9, 0.0, 1.0, 0.1),
            ]
        )
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "decoration_budget"]
        assert len(violations) == 1

    def test_decoration_budget_uses_high_intensity_rules(self) -> None:
        # Four decoration zones exceed the default limit of 2 but are within a
        # high-intensity profile's budget of 6, so supplying its rules clears
        # the violation (mirrors test_chunk_size_uses_supplied_small_profile_rules).
        adapted = _make_adapted(
            decoration_zones=[
                (0.0, 0.0, 0.1, 0.1),
                (0.2, 0.0, 0.3, 0.1),
                (0.5, 0.0, 0.6, 0.1),
                (0.9, 0.0, 1.0, 0.1),
            ]
        )
        high_profile = LearnerProfile(
            name="High dial",
            grade_level="1",
            preferences=Preferences(visual_intensity="high"),
        )
        high_rules = build_rules(high_profile)
        assert high_rules.max_decorative_elements == 6

        with_rules = validate_adhd_compliance(adapted, rules=high_rules)
        assert not [v for v in with_rules.violations if v.check == "decoration_budget"]

        # Without rules the legacy limit of 2 still flags the same worksheet.
        without_rules = validate_adhd_compliance(adapted)
        assert [v for v in without_rules.violations if v.check == "decoration_budget"]

    def test_missing_feedback_panel_warns(self) -> None:
        adapted = _make_adapted(has_feedback=False)
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "feedback_panel_present"]
        assert len(violations) == 1
        assert violations[0].severity == "warning"

    def test_missing_worked_example_warns(self) -> None:
        adapted = _make_adapted(has_worked_example=False)
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "worked_example_present"]
        assert len(violations) == 1

    def test_valid_decoration_zones(self) -> None:
        adapted = _make_adapted(decoration_zones=[(0.85, 0.0, 1.0, 0.12), (0.0, 0.88, 0.15, 1.0)])
        result = validate_adhd_compliance(adapted)
        zone_violations = [v for v in result.violations if v.check == "decoration_zone_valid"]
        assert len(zone_violations) == 0

    def test_invalid_decoration_zone_coords(self) -> None:
        adapted = _make_adapted(decoration_zones=[(0.0, 0.0, 1.5, 0.1)])
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "decoration_zone_valid"]
        assert len(violations) == 1

    def test_grade_k_chunk_limits(self) -> None:
        # Grade K, large = 3. Should pass with 3.
        adapted = _make_adapted(grade_level="K", items_per_chunk=3)
        result = validate_adhd_compliance(adapted)
        size_violations = [v for v in result.violations if v.check == "chunk_size_limit"]
        assert len(size_violations) == 0

    def test_no_accuracy_scoring(self) -> None:
        adapted = _make_adapted()
        adapted.chunks[0].reward_event = {"trigger": "accuracy_based", "tokens": 1}
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "no_accuracy_scoring"]
        assert len(violations) == 1

    def test_effort_based_reward_passes(self) -> None:
        adapted = _make_adapted()
        adapted.chunks[0].reward_event = {"trigger": "chunk_completion", "tokens": 1}
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "no_accuracy_scoring"]
        assert len(violations) == 0


class TestAiReview:
    def test_no_api_key_review_records_skipped_pass_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        original = _make_adapted()

        adapted, reviews = review_adapted_worksheet(original)

        assert adapted == original
        assert reviews[-1].passed is True
        assert reviews[-1].to_dict()["skipped_no_api_key"] is True

    def test_fix_content_preserves_activity_item_fields(self) -> None:
        original_item = ActivityItem(
            item_id=1,
            content="The slde is tall.",
            response_format="fill_blank",
            metadata={"display": "sentence_completion", "difficulty": 2},
            options=["slide", "slid", "side"],
            answer="slide",
            picture_prompt="A child going down a playground slide",
        )
        adapted = _make_adapted()
        adapted.chunks[0].items = [original_item]

        fixed = _apply_suggestions(
            adapted,
            [
                {
                    "chunk_id": "1",
                    "item_id": "1",
                    "action": "fix_content",
                    "fixed_content": "The slide is tall.",
                }
            ],
        )

        fixed_item = fixed.chunks[0].items[0]
        assert fixed_item.content == "The slide is tall."
        assert fixed_item.answer == original_item.answer
        assert fixed_item.options == original_item.options
        assert fixed_item.picture_prompt == original_item.picture_prompt
        assert fixed_item.response_format == original_item.response_format
        assert fixed_item.metadata == original_item.metadata


# --- ValidationResult Schema Tests ---


class TestValidationSchema:
    def test_result_round_trip(self) -> None:
        result = ValidationResult(validator="test", passed=True, checks_run=3)
        result.add_violation("test_check", "test message", severity="warning")
        json_str = result.model_dump_json()
        restored = ValidationResult.model_validate_json(json_str)
        assert restored.validator == "test"
        assert len(restored.violations) == 1
        assert restored.passed  # warning doesn't fail

    def test_error_sets_passed_false(self) -> None:
        result = ValidationResult(validator="test", passed=True, checks_run=1)
        result.add_violation("check", "error!", severity="error")
        assert not result.passed

    def test_warning_keeps_passed_true(self) -> None:
        result = ValidationResult(validator="test", passed=True, checks_run=1)
        result.add_violation("check", "just a warning", severity="warning")
        assert result.passed


def _worksheet_with_n_chunks(count: int, grade: str = "1") -> AdaptedActivityModel:
    chunks = [
        ActivityChunk(
            chunk_id=i + 1,
            micro_goal=f"Goal {i + 1}",
            instructions=[Step(number=1, text="Do the task.")],
            items=[ActivityItem(item_id=i + 1, content="cat", response_format="write")],
            response_format="write",
            time_estimate="About 2 minutes",
        )
        for i in range(count)
    ]
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level=grade,
        domain="phonics",
        specific_skill="cvc",
        chunks=chunks,
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        feedback=FeedbackPanel(goal_statement="I can read CVC words"),
    )


def test_sections_per_worksheet_cap_violated() -> None:
    from validate.adhd_compliance import validate_adhd_compliance

    result = validate_adhd_compliance(_worksheet_with_n_chunks(9, grade="1"))

    assert result.passed is False
    checks = [v.check for v in result.violations if v.severity == "error"]
    assert "sections_per_worksheet" in checks


def test_sections_per_worksheet_cap_respected() -> None:
    from validate.adhd_compliance import validate_adhd_compliance

    result = validate_adhd_compliance(_worksheet_with_n_chunks(3, grade="1"))

    checks = [v.check for v in result.violations]
    assert "sections_per_worksheet" not in checks


def test_sections_per_worksheet_uses_rules_when_provided() -> None:
    from adapt.rules import build_rules
    from companion.schema import Accommodations, LearnerProfile
    from validate.adhd_compliance import validate_adhd_compliance

    profile = LearnerProfile(name="t", grade_level="K", accommodations=Accommodations())
    result = validate_adhd_compliance(
        _worksheet_with_n_chunks(3, grade="K"), rules=build_rules(profile)
    )

    assert result.passed is False
    checks = [v.check for v in result.violations if v.severity == "error"]
    assert "sections_per_worksheet" in checks
