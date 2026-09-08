from skill.contract import (
    TRANSFORMATION_CONTRACTS,
    contract_for_skill_id,
    match_transformation_contract,
)
from skill.transformation import analyze_chain, verify_step


def test_registry_ids_are_unique_and_complete() -> None:
    ids = [contract.skill_id for contract in TRANSFORMATION_CONTRACTS]
    assert len(ids) == len(set(ids))
    assert all(
        contract.goal_statement and contract.operation_label
        for contract in TRANSFORMATION_CONTRACTS
    )


def test_contract_resolution_is_objective_based_not_source_based() -> None:
    assert match_transformation_contract("Practice the Drop E Rule").skill_id == "drop_e_rule"  # type: ignore[union-attr]
    assert match_transformation_contract("Y to I Rule").skill_id == "y_to_i_rule"  # type: ignore[union-attr]
    assert match_transformation_contract("Doubling Rule: -ed, -ing").skill_id == "doubling_ed_ing"  # type: ignore[union-attr]
    assert match_transformation_contract("Prefix: un-").skill_id == "prefix_un"  # type: ignore[union-attr]


def test_ness_prefers_truthful_y_to_i_transformation() -> None:
    contract = contract_for_skill_id("suffix_ness")
    assert contract is not None
    step = analyze_chain("greedy -> greediness", contract)[0]
    assert verify_step(step)
    assert [operation.kind for operation in step.operations] == ["change_y_to_i", "append_affix"]
    assert step.from_word == "greedy"


def test_orthographic_and_affix_contracts_replay() -> None:
    cases = {
        "prefix_un": "safe -> unsafe",
        "doubling_ed_ing": "skip -> skipped -> skipping",
        "drop_e_rule": "smile -> smiled -> smiling",
        "y_to_i_rule": "dry -> dries -> dried",
        "suffix_less_ful": "pain -> painless -> painful",
    }
    for skill_id, chain in cases.items():
        contract = contract_for_skill_id(skill_id)
        assert contract is not None
        steps = analyze_chain(chain, contract)
        assert steps and all(verify_step(step) for step in steps)


def test_unknown_contract_does_not_guess() -> None:
    assert contract_for_skill_id("made_up_rule") is None
    assert match_transformation_contract("Unrecognized spelling idea") is None
