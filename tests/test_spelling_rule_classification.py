import pytest

from skill.lesson_loader import skill_model_from_lesson
from skill.taxonomy import match_phonics_pattern
from skill.transformation import verify_step


def test_transformation_objectives_classify_before_short_graphemes() -> None:
    cases = {
        "Suffixes; -s/-es": "suffix_s_es",
        "Prefixes; un-": "prefix_un",
        "pre-, re-": "prefix_pre_re",
        "dis-": "prefix_dis",
        "Doubling Rule: -ed, -ing": "doubling_ed_ing",
        "Doubling Rule: -er, -est": "doubling_er_est",
        "Drop E Rule": "drop_e_rule",
        "Y to I Rule": "y_to_i_rule",
        "-sion, -tion": "word_part_sion_tion",
        "-ture": "word_part_ture",
        "-er, -or, -ist": "suffix_er_or_ist",
        "-ish": "suffix_ish",
        "-y": "suffix_y",
        "-ment": "suffix_ment",
        "-able, -ible": "suffix_able_ible",
        "bi-, tri-, uni-": "prefix_bi_tri_uni",
        "Affixes Review": "affix_review",
        "Affixes Review 2": "affix_review",
    }
    assert {concept: match_phonics_pattern(concept) for concept in cases} == cases


def test_sound_patterns_are_not_misclassified_as_affixes() -> None:
    assert match_phonics_pattern("ar /er/, or /er/") == "r_controlled"
    assert match_phonics_pattern("-ing, -ang, -ong") == "cvc_blending"


@pytest.mark.parametrize(
    ("lesson_number", "expected_skill"),
    [
        (99, "suffix_s_es"),
        (100, "suffix_er_est"),
        (101, "suffix_ly"),
        (102, "suffix_less_ful"),
        (103, "prefix_un"),
        (104, "prefix_pre_re"),
        (105, "prefix_dis"),
        (106, "affix_review"),
        (107, "doubling_ed_ing"),
        (108, "doubling_er_est"),
        (109, "drop_e_rule"),
        (110, "y_to_i_rule"),
        (119, "word_part_sion_tion"),
        (120, "word_part_ture"),
        (121, "suffix_er_or_ist"),
        (122, "suffix_ish"),
        (123, "suffix_y"),
        (124, "suffix_ness"),
        (125, "suffix_ment"),
        (126, "suffix_able_ible"),
        (127, "prefix_bi_tri_uni"),
        (128, "affix_review"),
    ],
)
def test_corpus_examples_resolve_to_verified_objective_contracts(
    lesson_number: int, expected_skill: str
) -> None:
    """The current corpus is a fixture set, not a source-specific code path."""
    model = skill_model_from_lesson(lesson_number)
    transformations = [step for item in model.source_items for step in item.transformations]

    assert model.specific_skill == expected_skill
    assert transformations
    assert all(verify_step(step) for step in transformations)
