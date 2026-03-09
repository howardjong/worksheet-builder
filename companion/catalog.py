"""Unlockable item catalog for avatar customization — slot-based overlay system."""

from __future__ import annotations

from pydantic import BaseModel


class CatalogItem(BaseModel):
    """A single item in the avatar customization catalog."""

    item_id: str
    name: str
    slot: str  # "shirt" | "pants" | "shoes" | "hat" | "backpack" | "face"
    cost: int  # tokens required
    milestone_only: bool = False  # only unlockable via milestones


VALID_SLOTS = {"shirt", "pants", "shoes", "hat", "backpack", "face"}


def _item(
    item_id: str, name: str, slot: str, cost: int,
    milestone_only: bool = False,
) -> CatalogItem:
    return CatalogItem(
        item_id=item_id, name=name, slot=slot,
        cost=cost, milestone_only=milestone_only,
    )


# Phase 1 catalog — 7 items for slot-based overlay system
CATALOG: list[CatalogItem] = [
    _item("white_sneakers", "White Sneakers", "shoes", 5),
    _item("red_hoodie", "Red Hoodie", "shirt", 10),
    _item("blue_jeans", "Blue Jeans", "pants", 10),
    _item("green_backpack", "Green Backpack", "backpack", 5),
    _item("star_shades", "Star Shades", "face", 5),
    _item("wizard_hat", "Wizard Hat", "hat", 15),
    _item("gold_crown", "Gold Crown", "hat", 0, milestone_only=True),
]

_CATALOG_INDEX: dict[str, CatalogItem] = {item.item_id: item for item in CATALOG}


def get_item(item_id: str) -> CatalogItem | None:
    """Look up a catalog item by ID."""
    return _CATALOG_INDEX.get(item_id)


def get_items_by_slot(slot: str) -> list[CatalogItem]:
    """Return all catalog items for a given slot."""
    return [item for item in CATALOG if item.slot == slot]


def get_affordable_items(tokens: int) -> list[CatalogItem]:
    """Return items the child can currently afford."""
    results = []
    for item in CATALOG:
        if item.milestone_only:
            continue
        if item.cost > tokens:
            continue
        results.append(item)
    return results


def get_milestone_items() -> list[CatalogItem]:
    """Return items that are only unlockable via milestones."""
    return [item for item in CATALOG if item.milestone_only]
