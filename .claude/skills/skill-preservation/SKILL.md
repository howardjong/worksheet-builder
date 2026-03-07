---
name: Literacy Skill Preservation
description: This skill should be used when the user asks to "adapt a worksheet", "transform content", "change response format", "substitute activities", "restructure items", or when code in adapt/ or validate/skill_parity.py is being created or modified. It ensures the targeted literacy skill is preserved through all adaptations.
version: 1.0.0
---

# Literacy Skill Preservation

The worksheet-builder allows HIGH adaptation — but must ALWAYS preserve the targeted literacy skill.

## What Must Be Preserved
- **Domain:** phonics stays phonics. Never drift to a different literacy domain.
- **Target words:** all source target words must appear in adapted items (or equivalent words testing the same phonetic pattern)
- **Learning objectives:** every objective in the source must be addressed
- **Skill type:** if the source tests decoding, the adaptation must still test decoding

## What May Change Freely
- Layout, spacing, visual design
- Instruction wording (simplified, numbered, grade-appropriate)
- Item ordering (can reorder by difficulty, scaffold)
- Item count (can reduce if preserving skill coverage)
- Added scaffolding (worked examples, hints, self-check boxes)
- Theme elements (decorative, avatar)

## Response Format Substitution Rules

NOT all substitutions are valid. The substitution must still test the same cognitive skill:

| Original | Valid Substitutions | INVALID (tests different skill) |
|----------|--------------------|---------------------------------|
| "Write the word from memory" | (none — must write) | "Circle the word" (tests recognition, not recall) |
| "Write the word you hear" | "Write the word" (still tests encoding) | "Circle the word" (tests recognition) |
| "Circle the correct spelling" | "Match correct spelling", "Point to correct" | "Write the word" (tests production, not recognition) |
| "Fill in the missing letter" | "Write the missing letter" | "Circle from choices" (if it removes the spelling challenge) |
| "Read the sentence aloud" | "Read to a partner" | "Circle the sentence" (not reading fluency) |
| "Match word to picture" | "Draw line to picture", "Point to picture" | "Write the word" (different skill) |

## Grade-Level Skill Expectations

When extracting or validating skills, use this reference:
- **K:** phonemic awareness, letter-sound connections, CVC words, concepts of print
- **G1:** phonics decoding (digraphs, blends), high-frequency words, simple fluency
- **G2:** vowel teams, r-controlled vowels, prefixes/suffixes, reading fluency, basic comprehension
- **G3:** multi-syllable decoding, morphology, comprehension strategies, text evidence

## When implementing adaptation code:
1. Always check that target words from LiteracySkillModel appear in AdaptedActivityModel items
2. Validate response format substitutions against the skill-aware rules above
3. Never remove items that are the only ones testing a specific target word
4. Flag ambiguous adaptations for human review rather than silently proceeding
