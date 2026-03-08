"""Token economy and reward system — predictable, effort-based rewards."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from companion.catalog import get_item, get_milestone_items
from companion.schema import CompletionRecord, LearnerProfile, Progress

TOKENS_PER_WORKSHEET = 10
MILESTONE_INTERVAL = 5  # every 5th worksheet
MILESTONE_BONUS = 25


class RewardResult(BaseModel):
    """Result of awarding completion tokens."""

    tokens_earned: int
    tokens_total: int
    is_milestone: bool = False
    milestone_number: int = 0
    milestone_bonus: int = 0
    items_unlocked: list[str] = Field(default_factory=list)
    message: str = ""


class PurchaseResult(BaseModel):
    """Result of purchasing a catalog item."""

    success: bool
    item_id: str
    tokens_remaining: int
    message: str


def award_completion(
    profile: LearnerProfile,
    lesson: int,
    skill_domain: str = "",
) -> RewardResult:
    """Award tokens for completing a worksheet.

    Rules (ADHD-safe):
    - Tokens awarded for completion (effort), not accuracy
    - Predictable: always TOKENS_PER_WORKSHEET per worksheet
    - Milestones every MILESTONE_INTERVAL worksheets
    - Milestone items are auto-unlocked, not purchased
    """
    if profile.progress is None:
        profile.progress = Progress()

    progress = profile.progress

    # Award base tokens
    tokens = TOKENS_PER_WORKSHEET
    progress.worksheets_completed += 1
    progress.current_lesson = lesson

    # Check for milestone
    is_milestone = progress.worksheets_completed % MILESTONE_INTERVAL == 0
    milestone_number = progress.worksheets_completed // MILESTONE_INTERVAL
    milestone_bonus = 0
    items_unlocked: list[str] = []

    if is_milestone:
        milestone_bonus = MILESTONE_BONUS
        tokens += milestone_bonus

        # Record milestone
        if milestone_number not in progress.milestones_reached:
            progress.milestones_reached.append(milestone_number)

        # Auto-unlock milestone items
        milestone_items = get_milestone_items()
        if milestone_items and profile.avatar:
            # Unlock next milestone item not yet unlocked
            for m_item in milestone_items:
                if m_item.item_id not in profile.avatar.unlocked_items:
                    profile.avatar.unlocked_items.append(m_item.item_id)
                    items_unlocked.append(m_item.item_id)
                    break  # one per milestone

    # Update token balance
    progress.tokens_available += tokens
    progress.tokens_lifetime += tokens

    # Record completion
    progress.completion_history.append(
        CompletionRecord(
            lesson=lesson,
            timestamp=datetime.now(UTC).isoformat(),
            tokens_earned=tokens,
            skill_domain=skill_domain,
        )
    )

    # Build message
    if is_milestone:
        message = (
            f"You did it! You earned {tokens} points! "
            f"Milestone {milestone_number} reached!"
        )
    else:
        message = f"You did it! You earned {tokens} points!"

    return RewardResult(
        tokens_earned=tokens,
        tokens_total=progress.tokens_available,
        is_milestone=is_milestone,
        milestone_number=milestone_number,
        milestone_bonus=milestone_bonus,
        items_unlocked=items_unlocked,
        message=message,
    )


def purchase_item(
    profile: LearnerProfile,
    item_id: str,
) -> PurchaseResult:
    """Purchase a catalog item with tokens."""
    if profile.progress is None:
        return PurchaseResult(
            success=False, item_id=item_id, tokens_remaining=0,
            message="No progress data found.",
        )

    if profile.avatar is None:
        return PurchaseResult(
            success=False, item_id=item_id, tokens_remaining=profile.progress.tokens_available,
            message="No avatar configured.",
        )

    item = get_item(item_id)
    if item is None:
        return PurchaseResult(
            success=False, item_id=item_id, tokens_remaining=profile.progress.tokens_available,
            message=f"Item '{item_id}' not found in catalog.",
        )

    if item.milestone_only:
        return PurchaseResult(
            success=False, item_id=item_id, tokens_remaining=profile.progress.tokens_available,
            message=f"'{item.name}' can only be earned through milestones.",
        )

    if item_id in profile.avatar.unlocked_items:
        return PurchaseResult(
            success=False, item_id=item_id, tokens_remaining=profile.progress.tokens_available,
            message=f"You already have '{item.name}'!",
        )

    if profile.progress.tokens_available < item.cost:
        return PurchaseResult(
            success=False, item_id=item_id, tokens_remaining=profile.progress.tokens_available,
            message=(
                f"Not enough points for '{item.name}' "
                f"(need {item.cost}, have {profile.progress.tokens_available})."
            ),
        )

    # Purchase!
    profile.progress.tokens_available -= item.cost
    profile.avatar.unlocked_items.append(item_id)

    return PurchaseResult(
        success=True, item_id=item_id, tokens_remaining=profile.progress.tokens_available,
        message=f"You got '{item.name}'!",
    )


def equip_item(profile: LearnerProfile, item_id: str) -> bool:
    """Equip an unlocked item on the avatar."""
    if profile.avatar is None:
        return False
    if item_id not in profile.avatar.unlocked_items:
        return False
    if item_id not in profile.avatar.equipped_items:
        profile.avatar.equipped_items.append(item_id)
    return True


def unequip_item(profile: LearnerProfile, item_id: str) -> bool:
    """Unequip an item from the avatar."""
    if profile.avatar is None:
        return False
    if item_id in profile.avatar.equipped_items:
        profile.avatar.equipped_items.remove(item_id)
        return True
    return False
