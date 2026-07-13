"""Story passage chunking + worked examples (spec 2026-07-13, defect D8)."""

from __future__ import annotations

from adapt.engine import _build_story_chunks, _format_passage
from adapt.rules import build_rules
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem


def test_format_passage_groups_sentences_into_short_paragraphs() -> None:
    text = " ".join(f"Sentence number {i} is here." for i in range(1, 10))
    formatted = _format_passage(text)
    paragraphs = [p for p in formatted.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 3
    for p in paragraphs:
        assert p.count(".") <= 3, "at most 3 sentences per paragraph"


def test_format_passage_preserves_every_sentence() -> None:
    text = "One is here. Two is here! Three is here? Four is here."
    formatted = _format_passage(text)
    for s in ["One is here.", "Two is here!", "Three is here?", "Four is here."]:
        assert s in formatted


def _fluency_skill_for_story() -> LiteracySkillModel:
    """Synthetic fluency skill model with a 9-sentence passage and target words."""
    return LiteracySkillModel(
        grade_level="1",
        domain="fluency",
        specific_skill="decodable_text_cvce",
        learning_objectives=[
            "Read a decodable passage with fluency and accuracy",
            "Apply cvce pattern knowledge in connected text",
        ],
        target_words=["june", "flute", "tune", "dune", "luke"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="passage",
                content="June has a flute. June likes to use the flute to make tunes.",
                source_region_index=2,
            ),
            SourceItem(
                item_type="passage",
                content="Once, June and Luke made tunes at lunch for their pals.",
                source_region_index=3,
            ),
        ],
        extraction_confidence=0.92,
        template_type="ufli_decodable_story",
    )


def _grade_1_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test G1",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="medium",
            response_format_prefs=["write", "circle"],
        ),
    )


def test_story_chunks_use_formatted_passage_and_worked_example() -> None:
    skill = _fluency_skill_for_story()
    rules = build_rules(_grade_1_profile())
    sentences = [
        "June has a flute.",
        "June likes to use the flute to make tunes.",
        "Luke has a tune too.",
        "June and Luke play at the dune.",
    ]
    passage = " ".join(f"Sentence number {i} is here about June." for i in range(1, 10))
    chunks = _build_story_chunks(
        sentences=sentences,
        passages=[passage],
        target_words=skill.target_words,
        skill=skill,
        rules=rules,
    )

    read_chunks = [c for c in chunks if c.response_format == "read_aloud"]
    assert "\n\n" in read_chunks[0].items[0].content

    sentence_chunks = [c for c in chunks if "sentence" in c.micro_goal.lower()]
    assert sentence_chunks[0].worked_example is not None
    # Worked example consumed the first convertible sentence — not repeated as an item.
    assert all(
        sentence_chunks[0].worked_example.content.split(" → ")[0] != i.content
        for i in sentence_chunks[0].items
    )


def test_worked_example_only_on_first_sentence_batch() -> None:
    """Scaffolding fade: only the FIRST sentence-completion batch shows a worked
    example; later batches keep all their items (house convention, batch_start
    == 0 idiom — Task 5 review)."""
    skill = _fluency_skill_for_story()
    rules = build_rules(_grade_1_profile())
    assert rules.max_items_per_chunk == 4, "repro assumes grade-1 medium chunk cap of 4"
    # 8 convertible sentences (each carries a target word) -> 2 batches of 4.
    sentences = [
        "June has a flute.",
        "Luke likes the tune.",
        "The dune is by June.",
        "Luke plays a flute.",
        "June found a tune.",
        "The dune has Luke.",
        "June has a tune.",
        "Luke sees the dune.",
    ]
    chunks = _build_story_chunks(
        sentences=sentences,
        passages=[],
        target_words=skill.target_words,
        skill=skill,
        rules=rules,
    )

    sentence_chunks = [c for c in chunks if "sentence" in c.micro_goal.lower()]
    assert len(sentence_chunks) >= 2, "repro must produce at least two sentence batches"
    # Batch 1 has the worked example.
    assert sentence_chunks[0].worked_example is not None
    # Every later batch has none — and none of them lost an item to a pop.
    for chunk in sentence_chunks[1:]:
        assert chunk.worked_example is None
        assert len(chunk.items) == rules.max_items_per_chunk
