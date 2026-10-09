# GPT Image test in this chat: copy-paste prompt

This complements the OpenRouter experiment in
[approved-reference-consistency.md](approved-reference-consistency.md).
It tests visual conditioning through built-in GPT image generation. It does
not establish production Luna approval or OpenRouter end-to-end latency.

```text
Use GPT image generation here to test whether the new approved character
references improve first-attempt worksheet artwork.

Use howardjong/worksheet-builder, branch
codex/on-demand-composed-worksheets, and the library at
assets/characters/rainbow_learning_buddy/reference_library/v1/.
Read its manifest and inspect the original and selected references first.
Keep the original character as the identity authority.

Generate FOUR separate illustrations: two reference configurations for
each of these two learning actions. One generation per illustration;
preserve and show every first attempt, including failures. No retries,
selection from hidden alternatives, or repairs.

Control: original-authority/neutral-full-body.png plus
original-authority/neutral-face.png.

New references: the SAME original full-body reference, plus the approved
expression below, plus items/wardrobe/astronaut.png. Use only these three
references; do not send a whole sheet or the entire library.

Action 1: the buddy joins a blank word-part tile to another group of blank
tiles. Give the buddy a cheerful open smile in BOTH reference configurations.
For the new configuration use items/expressions/happy-open-smile.png.

Action 2: the buddy holds a pencil ABOVE three blank choice cards, considering
them without touching, circling or marking a card. Give the buddy a thoughtful
expression in BOTH configurations. For the new configuration use
items/expressions/thinking.png.

Hold the actual generation prompt and available settings fixed for each
action; only the supplied reference configuration changes. Say that image 1
fixes character identity, image 2 supplies face/hair detail, and image 3,
if present, supplies costume. All depict the same buddy; draw that buddy once.

For every illustration: landscape 16:9, calm sparse white background,
recognizable rainbow hairstyle, original face/eye construction and blocky
proportions, an astronaut costume with face and hair visible, clear hands
and learning materials. The action must be useful to the child's procedure.
No letters, numbers, words, pseudo-text, labels, marked answers or worksheet
page layout. Keep all tiles/cards blank. Change expression without redesigning
the character. The two learning actions must look different.

Show all four first attempts, clearly labelled by action and configuration.
Review likeness, expressiveness, task/action relevance, costume, child safety,
absence of text/answers and usable composition. Report pass, fail or uncertain
for your visual review, with specific reasons. Do not invent Luna scores or
call a visual judgement a production-gate pass. Record observed generation
time if available and state the tool/model information actually exposed.

Let me give the final likeness verdict. Summarize whether the new-reference
configuration looks more promising; four images are a pilot, not proof of a
reliable first-pass rate. Preserve the prompts, reference hashes and outputs
so Muse can later run the unchanged production Luna gate on the saved art.
```
