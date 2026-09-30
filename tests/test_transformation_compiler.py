from adapt.transformation_compiler import activity_item_for, instruction_steps_for
from skill.contract import contract_for_skill_id
from skill.transformation import TransformationStep, analyze_chain, replay_operations


def _step(skill_id: str, chain: str) -> TransformationStep:
    contract = contract_for_skill_id(skill_id)
    assert contract is not None
    return analyze_chain(chain, contract)[0]


def test_compiler_hides_answer_and_preserves_typed_step() -> None:
    step = _step("drop_e_rule", "smile -> smiling")
    item = activity_item_for(step, 1)
    assert "smiling" not in item.content
    assert item.answer == "smiling"
    assert item.response_format == "write"
    assert item.transformation == step
    assert replay_operations(step.from_word, step.operations) == item.answer


def test_compiler_uses_truthful_rule_language() -> None:
    cases = [
        (
            "doubling_ed_ing",
            "skip -> skipped",
            "Double the final consonant in each base word.",
        ),
        ("drop_e_rule", "smile -> smiling", "Drop the final e in each base word."),
        (
            "y_to_i_rule",
            "happy -> happier",
            "Change the final y to i in each base word.",
        ),
        ("prefix_un", "safe -> unsafe", "Add un- to the beginning."),
        ("suffix_ness", "dark -> darkness", "Add -ness."),
    ]
    for skill_id, chain, expected in cases:
        texts = [instruction.text for instruction in instruction_steps_for(_step(skill_id, chain))]
        assert expected in texts


def test_change_one_letter_requires_verified_substitution() -> None:
    step = _step("letter_chain", "cry -> try")
    item = activity_item_for(step, 1)
    assert [operation.kind for operation in step.operations] == ["substitute_grapheme"]
    assert len(step.from_word) == len(step.to_word)
    assert "change" in item.content.casefold()


def test_mixed_endings_use_per_problem_directions() -> None:
    from adapt.transformation_compiler import compile_transformation_chunk

    contract = contract_for_skill_id("suffix_er_est")
    assert contract is not None
    steps = [_step("suffix_er_est", chain) for chain in ("slow -> slowest", "long -> longer")]
    chunk = compile_transformation_chunk(
        steps,
        contract,
        chunk_id=1,
        item_id_start=0,
        max_items=4,
        include_example=False,
    )
    assert chunk is not None
    assert "-est" in chunk.items[0].content and "-er" in chunk.items[1].content
    assert [step.text for step in chunk.instructions] == [
        "Read the starting word in each problem.",
        "Add the ending printed in each problem.",
        "Write each complete new word on its line.",
    ]


def test_standalone_ness_targets_reconstruct_real_y_base() -> None:
    from adapt.engine import _build_add_ending_chunk

    chunk = _build_add_ending_chunk(["greediness", "grumpiness"], ["ness"], 1, 0)
    assert all("greedi +" not in item.content for item in chunk.items)
    assert all("grumpi +" not in item.content for item in chunk.items)
    assert [item.transformation.from_word for item in chunk.items if item.transformation] == [
        "greedy",
        "grumpy",
    ]
