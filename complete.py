"""CLI entry point: mark worksheet completion, award tokens, manage profile."""

from __future__ import annotations

import json
import logging

import click

from companion.caregiver import adjust_accommodations, view_progress
from companion.profile import ensure_companion_fields
from companion.rewards import award_completion, purchase_item
from companion.schema import load_profile, save_profile

logger = logging.getLogger(__name__)


@click.command()
@click.option("--profile", "profile_path", required=True, help="Path to learner profile YAML")
@click.option("--lesson", type=int, default=None, help="Lesson number to mark complete")
@click.option("--progress", "show_progress", is_flag=True, help="View progress report")
@click.option("--buy", "buy_item", default=None, help="Purchase a catalog item by ID")
@click.option("--set-chunking", default=None, help="Set chunking level (small/medium/large)")
def complete(
    profile_path: str,
    lesson: int | None,
    show_progress: bool,
    buy_item: str | None,
    set_chunking: str | None,
) -> None:
    """Mark worksheet completion, manage rewards, and adjust accommodations."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    profile = load_profile(profile_path)
    profile = ensure_companion_fields(profile)

    if lesson is not None:
        result = award_completion(profile, lesson)
        logger.info(result.message)
        if result.is_milestone:
            logger.info(f"  Milestone {result.milestone_number}!")
            for item_id in result.items_unlocked:
                logger.info(f"  Unlocked: {item_id}")
        logger.info(f"  Points: {result.tokens_total}")
        save_profile(profile, profile_path)

    elif show_progress:
        report = view_progress(profile)
        click.echo(json.dumps(report.model_dump(), indent=2))

    elif buy_item:
        purchase = purchase_item(profile, buy_item)
        logger.info(purchase.message)
        if purchase.success:
            save_profile(profile, profile_path)

    elif set_chunking:
        profile = adjust_accommodations(profile, chunking_level=set_chunking)
        save_profile(profile, profile_path)
        logger.info(f"Chunking level set to: {set_chunking}")

    else:
        click.echo("Use --lesson, --progress, --buy, or --set-chunking. See --help.")


if __name__ == "__main__":
    complete()
