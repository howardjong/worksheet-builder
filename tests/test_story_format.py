"""Story passage chunking + worked examples (spec 2026-07-13, defect D8)."""

from __future__ import annotations

from adapt.engine import _build_story_chunks, _format_passage, _passage_excerpt
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


def test_passage_excerpt_keeps_title_and_two_to_four_opening_sentences() -> None:
    text = (
        "The Baker\n\n"
        "Rashawn is a world class baker. "
        "He has been baking since he was a little boy. "
        "Every day he dances while making treats. "
        "He trades tips with other bakers."
    )
    excerpt = _passage_excerpt(text)

    assert excerpt.startswith("The Baker\n\n")
    assert "Rashawn is a world class baker." in excerpt
    assert "Every day he dances while making treats." in excerpt
    assert "He trades tips with other bakers." in excerpt
    assert excerpt.count(".") == 4


def test_ufli_word_work_story_uses_bounded_source_excerpt() -> None:
    skill = _fluency_skill_for_story().model_copy(
        update={"template_type": "ufli_word_work", "target_words": ["baking"]}
    )
    rules = build_rules(_grade_1_profile())
    passage = (
        "The Baker\n\n"
        "Rashawn is a baker. He has been baking a pie. "
        "He smiles as he makes it. His friend visits the kitchen. "
        "They share the pie after lunch."
    )
    chunks = _build_story_chunks([], [passage], skill.target_words, skill, rules)
    read_item = next(
        item for chunk in chunks if chunk.response_format == "read_aloud" for item in chunk.items
    )

    assert read_item.metadata.get("source_excerpt") is True
    assert "He smiles as he makes it." in read_item.content
    assert "His friend visits the kitchen." in read_item.content
    assert "They share the pie after lunch." not in read_item.content
    assert read_item.content.count(".") == 4
    read_chunk = next(chunk for chunk in chunks if chunk.response_format == "read_aloud")
    assert read_chunk.instructions[1].text == ("Underline these target words in the story: baking.")


def test_excerpt_comprehension_uses_only_the_visible_story() -> None:
    skill = _fluency_skill_for_story().model_copy(
        update={
            "template_type": "ufli_word_work",
            "target_words": ["baking", "larger"],
        }
    )
    rules = build_rules(_grade_1_profile())
    passage = (
        "The Baker\n\n"
        "Rashawn is a baker. He has been baking a pie. "
        "He smiles as he makes it. His friend visits the kitchen. "
        "His friend takes the larger slice."
    )
    chunks = _build_story_chunks([], [passage], skill.target_words, skill, rules)
    read_text = next(
        item.content
        for chunk in chunks
        if chunk.response_format == "read_aloud"
        for item in chunk.items
    ).lower()
    comp_items = [
        item
        for chunk in chunks
        if chunk.micro_goal == "Check your understanding"
        for item in chunk.items
    ]

    assert "baking" in read_text
    assert "larger" in read_text
    pattern_question = next(
        item
        for item in comp_items
        if item.content == "Which word from the pattern is in the story?"
    )
    assert pattern_question.answer == "baking"
    assert all(item.answer != "No" for item in comp_items if item.content.startswith("Is the word"))
    assert [item.item_id for item in comp_items] == list(range(1, len(comp_items) + 1))


def test_excerpt_selects_target_bearing_window_for_any_source_type() -> None:
    skill = _fluency_skill_for_story().model_copy(
        update={"template_type": "unknown", "target_words": ["flute", "tune"]}
    )
    rules = build_rules(_grade_1_profile())
    passage = (
        "Music Day\n\n"
        "Mara wakes up early. She packs a small lunch. They walk to the park. "
        "A band starts to play. Luke plays a flute. Mara hums the tune."
    )
    chunks = _build_story_chunks([], [passage], skill.target_words, skill, rules)
    read_text = next(
        item.content
        for chunk in chunks
        if chunk.response_format == "read_aloud"
        for item in chunk.items
    )
    assert "flute" in read_text.casefold()
    assert "tune" in read_text.casefold()


def test_comprehension_word_presence_uses_whole_words() -> None:
    from adapt.engine import _generate_comprehension_questions

    questions = _generate_comprehension_questions(
        ["The engine worked powerfully. It stayed calm."], ["powerful", "calm"]
    )
    pattern_question = next(question for question in questions if question[0].startswith("Which"))
    assert pattern_question[2] == "calm"


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
