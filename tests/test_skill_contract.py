"""Skill contract registry: per-suffix-family correctness facts as data."""

from skill.contract import SUFFIX_CONTRACTS, contract_for_skill, known_suffix_tokens

# Exact strings currently hardcoded in adapt/objective_ledger.py:809-815.
SINGLE_HOP_RULE = (
    "≥2 add-the-ending transformations (base + suffix → new word); this "
    "suffix forms no multi-step chain, so independent pairs ARE this "
    "lesson's manipulation form"
)
MULTI_HOP_RULE = "≥1 coherent build/change chain (count steps, not words)"


def test_registry_covers_exactly_the_current_morphology_tokens() -> None:
    # Byte-identity bar for the migration: same token universe as
    # skill/taxonomy.py MORPHOLOGY_SUFFIXES before this branch.
    assert known_suffix_tokens() == frozenset({"er", "est", "ed", "ly", "es"})


def test_er_est_contract_carries_the_bespoke_goal_text() -> None:
    contract = contract_for_skill("suffix_er_est")
    assert contract is not None
    assert contract.goal_statement == "I can add -er and -est to compare things"
    assert contract.skill_slug == "suffix_er_est"


def test_ly_contract_matches_current_generic_goal_text() -> None:
    contract = contract_for_skill("suffix_ly")
    assert contract is not None
    assert contract.goal_statement == "I can add -ly to words"


def test_all_contracts_carry_current_manipulation_wording() -> None:
    for contract in SUFFIX_CONTRACTS:
        assert contract.manipulation_rule_single_hop == SINGLE_HOP_RULE
        assert contract.manipulation_rule_multi_hop == MULTI_HOP_RULE


def test_unknown_and_non_suffix_slugs_return_none() -> None:
    assert contract_for_skill("suffix_ness") is None  # not registered until Task 5
    assert contract_for_skill("cvc_blending") is None


def test_token_order_does_not_matter_for_lookup() -> None:
    assert contract_for_skill("suffix_est_er") is contract_for_skill("suffix_er_est")


def test_no_two_contracts_share_a_token_set() -> None:
    # Registry lint: duplicate token-sets would make contract_for_skill
    # order-of-registration dependent — a silent authoring hazard.
    seen = [frozenset(c.suffixes) for c in SUFFIX_CONTRACTS]
    assert len(seen) == len(set(seen))
