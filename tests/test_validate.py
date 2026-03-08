"""Tests for validate/skill_parity.py and validate/adhd_compliance.py."""

from __future__ import annotations

from adapt.engine import adapt_activity
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from validate.adhd_compliance import validate_adhd_compliance
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
    has_self_assessment: bool = True,
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
        self_assessment=(
            ["I can read CVC words", "I'm still learning"] if has_self_assessment else None
        ),
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

    def test_missing_self_assessment_warns(self) -> None:
        adapted = _make_adapted(has_self_assessment=False)
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "self_assessment_present"]
        assert len(violations) == 1
        assert violations[0].severity == "warning"

    def test_missing_worked_example_warns(self) -> None:
        adapted = _make_adapted(has_worked_example=False)
        result = validate_adhd_compliance(adapted)
        violations = [v for v in result.violations if v.check == "worked_example_present"]
        assert len(violations) == 1

    def test_valid_decoration_zones(self) -> None:
        adapted = _make_adapted(
            decoration_zones=[(0.85, 0.0, 1.0, 0.12), (0.0, 0.88, 0.15, 1.0)]
        )
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
