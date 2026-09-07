"""Learning-objective contracts for verified word transformations.

Contracts describe what a learner must do and which mechanical operations are
truthful for that objective. They contain no lesson numbers or corpus-provider
assumptions, so OCR, local curricula, and model-authored plans resolve through
the same registry.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from skill.transformation import OperationKind

DEFAULT_SINGLE_HOP_RULE = (
    "≥2 add-the-ending transformations (base + suffix → new word); this "
    "suffix forms no multi-step chain, so independent pairs ARE this "
    "lesson's manipulation form"
)
DEFAULT_MULTI_HOP_RULE = "≥1 coherent build/change chain (count steps, not words)"

DROP_E_RULE_SKILL = "drop_e_rule"
DROP_E_RULE_SUFFIXES: tuple[str, ...] = ("ed", "ing", "er", "est")
DROP_E_RULE_GOAL = "I can drop final e before adding an ending"
DROP_E_RULE_MANIPULATION = (
    "≥2 Drop-E transformations: start with a silent-e base word, remove final e, "
    "then add -ed, -ing, -er, or -est to spell the new word; base-anchored "
    "derived forms ARE this lesson's manipulation form, so do not require a "
    "one-letter or one-sound substitution chain"
)

ContractFamily = Literal[
    "letter_chain", "prefix", "suffix", "orthographic_rule", "review", "pattern_only"
]
ChainAnchoring = Literal["sequential", "base_anchored", "per_step_infer"]


class TransformationContract(BaseModel):
    """Correctness-as-data for one reusable learning objective."""

    skill_id: str
    rule_id: str
    concept_patterns: tuple[str, ...] = ()
    priority: int = 0
    family: ContractFamily
    chain_anchoring: ChainAnchoring
    allowed_prefixes: tuple[str, ...] = ()
    allowed_endings: tuple[str, ...] = ()
    permitted_recipes: tuple[tuple[OperationKind, ...], ...] = Field(min_length=1)
    goal_statement: str = Field(min_length=1)
    operation_label: str = Field(min_length=1)
    manipulation_rule_single_hop: str = DEFAULT_SINGLE_HOP_RULE
    manipulation_rule_multi_hop: str = DEFAULT_MULTI_HOP_RULE
    written_production_essential: bool = True

    @model_validator(mode="after")
    def validate_identity(self) -> TransformationContract:
        if self.rule_id != self.skill_id:
            raise ValueError("rule_id and skill_id must share one stable identity")
        return self


class SuffixContract(BaseModel):
    """Backward-compatible view used by existing suffix callers."""

    suffixes: tuple[str, ...] = Field(min_length=1)
    goal_statement: str
    manipulation_rule_single_hop: str = DEFAULT_SINGLE_HOP_RULE
    manipulation_rule_multi_hop: str = DEFAULT_MULTI_HOP_RULE

    @property
    def skill_slug(self) -> str:
        return "suffix_" + "_".join(self.suffixes)


def _generic_goal(*affixes: str, position: str = "suffix") -> str:
    joined = " and ".join(f"-{part}" if position == "suffix" else f"{part}-" for part in affixes)
    return f"I can add {joined} to words"


APPEND: tuple[OperationKind, ...] = ("append_affix",)
PREPEND: tuple[OperationKind, ...] = ("prepend_affix",)
SUBSTITUTE: tuple[OperationKind, ...] = ("substitute_grapheme",)
INSERT: tuple[OperationKind, ...] = ("insert_grapheme",)
DELETE: tuple[OperationKind, ...] = ("delete_grapheme",)
DROP_E_APPEND: tuple[OperationKind, ...] = ("drop_final_e", "append_affix")
DOUBLE_APPEND: tuple[OperationKind, ...] = ("double_final_consonant", "append_affix")
Y_TO_I_APPEND: tuple[OperationKind, ...] = ("change_y_to_i", "append_affix")


def _suffix_contract(
    skill_id: str,
    suffixes: tuple[str, ...],
    *,
    goal: str | None = None,
    patterns: tuple[str, ...] = (),
    recipes: tuple[tuple[OperationKind, ...], ...] = (APPEND,),
    family: ContractFamily = "suffix",
    anchoring: ChainAnchoring = "base_anchored",
    priority: int = 50,
    manipulation: str | None = None,
    prefixes: tuple[str, ...] = (),
) -> TransformationContract:
    return TransformationContract(
        skill_id=skill_id,
        rule_id=skill_id,
        concept_patterns=patterns,
        priority=priority,
        family=family,
        chain_anchoring=anchoring,
        allowed_endings=suffixes,
        allowed_prefixes=prefixes,
        permitted_recipes=recipes,
        goal_statement=goal or _generic_goal(*suffixes),
        operation_label="add the ending",
        manipulation_rule_single_hop=manipulation or DEFAULT_SINGLE_HOP_RULE,
        manipulation_rule_multi_hop=manipulation or DEFAULT_MULTI_HOP_RULE,
    )


def _prefix_contract(
    skill_id: str, prefixes: tuple[str, ...], patterns: tuple[str, ...]
) -> TransformationContract:
    return TransformationContract(
        skill_id=skill_id,
        rule_id=skill_id,
        concept_patterns=patterns,
        priority=55,
        family="prefix",
        chain_anchoring="base_anchored",
        allowed_prefixes=prefixes,
        permitted_recipes=(PREPEND,),
        goal_statement=_generic_goal(*prefixes, position="prefix"),
        operation_label="add the beginning word part",
    )


_GENERIC_EDIT_RECIPES = (SUBSTITUTE, INSERT, DELETE, PREPEND, APPEND)

TRANSFORMATION_CONTRACTS: tuple[TransformationContract, ...] = (
    TransformationContract(
        skill_id="letter_chain",
        rule_id="letter_chain",
        family="letter_chain",
        chain_anchoring="sequential",
        permitted_recipes=(SUBSTITUTE, INSERT, DELETE),
        goal_statement="I can build words by making one verified change",
        operation_label="make the verified change",
    ),
    _suffix_contract(
        "suffix_s_es",
        ("s", "es"),
        patterns=(r"\bsuffix(?:es)?\b.*-s\s*[,/]\s*-es",),
    ),
    _suffix_contract(
        "suffix_er_est",
        ("er", "est"),
        goal="I can add -er and -est to compare things",
        patterns=(r"^\s*-er\s*[,/]\s*-est\s*$",),
    ),
    _suffix_contract("suffix_ly", ("ly",), patterns=(r"^\s*-ly\s*$",)),
    _suffix_contract("suffix_ed", ("ed",), patterns=(r"^\s*-ed\s*$",)),
    _suffix_contract("suffix_es", ("es",), patterns=(r"^\s*-es\s*$",)),
    _suffix_contract(
        "suffix_less_ful",
        ("less", "ful"),
        patterns=(r"^\s*-less\s*[,/]\s*-ful\s*$",),
    ),
    _suffix_contract(
        "suffix_ness",
        ("ness",),
        patterns=(r"^\s*-ness\s*$",),
        recipes=(Y_TO_I_APPEND, APPEND),
    ),
    _prefix_contract("prefix_un", ("un",), (r"\bprefix(?:es)?\b.*\bun-", r"^\s*un-\s*$")),
    _prefix_contract("prefix_pre_re", ("pre", "re"), (r"^\s*pre-\s*[,/]\s*re-\s*$",)),
    _prefix_contract("prefix_dis", ("dis",), (r"^\s*dis-\s*$",)),
    _prefix_contract(
        "prefix_bi_tri_uni",
        ("bi", "tri", "uni"),
        (r"^\s*bi-\s*[,/]\s*tri-\s*[,/]\s*uni-\s*$",),
    ),
    _suffix_contract(
        "suffix_er_or_ist",
        ("er", "or", "ist"),
        patterns=(r"^\s*-er\s*[,/]\s*-or\s*[,/]\s*-ist\s*$",),
    ),
    _suffix_contract("suffix_ish", ("ish",), patterns=(r"^\s*-ish\s*$",)),
    _suffix_contract("suffix_y", ("y",), patterns=(r"^\s*-y\s*$",)),
    _suffix_contract("suffix_ment", ("ment",), patterns=(r"^\s*-ment\s*$",)),
    _suffix_contract(
        "suffix_able_ible",
        ("able", "ible"),
        patterns=(r"^\s*-able\s*[,/]\s*-ible\s*$",),
    ),
    _suffix_contract(
        "word_part_sion_tion",
        ("sion", "tion"),
        patterns=(r"^\s*-sion\s*[,/]\s*-tion\s*$",),
        recipes=_GENERIC_EDIT_RECIPES,
        family="pattern_only",
        anchoring="sequential",
        prefixes=("re", "di"),
        goal="I can read and spell words with -sion and -tion",
    ),
    _suffix_contract(
        "word_part_ture",
        ("ture", "s"),
        patterns=(r"^\s*-ture\s*$",),
        recipes=_GENERIC_EDIT_RECIPES,
        family="pattern_only",
        anchoring="sequential",
        goal="I can read and spell words with -ture",
    ),
    TransformationContract(
        skill_id="doubling_ed_ing",
        rule_id="doubling_ed_ing",
        concept_patterns=(r"\bdoubling rule\b.*-ed\s*[,/]\s*-ing",),
        priority=100,
        family="orthographic_rule",
        chain_anchoring="base_anchored",
        allowed_endings=("ed", "ing"),
        permitted_recipes=(DOUBLE_APPEND,),
        goal_statement="I can double the final consonant before adding -ed or -ing",
        operation_label="double the final consonant and add the ending",
        manipulation_rule_single_hop="≥2 verified consonant-doubling transformations",
        manipulation_rule_multi_hop="≥2 verified consonant-doubling transformations",
    ),
    TransformationContract(
        skill_id="doubling_er_est",
        rule_id="doubling_er_est",
        concept_patterns=(r"\bdoubling rule\b.*-er\s*[,/]\s*-est",),
        priority=100,
        family="orthographic_rule",
        chain_anchoring="base_anchored",
        allowed_endings=("er", "est"),
        permitted_recipes=(DOUBLE_APPEND,),
        goal_statement="I can double the final consonant before adding -er or -est",
        operation_label="double the final consonant and add the ending",
        manipulation_rule_single_hop="≥2 verified consonant-doubling transformations",
        manipulation_rule_multi_hop="≥2 verified consonant-doubling transformations",
    ),
    TransformationContract(
        skill_id=DROP_E_RULE_SKILL,
        rule_id=DROP_E_RULE_SKILL,
        concept_patterns=(r"\bdrop\s*-?e\s+rule\b", r"\bdrop\s*-?e\b"),
        priority=110,
        family="orthographic_rule",
        chain_anchoring="base_anchored",
        allowed_endings=DROP_E_RULE_SUFFIXES,
        permitted_recipes=(DROP_E_APPEND,),
        goal_statement=DROP_E_RULE_GOAL,
        operation_label="drop final e and add the ending",
        manipulation_rule_single_hop=DROP_E_RULE_MANIPULATION,
        manipulation_rule_multi_hop=DROP_E_RULE_MANIPULATION,
    ),
    TransformationContract(
        skill_id="y_to_i_rule",
        rule_id="y_to_i_rule",
        concept_patterns=(r"\by\s+to\s+i\s+rule\b",),
        priority=110,
        family="orthographic_rule",
        chain_anchoring="base_anchored",
        allowed_endings=("es", "ed", "er", "est", "ness"),
        permitted_recipes=(Y_TO_I_APPEND,),
        goal_statement="I can change final y to i before adding an ending",
        operation_label="change final y to i and add the ending",
        manipulation_rule_single_hop="≥2 verified Y-to-I transformations",
        manipulation_rule_multi_hop="≥2 verified Y-to-I transformations",
    ),
    TransformationContract(
        skill_id="affix_review",
        rule_id="affix_review",
        concept_patterns=(r"^\s*affixes review(?:\s+\d+)?\s*$",),
        priority=90,
        family="review",
        chain_anchoring="per_step_infer",
        allowed_prefixes=("un", "pre", "re", "dis", "bi", "tri", "uni"),
        allowed_endings=(
            "s",
            "es",
            "er",
            "est",
            "ly",
            "less",
            "ful",
            "ness",
            "ment",
            "ish",
            "y",
            "able",
            "ible",
        ),
        permitted_recipes=(PREPEND, APPEND, DROP_E_APPEND, DOUBLE_APPEND, Y_TO_I_APPEND),
        goal_statement="I can use word parts to build and spell words",
        operation_label="apply the verified word-part change",
    ),
)


def _registry_by_skill() -> dict[str, TransformationContract]:
    return {contract.skill_id: contract for contract in TRANSFORMATION_CONTRACTS}


def contract_for_skill_id(skill_id: str) -> TransformationContract | None:
    """Return an exact contract; unknown objectives never guess."""
    return _registry_by_skill().get(skill_id)


def match_transformation_contract(concept_text: str) -> TransformationContract | None:
    """Resolve concept text deterministically by priority and pattern length."""
    normalized = " ".join(concept_text.casefold().replace("\n", " ").split())
    matches: list[tuple[int, int, TransformationContract]] = []
    for contract in TRANSFORMATION_CONTRACTS:
        for pattern in contract.concept_patterns:
            if re.search(pattern, normalized):
                matches.append((contract.priority, len(pattern), contract))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], -item[1], item[2].skill_id))
    return matches[0][2]


SUFFIX_CONTRACTS: tuple[SuffixContract, ...] = tuple(
    SuffixContract(
        suffixes=contract.allowed_endings,
        goal_statement=contract.goal_statement,
        manipulation_rule_single_hop=contract.manipulation_rule_single_hop,
        manipulation_rule_multi_hop=contract.manipulation_rule_multi_hop,
    )
    for contract in TRANSFORMATION_CONTRACTS
    if contract.family == "suffix" and contract.skill_id.startswith("suffix_")
)


def known_suffix_tokens() -> frozenset[str]:
    return frozenset(token for contract in SUFFIX_CONTRACTS for token in contract.suffixes)


def contract_for_skill(specific_skill: str) -> SuffixContract | None:
    """Backward-compatible suffix view, including order-insensitive lookup."""
    if not specific_skill.startswith("suffix_"):
        return None
    token_set = frozenset(specific_skill.removeprefix("suffix_").split("_"))
    for contract in SUFFIX_CONTRACTS:
        if frozenset(contract.suffixes) == token_set:
            return contract
    return None
