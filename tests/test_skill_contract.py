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


def test_taxonomy_token_set_is_derived_from_the_registry() -> None:
    from skill.taxonomy import MORPHOLOGY_SUFFIXES

    assert MORPHOLOGY_SUFFIXES == known_suffix_tokens()
    assert MORPHOLOGY_SUFFIXES is not known_suffix_tokens()  # derived, not aliased per-call


def test_goal_statement_comes_from_contract_when_registered() -> None:
    from adapt.feedback import learning_goal_statement

    # Both must match the contract entries verbatim (byte-identity bar).
    assert (
        learning_goal_statement("phonics", "suffix_er_est")
        == "I can add -er and -est to compare things"
    )
    assert learning_goal_statement("phonics", "suffix_ly") == "I can add -ly to words"


def test_goal_statement_falls_back_for_unregistered_suffix_slugs() -> None:
    from adapt.feedback import learning_goal_statement

    # A combined slug with no contract keeps the generic joiner behavior.
    assert learning_goal_statement("phonics", "suffix_ed_es") == "I can add -ed and -es to words"


def test_manipulation_cell_wording_comes_from_contract() -> None:
    # tests/objective_corpus_fixture.py is a corpus-lookup helper, not a
    # LiteracySkillModel builder, so build the skill the way
    # tests/test_objective_ledger.py::_chain_skill does (construction copied
    # verbatim) and read the manipulation cell back out of the built ledger.
    from adapt.objective_ledger import build_objective_ledger
    from skill.contract import contract_for_skill
    from skill.schema import LiteracySkillModel, SourceItem

    skill_model = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="suffix_ly",
        learning_objectives=["objective"],
        target_words=["quickly"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_chain", content=c, source_region_index=i)
            for i, c in enumerate(["quick → quickly", "light → lightly", "deep → deeply"])
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )
    ledger = build_objective_ledger(skill_model, corpus_lookup=lambda n: None)
    cell = next(c for c in ledger.objectives if c.objective_id == "obj_manipulation")
    contract = contract_for_skill("suffix_ly")
    assert contract is not None
    assert cell.sufficiency_rule == contract.manipulation_rule_single_hop
