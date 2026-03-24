"""Tests for cross-worksheet time budget validation."""

from __future__ import annotations

from adapt.engine import adapt_lesson
from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel, ScaffoldConfig, Step
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from validate.adhd_compliance import validate_lesson_time_budget


def _ufli_59_skill() -> LiteracySkillModel:
    """Synthetic UFLI Lesson 59 skill model with varied content types."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=[
            "Read words with CVCe pattern",
            "Apply CVCe pattern in connected text",
        ],
        target_words=["grade", "chase", "slide", "quite", "froze", "these"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, chase, slide, quite, froze, these",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content=(
                    "1. tune → tone → cone → cane "
                    "2. tame → time → dime → dome"
                ),
                source_region_index=1,
            ),
            SourceItem(
                item_type="sight_words",
                content="who, by, my, one, once",
                source_region_index=2,
            ),
            SourceItem(
                item_type="sentence",
                content=(
                    "1. The grade on the slide was quite nice. "
                    "2. These froze by the chase."
                ),
                source_region_index=3,
            ),
            SourceItem(
                item_type="passage",
                content=(
                    "A Cake for Tess. Tess had a cake. "
                    "The cake was huge! She made it with love."
                ),
                source_region_index=4,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _grade_1_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test G1",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="medium",
            response_format_prefs=["write", "circle"],
        ),
    )


class TestLessonTimeBudget:
    def test_normal_lesson_passes(self) -> None:
        """Normal lessons should pass time budget validation."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        result = validate_lesson_time_budget(worksheets)
        assert result.passed is True
        # Should have no violations with check "total_time_budget"
        total_time_violations = [
            v for v in result.violations
            if v.check == "total_time_budget"
        ]
        assert len(total_time_violations) == 0

    def test_warns_when_over_20_minutes(self) -> None:
        """Lessons exceeding 20 minutes should generate a warning."""
        # Generate real worksheets then inflate time estimates
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())

        # Manually inflate time estimates to exceed 20 minutes
        for ws in worksheets:
            for chunk in ws.chunks:
                chunk.time_estimate = "About 10 minutes"

        result = validate_lesson_time_budget(worksheets)

        # Should still pass (warnings don't fail validation)
        assert result.passed is True

        # Should have a warning violation with check "total_time_budget"
        total_time_violations = [
            v for v in result.violations
            if v.check == "total_time_budget"
        ]
        assert len(total_time_violations) >= 1
        assert total_time_violations[0].severity == "warning"

    def test_empty_worksheets_passes(self) -> None:
        """Empty worksheet list should pass with 0 violations."""
        result = validate_lesson_time_budget([])
        assert result.passed is True
        assert len(result.violations) == 0

    def test_individual_worksheet_time_limit(self) -> None:
        """Individual worksheets exceeding 8 minutes should generate a warning."""
        # Create a single worksheet with inflated time
        ws = AdaptedActivityModel(
            source_hash="test123",
            skill_model_hash="skill456",
            learner_profile_hash="profile789",
            grade_level="1",
            domain="phonics",
            specific_skill="test_skill",
            chunks=[
                ActivityChunk(
                    chunk_id=1,
                    micro_goal="Test goal",
                    instructions=[Step(number=1, text="Test instruction")],
                    items=[
                        ActivityItem(
                            item_id=1,
                            content="test",
                            response_format="write",
                        )
                    ],
                    response_format="write",
                    time_estimate="About 10 minutes",
                )
            ],
            scaffolding=ScaffoldConfig(),
            theme_id="default",
            decoration_zones=[],
            worksheet_number=1,
            worksheet_count=1,
        )

        result = validate_lesson_time_budget([ws])

        # Should pass but with a warning
        assert result.passed is True
        worksheet_time_violations = [
            v for v in result.violations
            if v.check == "worksheet_time_limit"
        ]
        assert len(worksheet_time_violations) >= 1
        assert worksheet_time_violations[0].severity == "warning"
