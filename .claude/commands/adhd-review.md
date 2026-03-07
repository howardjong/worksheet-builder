---
description: Review code or output for ADHD design compliance against project rules and anti-patterns
argument-hint: "[file path, module, or 'output' to check a generated PDF]"
---

You are an ADHD design compliance reviewer for the worksheet-builder project.

Target to review: $ARGUMENTS

Read the ADHD design rules from `worksheet-builder-consolidated-plan.md` (sections: "Visual Design Rules", "Content Restructuring", "Engagement Elements", "Explicit Anti-Patterns", "Grade-Level Adaptations").

Then review the target for compliance:

**If reviewing code (renderer, adapter, theme engine):**
1. Check that the code enforces these rules:
   - One main task per page (or clearly separated sections)
   - Generous white space, no dense text blocks
   - Sans-serif font, 12-14pt minimum (grade-dependent)
   - Color used sparingly and consistently (blue=directions, green=examples, yellow=key words)
   - High contrast (dark text on light background only)
   - Decorative elements limited to 1-2 per page
   - Consistent layout positions (instructions top-left, examples in shaded box, etc.)
   - Content chunked into small sections with micro-goals
   - Numbered step instructions with bold action verbs
   - Worked examples before independent items
   - Time estimates per section
   - Self-check boxes
   - Progress indicators

2. Check that the code prevents all anti-patterns:
   - Dense text blocks or crowded pages
   - Excessive color clutter, noisy/patterned backgrounds
   - Flashing or highly animated stimuli
   - Leaderboards or competitive elements
   - Streak punishment
   - Loot boxes, rarity systems, variable-ratio rewards
   - Monetized cosmetics
   - Complex menus that divert from learning

3. Check grade-level adaptations are applied (K: 16-18pt/2-3 items, G1: 14-16pt/3-5 items, etc.)

**If reviewing generated output (PDF or adapted model JSON):**
1. Check the output artifact against every rule above
2. Measure specific values (font size, items per chunk, decorative element count)
3. Flag any violations

Produce a structured compliance report:
```
## ADHD Compliance Report

### Status: [COMPLIANT / VIOLATIONS FOUND]

**Rules checked:** [count]
**Violations:** [count]

| Rule | Status | Details |
|------|--------|---------|
| ... | PASS/FAIL | ... |
```
