---
name: Avatar & Reward System Design
description: This skill should be used when the user asks to "create avatar", "add items", "build rewards", "implement tokens", "customize character", "unlock items", "design catalog", or when code in companion/ is being created or modified. It enforces ADHD-safe reward mechanics and avatar system constraints.
version: 1.0.0
---

# Avatar & Reward System Design

The companion layer provides engagement through progressive avatar customization. All reward mechanics must be ADHD-safe.

## Token Economy Rules
- **Tokens per worksheet:** fixed amount (e.g., 10 tokens), always the same
- **Milestone bonus:** every 5th/10th worksheet, fixed bonus (e.g., 25 tokens)
- **Predictable:** child always knows exactly what they'll earn before starting
- **No variable rewards:** never randomize token amounts or item drops
- **No penalties:** missing a day, skipping items, or getting answers wrong never costs tokens

## Item Catalog Design
- **Cosmetic only:** items change appearance, not gameplay or learning
- **Categories:** clothing, accessories, expressions/poses, theme-specific items
- **Pricing:** transparent, fixed token costs per item
- **No rarity tiers:** no "common/rare/legendary" distinctions
- **No limited-time items:** everything remains available forever
- **Sufficient depth:** ~15-20 items for MVP across 3 themes, enough for ~50 worksheets

## Avatar Composition
- **Layered rendering:** base character → body → clothing → accessories → hat (strict z-order)
- **Asset format:** PNG or SVG with transparency
- **Two render sizes:** "companion" (~150px for worksheets) and "profile" (~400px for companion app)
- **Visual style:** clean, flat-color illustration matching ADHD-friendly worksheet aesthetic
- **Color tinting:** base colors applied to character, customizable per profile

## Customization UX Constraints (ADHD-specific)
- **Gated to break points:** customization ONLY accessible before or after a work session, never during
- **Quick interactions:** target <2 minutes per customization session
- **Simple interface:** tap-to-equip, not drag-and-drop or complex menus
- **Auto-transition:** after customization, prompt "Ready for the next worksheet?"
- **No browsing rabbit holes:** show only affordable items + next unlock, not full catalog

## Catalog YAML Structure
```yaml
# theme/themes/space/catalog.yaml
items:
  - id: space_helmet
    name: Space Helmet
    category: hat
    cost: 15
    asset: hats/space_helmet.svg
    unlock_condition: null  # purchasable anytime
  - id: jetpack
    name: Jetpack
    category: accessory
    cost: 0
    asset: accessories/jetpack.svg
    unlock_condition: milestone_5  # free at milestone, not purchasable
```

## When implementing companion code:
1. Never introduce randomness in rewards
2. Never gate learning content behind token purchases
3. Keep the catalog data-driven (YAML), not hardcoded
4. Profile must persist all state (equipped, unlocked, tokens, history)
5. Operational signals (time-on-task, skip rate) inform accommodations, never affect rewards
