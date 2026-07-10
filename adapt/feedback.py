"""Learning-goal statements and the print-only feedback panel builder."""

from __future__ import annotations

from adapt.schema import FeedbackPanel

# Next-step hint for the grown-up, printed on the package's last sheet.
# Thresholds: Betts reading levels + UFLI-aligned practice (spec 2026-07-10).
DECISION_HINT = (
    "Mostly green + 9 of 10 right + no help: move on. "
    "Mixed or some help: practice again with fresh words. "
    "Mostly red or lots of help: step back one lesson."
)


def learning_goal_statement(domain: str, specific_skill: str) -> str:
    """Child-friendly 'I can...' goal shown in page banners and feedback strips."""
    if domain == "phonics":
        return f"I can read words with the {specific_skill} pattern"
    if domain == "fluency":
        return "I can read the story smoothly"
    return f"I can practice {domain.replace('_', ' ')} skills"


def build_feedback_panel(domain: str, specific_skill: str) -> FeedbackPanel:
    return FeedbackPanel(goal_statement=learning_goal_statement(domain, specific_skill))
