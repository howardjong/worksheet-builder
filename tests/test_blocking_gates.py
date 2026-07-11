"""Tests for deterministic blocking gates (T5).

These tests construct minimal AdaptedActivityModel worksheets plus a small
hand-built ObjectiveLedger and assert the exact blocker/warning behavior of each
gate. The emphasis is false-positive safety: legitimate answer!=option formats
(match, sound_box), sentence-initial proper nouns, and clean packets must PASS.
"""

from __future__ import annotations

from adapt.objective_ledger import (
    ClassifiedSourceItem,
    LedgerWord,
    ObjectiveCell,
    ObjectiveLedger,
)
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from validate.blocking_gates import (
    BlockingGateResult,
    BlockingViolation,
    run_blocking_gates,
)

# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #


def _item(
    item_id: int = 1,
    content: str = "cube",
    response_format: str = "circle",
    options: list[str] | None = None,
    answer: str | None = None,
) -> ActivityItem:
    return ActivityItem(
        item_id=item_id,
        content=content,
        response_format=response_format,
        options=options,
        answer=answer,
    )


def _chunk(
    items: list[ActivityItem],
    *,
    chunk_id: int = 1,
    instructions: list[Step] | None = None,
    worked_example: Example | None = None,
    response_format: str = "circle",
) -> ActivityChunk:
    return ActivityChunk(
        chunk_id=chunk_id,
        micro_goal="Practice",
        instructions=instructions or [Step(number=1, text="Do the work.")],
        worked_example=worked_example,
        items=items,
        response_format=response_format,
        time_estimate="About 3 minutes",
    )


def _worksheet(chunks: list[ActivityChunk]) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="srch",
        skill_model_hash="skh",
        learner_profile_hash="lph",
        grade_level="1",
        domain="phonics",
        specific_skill="u_e",
        chunks=chunks,
        scaffolding=ScaffoldConfig(),
        theme_id="space",
        decoration_zones=[],
    )


def _ledger(
    *,
    objectives: list[ObjectiveCell] | None = None,
    source_items: list[ClassifiedSourceItem] | None = None,
    primary_pattern: str | None = "u_e",
) -> ObjectiveLedger:
    return ObjectiveLedger(
        source_skill_hash="skh",
        lesson_number=33,
        corpus_status="matched",
        corpus_version="cv1",
        primary_pattern=primary_pattern,
        objectives=objectives or [],
        source_items=source_items or [],
    )


def _classified(
    *,
    content: str,
    item_type: str = "word_list",
    word_roles: list[LedgerWord] | None = None,
) -> ClassifiedSourceItem:
    return ClassifiedSourceItem(
        source_item_id=f"src_{item_type}",
        item_type=item_type,
        content=content,
        normalized_content=content.strip().lower(),
        coverage_class="samplable_pool",
        word_roles=word_roles or [],
        mandatory=False,
    )


def _empty_ledger() -> ObjectiveLedger:
    return _ledger()


def _gate_names(result: BlockingGateResult) -> set[str]:
    return {v.gate for v in result.violations}


def _blockers(result: BlockingGateResult) -> list[BlockingViolation]:
    return [v for v in result.violations if v.severity == "blocker"]


# --------------------------------------------------------------------------- #
# answer_key gate
# --------------------------------------------------------------------------- #


def test_fill_blank_answer_not_in_options_blocks() -> None:
    ws = _worksheet(
        [_chunk([_item(response_format="fill_blank", options=["cat", "dog"], answer="fish")])]
    )
    result = run_blocking_gates([ws], _empty_ledger())
    assert result.passed is False
    assert "answer_key" in _gate_names(result)
    assert _blockers(result)


def test_circle_answer_in_options_passes() -> None:
    ws = _worksheet(
        [_chunk([_item(response_format="circle", options=["cube", "cup"], answer="cube")])]
    )
    result = run_blocking_gates([ws], _empty_ledger())
    assert "answer_key" not in _gate_names(result)


def test_match_answer_not_in_options_passes() -> None:
    # match deliberately pairs answer != option (e.g. word -> picture).
    ws = _worksheet(
        [_chunk([_item(response_format="match", options=["cube", "tube"], answer="picture")])]
    )
    result = run_blocking_gates([ws], _empty_ledger())
    assert "answer_key" not in _gate_names(result)
    assert result.passed is True


