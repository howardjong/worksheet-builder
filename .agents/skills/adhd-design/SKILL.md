---
name: ADHD Worksheet Design Rules
description: This skill should be used when the user asks to "render a worksheet", "create a layout", "design a page", "add decorative elements", "apply a theme", "style the output", or when code in render/, theme/, or adapt/ is being created or modified. It provides ADHD-safe design constraints that must be enforced in all worksheet output.
version: 1.0.0
---

# ADHD Worksheet Design Rules

When generating, reviewing, or modifying any code that affects worksheet visual output, enforce ALL of these rules.

## Visual Design Rules (Hard Constraints)
- One main task per page (or clearly separated sections with visible borders)
- Generous white space — no dense text blocks
- Sans-serif font, minimum sizes by grade: K=16-18pt, G1=14-16pt, G2-3=12-14pt
- Color used sparingly and consistently: blue=directions, green=examples, yellow/amber=key words
- No patterned backgrounds — solid light backgrounds only
- High contrast — dark text (#1F2937 or darker) on light background (#FAFAFA or lighter)
- Decorative elements limited to 1-2 per page — every illustration must support the task
- Consistent layout positions: instructions always top-left, examples in shaded box below, answer spaces in predictable position
- Avatar companion placed once per page in a fixed position (e.g., bottom-right), never scattered

## Content Restructuring Rules
- Chunk content into small sections (grade-dependent: K=2-3 items, G1=3-5, G2=4-6, G3=5-8)
- Label each chunk with a micro-goal: "Part A — Find the nouns (5 questions)"
- Numbered step instructions with bold action verbs: "1) **Read** the sentence. 2) **Circle** the verb."
- Worked example immediately after instructions, before independent items
- Time estimate per section when profile.show_time_estimates is true
- Self-check boxes when profile.show_self_check_boxes is true
- Mini progress indicator per page

## Engagement Elements
- Frame as missions/levels, not exercises
- Predictable reward cadence with low-stimulation feedback
- Choice-based items where possible
- Alternate response formats when skill-appropriate (circle, match, short write, verbal)

## ABSOLUTE ANTI-PATTERNS (Never implement these)
- Dense text blocks or crowded pages
- Excessive color clutter or noisy/patterned backgrounds
- Flashing or highly animated stimuli
- Leaderboards or competitive elements
- Streak punishment ("you lost your streak!")
- Loot boxes, rarity systems, or variable-ratio reward mechanics
- Monetized cosmetics
- Complex menus or inventories that divert from learning

## When reviewing code, check:
1. Does the renderer enforce max items per chunk based on grade level?
2. Are fonts embedded and sized correctly?
3. Is the color system consistent (not ad-hoc color choices)?
4. Are decoration zones defined and respected?
5. Does the theme engine cap decorative elements at 1-2 per page?
