"""Skill contracts: per-suffix-family correctness facts as data.

Centralizes what was scattered across taxonomy (classification tokens),
adapt/feedback.py (goal text), and adapt/objective_ledger.py (judge
sufficiency wording). The pipeline stays generic machinery; adding a new
suffix family is adding one SuffixContract entry here — nothing else.

Dependency rule: this module imports nothing from skill/taxonomy.py;
taxonomy derives its token set FROM this registry.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Default judge sufficiency wording, the single source of these strings.
# Suffix families inherit them via SuffixContract defaults; the objective
# ledger's non-suffix / unregistered-slug fallback imports them too, so the
# literals never get retyped elsewhere.
DEFAULT_SINGLE_HOP_RULE = (
    "≥2 add-the-ending transformations (base + suffix → new word); this "
    "suffix forms no multi-step chain, so independent pairs ARE this "
    "lesson's manipulation form"
)
DEFAULT_MULTI_HOP_RULE = "≥1 coherent build/change chain (count steps, not words)"


class SuffixContract(BaseModel):
    """Correctness facts for one morphological suffix family."""

    suffixes: tuple[str, ...] = Field(min_length=1, description="Suffix tokens, no leading hyphen")
    goal_statement: str = Field(description="Child-facing 'I can...' banner text")
    manipulation_rule_single_hop: str = Field(default=DEFAULT_SINGLE_HOP_RULE)
    manipulation_rule_multi_hop: str = Field(default=DEFAULT_MULTI_HOP_RULE)

    @property
    def skill_slug(self) -> str:
        return "suffix_" + "_".join(self.suffixes)


def _generic_goal(*suffixes: str) -> str:
    joined = " and ".join(f"-{s}" for s in suffixes)
    return f"I can add {joined} to words"


SUFFIX_CONTRACTS: tuple[SuffixContract, ...] = (
    SuffixContract(
        suffixes=("er", "est"),
        goal_statement="I can add -er and -est to compare things",
    ),
    SuffixContract(suffixes=("ly",), goal_statement=_generic_goal("ly")),
    SuffixContract(suffixes=("ed",), goal_statement=_generic_goal("ed")),
    SuffixContract(suffixes=("es",), goal_statement=_generic_goal("es")),
    # UFLI lesson 102 — first family added post-registry; the H1a proof.
    SuffixContract(suffixes=("less", "ful"), goal_statement=_generic_goal("less", "ful")),
    # UFLI lesson 124.
    SuffixContract(suffixes=("ness",), goal_statement=_generic_goal("ness")),
)


def known_suffix_tokens() -> frozenset[str]:
    """Union of all registered suffix tokens — taxonomy's morphology set."""
    return frozenset(t for c in SUFFIX_CONTRACTS for t in c.suffixes)


def contract_for_skill(specific_skill: str) -> SuffixContract | None:
    """Look up the contract for a suffix skill slug, order-insensitive."""
    if not specific_skill.startswith("suffix_"):
        return None
    token_set = frozenset(specific_skill.removeprefix("suffix_").split("_"))
    for contract in SUFFIX_CONTRACTS:
        if frozenset(contract.suffixes) == token_set:
            return contract
    return None