def test_sound_box_phoneme_options_whole_word_answer_passes() -> None:
    ws = _worksheet(
        [
            _chunk(
                [
                    _item(
                        response_format="sound_box",
                        content="cat",
                        options=["/k/", "/a/", "/t/"],
                        answer="cat",
                    )
                ]
            )
        ]
    )
    result = run_blocking_gates([ws], _empty_ledger())
    assert "answer_key" not in _gate_names(result)
    assert result.passed is True


def test_fill_blank_empty_options_not_checked() -> None:
    ws = _worksheet([_chunk([_item(response_format="fill_blank", options=None, answer="fish")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "answer_key" not in _gate_names(result)


def test_unknown_response_format_is_warning_not_blocker() -> None:
    ws = _worksheet([_chunk([_item(response_format="mystery", options=["a", "b"], answer="zzz")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert result.passed is True
    warnings = [v for v in result.violations if v.severity == "warning"]
    assert any(v.gate == "answer_key" for v in warnings)


# --------------------------------------------------------------------------- #
# capitalization gate
# --------------------------------------------------------------------------- #


def _june_ledger() -> ObjectiveLedger:
    # "June" appears mid-list (not sentence-initial) in a u_e word list, so it's a
    # known proper noun.
    src = _classified(content="cube, mute, fuse, tune, rule, June", item_type="word_list")
    return _ledger(source_items=[src])


def test_lowercased_proper_noun_mid_sentence_blocks() -> None:
    ws = _worksheet([_chunk([_item(content="We go in june.", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _june_ledger())
    assert result.passed is False
    assert "capitalization" in _gate_names(result)


def test_proper_noun_sentence_initial_passes() -> None:
    ws = _worksheet([_chunk([_item(content="June is fun.", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _june_ledger())
    assert "capitalization" not in _gate_names(result)


def test_correctly_capitalized_proper_noun_mid_sentence_passes() -> None:
    ws = _worksheet([_chunk([_item(content="We go in June.", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _june_ledger())
    assert "capitalization" not in _gate_names(result)


def _puppy_ledger() -> ObjectiveLedger:
    # Passage source item: title-case heading line + body with lowercase "puppy".
    src = _classified(
        content="Lily's Puppy\nLily has a puppy. The puppy runs fast.",
        item_type="word_list",
    )
    return _ledger(source_items=[src])


def test_title_case_heading_does_not_create_proper_nouns() -> None:
    ws = _worksheet([_chunk([_item(content="Write puppy here.", response_format="write")])])
    result = run_blocking_gates([ws], _puppy_ledger())
    assert "capitalization" not in _gate_names(result)


def test_lowercase_occurrence_exonerates_capitalized_token() -> None:
    # "Puppy" appears capitalized mid-title AND lowercase in the body →
    # lowercase evidence wins; not a proper noun.
    ws = _worksheet(
        [_chunk([_item(content="Feed the puppy today.", response_format="read_aloud")])]
    )
    result = run_blocking_gates([ws], _puppy_ledger())
    assert "capitalization" not in _gate_names(result)


def test_title_only_word_without_lowercase_evidence_still_safe() -> None:
    # Word appears ONLY in the title-case heading ("Lily's") — heading exclusion
    # alone must keep it out of the proper-noun set... unless it also shows up
    # capitalized mid-sentence in a body line (like June in a word list).
    ws = _worksheet([_chunk([_item(content="Say lily out loud.", response_format="verbal")])])
    result = run_blocking_gates([ws], _puppy_ledger())
    assert "capitalization" not in _gate_names(result)


def _garden_ledger() -> ObjectiveLedger:
    # Title-case heading contains "Garden"; the body never mentions garden at
    # all (lowercase or otherwise), so the lowercase-seen guard (heuristic 2)
    # never fires for this word — only the title-case-segment exclusion
    # (heuristic 1) keeps "Garden" out of the proper-noun set.
    src = _classified(
        content="The Lily Garden\nWe like to play. We ran fast.",
        item_type="word_list",
    )
    return _ledger(source_items=[src])


def test_title_only_word_exonerated_by_heading_exclusion_alone() -> None:
    ws = _worksheet([_chunk([_item(content="Water the garden now.", response_format="write")])])
    result = run_blocking_gates([ws], _garden_ledger())
    assert "capitalization" not in _gate_names(result)


def _bumpy_ledger() -> ObjectiveLedger:
    # "Bumpy" is capitalized mid-sentence in a NON-title body line (the segment
    # is not all-title-case, so heuristic 1's heading exclusion cannot apply),
    # but "bumpy" also appears lowercase later in the same source item →
    # heuristic 2 (lowercase-seen guard) alone must exonerate it.
    src = _classified(
        content="We saw Bumpy roads today. The bumpy road was long.",
        item_type="word_list",
    )
    return _ledger(source_items=[src])


def test_lowercase_corroboration_alone_exonerates() -> None:
    ws = _worksheet([_chunk([_item(content="Read bumpy aloud.", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _bumpy_ledger())
    assert "capitalization" not in _gate_names(result)


# --------------------------------------------------------------------------- #
# heading_as_item gate
# --------------------------------------------------------------------------- #


def test_known_heading_used_as_item_blocks() -> None:
    ws = _worksheet([_chunk([_item(content="Roll and Read", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert result.passed is False
    assert "heading_as_item" in _gate_names(result)


def test_chain_label_from_ledger_used_as_item_blocks() -> None:
    src = _classified(content="Word Chain", item_type="chain_script")
    ledger = _ledger(source_items=[src])
    ws = _worksheet([_chunk([_item(content="Word Chain", response_format="read_aloud")])])
    result = run_blocking_gates([ws], ledger)
    assert result.passed is False
    assert "heading_as_item" in _gate_names(result)


def test_normal_practice_item_is_not_heading() -> None:
    ws = _worksheet([_chunk([_item(content="cube", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "heading_as_item" not in _gate_names(result)


# --------------------------------------------------------------------------- #
# worked_example_consistency gate
# --------------------------------------------------------------------------- #


def test_worked_example_negation_after_answer_blocks() -> None:
    # Triggers via the strong contradiction token ``wrong`` (bare no/not no longer
    # trip this gate).
    ex = Example(instruction="Watch:", content="cube -> kube. That is wrong.")
    ws = _worksheet([_chunk([_item(content="cube")], worked_example=ex)])
    result = run_blocking_gates([ws], _empty_ledger())
    assert result.passed is False
    assert "worked_example_consistency" in _gate_names(result)


def test_worked_example_incorrect_token_blocks() -> None:
    ex = Example(instruction="Watch:", content="cube -> kube. That is incorrect.")
    ws = _worksheet([_chunk([_item(content="cube")], worked_example=ex)])
    result = run_blocking_gates([ws], _empty_ledger())
    assert result.passed is False
    assert "worked_example_consistency" in _gate_names(result)


def test_worked_example_legitimate_not_copy_passes() -> None:
    # FALSE-POSITIVE guard: bare ``not``/``no`` in legitimate instructional prose
    # must NOT block.
    for copy in (
        "Do not forget the silent e.",
        "Circle the word, not the picture.",
        "There is no short u here.",
    ):
        ex = Example(instruction="Watch:", content=copy)
        ws = _worksheet([_chunk([_item(content="cube")], worked_example=ex)])
        result = run_blocking_gates([ws], _empty_ledger())
        assert "worked_example_consistency" not in _gate_names(result), copy


def test_worked_example_internal_answer_not_in_options_blocks() -> None:
    # The worked example carries its own options/answer that mismatch.
    ex = Example(instruction="Watch:", content="Circle: cube tube | answer: zebra")
    item = _item(response_format="circle", options=["cube", "tube"], answer="cube")
    ws = _worksheet([_chunk([item], worked_example=ex)])
    result = run_blocking_gates([ws], _empty_ledger())
    # mismatch detected via the answer:... vs displayed-words mismatch.
    assert "worked_example_consistency" in _gate_names(result)
    assert result.passed is False


def test_clean_worked_example_passes() -> None:
    ex = Example(instruction="Watch how I do the first one:", content="cube -> I hear long u!")
    ws = _worksheet([_chunk([_item(content="tube")], worked_example=ex)])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "worked_example_consistency" not in _gate_names(result)


# --------------------------------------------------------------------------- #
# instruction predicate parsing (false-positive guards)
# --------------------------------------------------------------------------- #


def test_hyphenated_instruction_word_does_not_parse_as_rime() -> None:
    # FALSE-POSITIVE guard: "sound-by-sound" must NOT yield a rime:by predicate
    # that hard-blocks a legitimate keyed answer via gates 2/6.
    chunk = _chunk(
        [_item(response_format="circle", options=["cube", "cup"], answer="cube")],
        instructions=[Step(number=1, text="Read each word sound-by-sound.")],
    )
    ws = _worksheet([chunk])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "instruction_option_answer" not in _gate_names(result)
    assert result.passed is True


def test_genuine_rime_cue_still_parses_and_blocks_bad_answer() -> None:
    # A real rime cue ("the -oll words") must still predicate-check: an answer that
    # doesn't end in -oll blocks.
    chunk = _chunk(
        [_item(response_format="fill_blank", options=["roll", "cube"], answer="cube")],
        instructions=[Step(number=1, text="Write the -oll words.")],
    )
    ws = _worksheet([chunk])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "instruction_option_answer" in _gate_names(result)
    assert result.passed is False


# --------------------------------------------------------------------------- #
# source_notation_artifact gate
# --------------------------------------------------------------------------- #


def test_source_notation_star_in_content_blocks() -> None:
    ws = _worksheet([_chunk([_item(content="by* my* one", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert result.passed is False
    assert "source_notation_artifact" in _gate_names(result)


def test_source_notation_in_option_blocks() -> None:
    ws = _worksheet(
        [_chunk([_item(response_format="circle", options=["cube", "tube*"], answer="cube")])]
    )
    result = run_blocking_gates([ws], _empty_ledger())
    assert "source_notation_artifact" in _gate_names(result)


def test_normal_punctuation_not_flagged_as_artifact() -> None:
    ws = _worksheet([_chunk([_item(content="Run to the den.", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "source_notation_artifact" not in _gate_names(result)


def test_plain_parenthetical_not_flagged_as_artifact() -> None:
    # FALSE-POSITIVE guard: ordinary K-3 parentheticals must NOT block.
    for content in ("I can run (and jump).", "cube (long u)"):
        ws = _worksheet([_chunk([_item(content=content, response_format="read_aloud")])])
        result = run_blocking_gates([ws], _empty_ledger())
        assert "source_notation_artifact" not in _gate_names(result), content


def test_annotation_parenthetical_still_blocks() -> None:
    # A paren that reads as a source annotation IS an artifact.
    ws = _worksheet([_chunk([_item(content="the (heart word)", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "source_notation_artifact" in _gate_names(result)
    assert result.passed is False


def test_bracket_annotation_still_blocks() -> None:
    ws = _worksheet([_chunk([_item(content="the [heart word]", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _empty_ledger())
    assert "source_notation_artifact" in _gate_names(result)
    assert result.passed is False


# --------------------------------------------------------------------------- #
# clean packet + determinism
# --------------------------------------------------------------------------- #


def test_clean_packet_passes_with_no_violations() -> None:
    chunk = _chunk(
        [
            _item(item_id=1, content="cube", response_format="read_aloud"),
            _item(item_id=2, response_format="circle", options=["cube", "cup"], answer="cube"),
        ],
        worked_example=Example(instruction="Watch:", content="cube -> long u"),
    )
    ws = _worksheet([chunk])
    result = run_blocking_gates([ws], _june_ledger())
    assert result.passed is True
    assert result.violations == []


def test_violations_are_deterministically_ordered() -> None:
    ws = _worksheet(
        [
            _chunk(
                [
                    _item(
                        item_id=2,
                        response_format="fill_blank",
                        options=["cat"],
                        answer="fish",
                    ),
                    _item(item_id=1, content="by*", response_format="read_aloud"),
                ]
            )
        ]
    )
    result = run_blocking_gates([ws], _empty_ledger())
    keys = [(v.activity_id, v.item_id, v.gate) for v in result.violations]
    assert keys == sorted(keys, key=lambda k: (k[0] or "", k[1] or "", k[2]))
