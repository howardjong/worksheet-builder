"""CLI entry point: mark worksheet completion, award tokens, manage profile."""

from __future__ import annotations

import json
import logging

# Load .env before anything else
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import click

from companion.caregiver import adjust_accommodations, view_progress
from companion.profile import ensure_companion_fields
from companion.rewards import award_completion, equip_item, purchase_item, unequip_item
from companion.schema import LearnerProfile, load_profile, save_profile

logger = logging.getLogger(__name__)


@click.command()
@click.option("--profile", "profile_path", required=True, help="Path to learner profile YAML")
@click.option("--lesson", type=int, default=None, help="Lesson number to mark complete")
@click.option("--progress", "show_progress", is_flag=True, help="View progress report")
@click.option("--buy", "buy_item", default=None, help="Purchase a catalog item by ID")
@click.option("--equip", "equip_id", default=None, help="Equip an unlocked item by ID")
@click.option("--unequip", "unequip_id", default=None, help="Unequip an item by ID")
@click.option("--catalog", "show_catalog", is_flag=True, help="List available items")
@click.option("--avatar", "show_avatar", is_flag=True, help="Compose and display current avatar")
@click.option(
    "--generate-overlays", "gen_overlays", is_flag=True,
    help="Generate all overlay PNGs via AI",
)
@click.option("--set-chunking", default=None, help="Set chunking level (small/medium/large)")
def complete(
    profile_path: str,
    lesson: int | None,
    show_progress: bool,
    buy_item: str | None,
    equip_id: str | None,
    unequip_id: str | None,
    show_catalog: bool,
    show_avatar: bool,
    gen_overlays: bool,
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

    elif equip_id:
        equip_result = equip_item(profile, equip_id)
        logger.info(equip_result.message)
        if equip_result.success:
            save_profile(profile, profile_path)

    elif unequip_id:
        unequip_result = unequip_item(profile, unequip_id)
        logger.info(unequip_result.message)
        if unequip_result.success:
            save_profile(profile, profile_path)

    elif show_catalog:
        _display_catalog(profile)

    elif show_avatar:
        from companion.avatar import compose_avatar
        path = compose_avatar(profile, size="profile")
        if path:
            click.echo(f"Avatar composed: {path}")
        else:
            click.echo("Could not compose avatar.")

    elif gen_overlays:
        from companion.generate_overlays import generate_all_items
        results = generate_all_items()
        for item_id, path in results.items():
            status = f"OK: {path}" if path else "FAILED"
            click.echo(f"  {item_id}: {status}")

    elif set_chunking:
        profile = adjust_accommodations(profile, chunking_level=set_chunking)
        save_profile(profile, profile_path)
        logger.info(f"Chunking level set to: {set_chunking}")

    else:
        click.echo(
            "Use --lesson, --progress, --buy, --equip, --unequip,"
            " --catalog, --avatar, --generate-overlays,"
            " or --set-chunking. See --help."
        )


def _display_catalog(profile: LearnerProfile) -> None:
    """Display the catalog with owned/equipped status."""
    from companion.catalog import CATALOG

    click.echo("\n  Avatar Item Catalog")
    click.echo("  " + "-" * 50)
    for item in CATALOG:
        avatar = getattr(profile, "avatar", None)
        owned = item.item_id in (avatar.unlocked_items if avatar else [])
        equipped = item.item_id in (
            avatar.equipped_items.values() if avatar else {}
        )
        status = ""
        if equipped:
            status = " [EQUIPPED]"
        elif owned:
            status = " [OWNED]"
        elif item.milestone_only:
            status = " (milestone only)"

        cost_str = f"{item.cost} pts" if not item.milestone_only else "milestone"
        click.echo(f"  {item.item_id:<20} {item.name:<20} {item.slot:<10} {cost_str:<12}{status}")
    click.echo()


if __name__ == "__main__":
    complete()
