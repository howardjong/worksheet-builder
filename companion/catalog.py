"""Unlockable item catalog for avatar customization."""

from __future__ import annotations

from pydantic import BaseModel


class CatalogItem(BaseModel):
    """A single item in the avatar customization catalog."""

    item_id: str
    name: str
    category: str  # "clothing" | "accessories" | "hats" | "expressions"
    cost: int  # tokens required
    theme: str  # which theme this belongs to ("any" for universal)
    milestone_only: bool = False  # only unlockable via milestones


def _item(
    item_id: str, name: str, category: str, cost: int,
    theme: str, milestone_only: bool = False,
) -> CatalogItem:
    return CatalogItem(
        item_id=item_id, name=name, category=category,
        cost=cost, theme=theme, milestone_only=milestone_only,
    )


# Master catalog — items available across all themes
CATALOG: list[CatalogItem] = [
    # Universal items
    _item("star_badge", "Star Badge", "accessories", 5, "any"),
    _item("rainbow_cape", "Rainbow Cape", "clothing", 10, "any"),
    _item("crown", "Golden Crown", "hats", 15, "any"),
    _item("sunglasses", "Cool Sunglasses", "accessories", 5, "any"),
    _item("happy_face", "Happy Expression", "expressions", 0, "any"),
    # Space theme items
    _item("space_helmet", "Space Helmet", "hats", 10, "space"),
    _item("jetpack", "Jetpack", "accessories", 15, "space"),
    _item("space_suit", "Space Suit", "clothing", 10, "space"),
    _item("astronaut_gold", "Gold Astronaut Suit", "clothing", 0, "space", True),
    # Underwater theme items
    _item("diving_mask", "Diving Mask", "accessories", 10, "underwater"),
    _item("flippers", "Flippers", "accessories", 5, "underwater"),
    _item("coral_crown", "Coral Crown", "hats", 15, "underwater"),
    # Dinosaur theme items
    _item("dino_hat", "Dino Hat", "hats", 10, "dinosaur"),
    _item("fossil_necklace", "Fossil Necklace", "accessories", 10, "dinosaur"),
    _item("explorer_vest", "Explorer Vest", "clothing", 10, "dinosaur"),
]

_CATALOG_INDEX: dict[str, CatalogItem] = {item.item_id: item for item in CATALOG}


def get_item(item_id: str) -> CatalogItem | None:
    """Look up a catalog item by ID."""
    return _CATALOG_INDEX.get(item_id)


def get_affordable_items(tokens: int, theme: str | None = None) -> list[CatalogItem]:
    """Return items the child can currently afford."""
    results = []
    for item in CATALOG:
        if item.milestone_only:
            continue
        if item.cost > tokens:
            continue
        if theme and item.theme not in (theme, "any"):
            continue
        results.append(item)
    return results


def get_milestone_items() -> list[CatalogItem]:
    """Return items that are only unlockable via milestones."""
    return [item for item in CATALOG if item.milestone_only]
