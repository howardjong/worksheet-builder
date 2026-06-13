"""Tests for the deterministic coverage ledger (Stage 1 coverage contract)."""

from __future__ import annotations

from adapt.coverage_ledger import build_coverage_ledger, verify_coverage
from adapt.llm_adapt import ActivityPlan, LessonPlan, PlannedItem, WorksheetPlan
from skill.schema import LiteracySkillModel, SourceItem


def _skill_with_chain_and_sentences() -> LiteracySkillModel:
    """A dense skill model: a 3-word chain, two sentences, a passage, words."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["mule", "cute", "mute"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="mule -> mute -> cute",
                source_region_index=0,
            ),
            SourceItem(
                item_type="sentence",
                content="The mule is cute.",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sentence",
                content="Do not be rude to the mule.",
                source_region_index=2,
            ),
            SourceItem(
                item_type="passage",
                content="Sam has a mule. The mule is cute. Sam is not rude.",
                source_region_index=3,
            ),
        ],
        extraction_confidence=0.9,
        template_type="word_work",
    )


def test_word_entries_one_per_deduped_target_word() -> None:
    skill = _skill_with_chain_and_sentences()
    ledger = build_coverage_ledger(skill)
    words = [e for e in ledger if e.item_type == "word"]
    assert {e.exact_text for e in words} == {"mule", "cute", "mute"}
    # stable, index-based ids
    assert [e.source_item_id for e in words] == ["word_001", "word_002", "word_003"]
    assert all(e.priority == "required" for e in words)


def test_chain_yields_chain_and_step_entries() -> None:
    skill = _skill_with_chain_and_sentences()
    ledger = build_coverage_ledger(skill)
    chains = [e for e in ledger if e.item_type == "word_chain"]
    steps = [e for e in ledger if e.item_type == "word_chain_step"]
    assert len(chains) == 1
    assert chains[0].source_item_id == "chain_001"
    assert chains[0].exact_text == "mule -> mute -> cute"
    # two arrow-split steps: mule->mute, mute->cute
    assert [s.exact_text for s in steps] == ["mute", "cute"]
    assert [s.source_item_id for s in steps] == ["chain_001_step_1", "chain_001_step_2"]
    assert all(s.parent_source_text == "mule -> mute -> cute" for s in steps)
    assert all(s.priority == "required" for s in steps)


def test_sentence_entries_preserve_full_text() -> None:
    skill = _skill_with_chain_and_sentences()
    ledger = build_coverage_ledger(skill)
    sentences = [e for e in ledger if e.item_type == "sentence"]
    assert [s.exact_text for s in sentences] == [
        "The mule is cute.",
        "Do not be rude to the mule.",
    ]
    assert [s.source_item_id for s in sentences] == ["sentence_001", "sentence_002"]
    assert all(s.priority == "required" for s in sentences)


def test_passage_entry_preserved_verbatim() -> None:
    skill = _skill_with_chain_and_sentences()
    ledger = build_coverage_ledger(skill)
    passages = [e for e in ledger if e.item_type == "passage"]
    assert len(passages) == 1
    assert passages[0].source_item_id == "passage_001"
    assert passages[0].exact_text == "Sam has a mule. The mule is cute. Sam is not rude."
    assert passages[0].priority == "required"


def test_ledger_is_stable_across_calls() -> None:
    skill = _skill_with_chain_and_sentences()
    first = build_coverage_ledger(skill)
    second = build_coverage_ledger(skill)
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]


def test_sight_words_become_sight_word_entries() -> None:
    skill = LiteracySkillModel(
        grade_level="K",
        domain="phonics",
        specific_skill="sight_words",
        learning_objectives=["Read sight words"],
        target_words=[],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="sight_words",
                content="the, was, said",
                source_region_index=0,
            ),
        ],
        extraction_confidence=0.9,
        template_type="sight_word",
    )
    ledger = build_coverage_ledger(skill)
    sight = [e for e in ledger if e.item_type == "sight_word"]
    assert [s.exact_text for s in sight] == ["the", "was", "said"]
    assert [s.source_item_id for s in sight] == [
        "sight_001",
        "sight_002",
        "sight_003",
    ]


# --- S2: verify_coverage (claim + exact-text) ---


def _small_skill() -> LiteracySkillModel:
    """One target word + one sentence → ledger required = word_001, sentence_001."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="sentence",
                content="The cake is on the lake.",
                source_region_index=0,
            ),
        ],
        extraction_confidence=0.9,
        template_type="word_work",
    )


def _plan(items: list[PlannedItem]) -> LessonPlan:
    return LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="t",
                activities=[ActivityPlan(activity_type="write", micro_goal="g", items=items)],
            )
        ]
    )


def test_missing_when_id_claimed_but_text_absent() -> None:
    ledger = build_coverage_ledger(_small_skill())
    plan = _plan([PlannedItem(content="apple", covered_source_item_ids=["word_001"])])
    report = verify_coverage(plan, ledger)
    assert "word_001" in {e.source_item_id for e in report.missing}
    assert report.unknown_claims == []


def test_covered_when_id_and_text_present() -> None:
    ledger = build_coverage_ledger(_small_skill())
    plan = _plan(
        [
            PlannedItem(content="Write the word cake.", covered_source_item_ids=["word_001"]),
            PlannedItem(
                content="The cake is on the lake.",
                covered_source_item_ids=["sentence_001"],
            ),
        ]
    )
    report = verify_coverage(plan, ledger)
    assert report.missing == []
    assert report.unknown_claims == []


def test_text_in_options_or_answer_counts() -> None:
    ledger = build_coverage_ledger(_small_skill())
    plan = _plan(
        [
            PlannedItem(
                content="Pick the real word.",
                options=["cake", "kake"],
                answer="cake",
                covered_source_item_ids=["word_001"],
            ),
            PlannedItem(
                content="The cake is on the lake.",
                covered_source_item_ids=["sentence_001"],
            ),
        ]
    )
    report = verify_coverage(plan, ledger)
    assert report.missing == []


def test_claim_required_text_alone_does_not_count() -> None:
    ledger = build_coverage_ledger(_small_skill())
    # text present, but the item never claims word_001 → not covered
    plan = _plan([PlannedItem(content="cake", covered_source_item_ids=[])])
    report = verify_coverage(plan, ledger)
    assert "word_001" in {e.source_item_id for e in report.missing}


def test_unknown_claim_is_reported() -> None:
    ledger = build_coverage_ledger(_small_skill())
    plan = _plan(
        [
            PlannedItem(content="cake", covered_source_item_ids=["word_001", "bogus_999"]),
            PlannedItem(
                content="The cake is on the lake.",
                covered_source_item_ids=["sentence_001"],
            ),
        ]
    )
    report = verify_coverage(plan, ledger)
    assert report.unknown_claims == ["bogus_999"]
    assert report.missing == []
