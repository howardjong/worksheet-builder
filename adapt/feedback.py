"""Learning-goal statements and the print-only feedback panel builder."""

from __future__ import annotations

from adapt.schema import FeedbackPanel
from skill.contract import contract_for_skill, contract_for_skill_id

# Next-step hint for the grown-up, printed on the package's last sheet.
# Thresholds: Betts reading levels + UFLI-aligned practice (spec 2026-07-10).
DECISION_HINT = (
    "Mostly correct and comfortable without help: consider moving on. "
    "Some errors or some help: practice again with fresh words. "
    "Many errors or lots of help: review an easier activity with the teacher."
)


def _display_skill(specific_skill: str) -> str:
    """Slug → child-facing text: underscores become spaces only in multi-letter
    slugs ("cvc_blending" → "cvc blending"); single-letter patterns like "a_e"
    are real phonics notation and stay verbatim."""
    segments = specific_skill.split("_")
    if len(segments) > 1 and all(len(s) == 1 for s in segments):
        return specific_skill  # "a_e", "o_e"-style split-vowel notation
    return specific_skill.replace("_", " ")


def learning_goal_statement(domain: str, specific_skill: str) -> str:
    """Child-friendly 'I can...' goal shown in page banners and feedback strips."""
    transformation_contract = contract_for_skill_id(specific_skill)
    if transformation_contract is not None:
        return transformation_contract.goal_statement
    if specific_skill.startswith("suffix_"):
        contract = contract_for_skill(specific_skill)
        if contract is not None:
            return contract.goal_statement
        # Unregistered combined slug: keep the generic joiner as a fallback.
        endings = specific_skill.removeprefix("suffix_").split("_")
        joined = " and ".join(f"-{e}" for e in endings)
        return f"I can add {joined} to words"
    if domain == "phonics":
        return f"I can read words with the {_display_skill(specific_skill)} pattern"
    if domain == "fluency":
        return "I can read the story smoothly"
    return f"I can practice {domain.replace('_', ' ')} skills"


def build_feedback_panel(domain: str, specific_skill: str) -> FeedbackPanel:
    return FeedbackPanel(goal_statement=learning_goal_statement(domain, specific_skill))
