"""Post-hoc objective-sufficiency package validation (spec 2026-07-10 P3a)."""

from __future__ import annotations

from adapt.engine import adapt_lesson
from adapt.schema import AdaptedActivityModel
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from validate.objective_package import validate_objective_package


def _skill_with_essentials() -> LiteracySkillModel:
    """A skill whose ledger yields exactly obj_decode/obj_encode/obj_manipulation/
    obj_connected_text (all essential): word_list + word_chain + passage, no
    sight_words item (which would add obj_irregular), lesson_number=None (no
    corpus injection). Adapted from tests/test_workload.py::_skill_with_essentials
    with one change: that fixture's chain ("un -> sunny -> ...") opens with a
    fragment hop that is not a single-letter change, which adapt/engine.py::
    _parse_chain_steps deliberately drops — so no engine-authored package can
    ever practice it, and the validator CORRECTLY fails such a package (a true
    positive). This "all forms present" test needs a chain the engine can
    author in full: every hop a real single-letter change."""
    return LiteracySkillModel(
        grade_level="2",
        domain="phonics",
        specific_skill="vowel_teams",
        learning_objectives=["Read y-as-long-e words"],
        target_words=["sunny", "funny", "bunny", "muddy"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list", content="sunny, funny, bunny, muddy", source_region_index=0
            ),
            SourceItem(
                item_type="word_chain",
                content="sunny -> funny -> bunny",
                source_region_index=1,
            ),
            SourceItem(
                item_type="passage",
                content="The sunny puppy is funny. The bunny is muddy.",
                source_region_index=2,
            ),
        ],
        extraction_confidence=1.0,
        template_type="ufli_word_work",
        lesson_number=None,  # corpus miss -> ledger degrades gracefully, no injects
    )


def _worksheets_covering(skill: LiteracySkillModel) -> list[AdaptedActivityModel]:
    """Deterministic (no LLM) adaptation: plain profile, no LLM env flags set."""
    profile = LearnerProfile(name="Test", grade_level="2")
    return adapt_lesson(skill, profile, theme_id="default")


def _remove_chain_chunks(worksheet: AdaptedActivityModel) -> AdaptedActivityModel:
    """Strip every chunk whose items were authored from the word_chain source.

    Discriminator: adapt/engine.py::_build_builder_chunks tags every chain-step
    item with metadata={"display": "chain_step"} (or "chain" in the read-only
    fallback path) -- the only items that carry that metadata key.
    """
    kept_chunks = [
        chunk
        for chunk in worksheet.chunks
        if not any(item.metadata.get("display") in ("chain_step", "chain") for item in chunk.items)
    ]
    return worksheet.model_copy(update={"chunks": kept_chunks})


def test_package_with_all_essential_forms_passes() -> None:
    skill = _skill_with_essentials()
    worksheets = _worksheets_covering(skill)
    result = validate_objective_package(skill, worksheets)
    assert result.status in ("pass", "needs_verification")


def test_package_missing_required_form_fails() -> None:
    skill = _skill_with_essentials()
    worksheets = _worksheets_covering(skill)
    gutted = [_remove_chain_chunks(ws) for ws in worksheets]
    result = validate_objective_package(skill, gutted)
    assert result.status == "fail"
    failing = [c for c in result.objective_results if c.status == "fail"]
    assert any("word_chain" in c.missing_required_forms for c in failing)
