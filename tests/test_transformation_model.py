import pytest
from pydantic import ValidationError

from skill.transformation import (
    TransformationOperation,
    TransformationStep,
    replay_operations,
    verify_step,
)


@pytest.mark.parametrize(
    ("source", "operations", "expected"),
    [
        ("cry", [{"kind": "substitute_grapheme", "index": 0, "old": "c", "new": "t"}], "try"),
        ("pace", [{"kind": "insert_grapheme", "index": 0, "value": "s"}], "space"),
        ("plane", [{"kind": "delete_grapheme", "index": 1, "old": "l"}], "pane"),
        ("safe", [{"kind": "prepend_affix", "value": "un"}], "unsafe"),
        ("cloud", [{"kind": "append_affix", "value": "s"}], "clouds"),
        (
            "smile",
            [{"kind": "drop_final_e"}, {"kind": "append_affix", "value": "ing"}],
            "smiling",
        ),
        (
            "skip",
            [
                {"kind": "double_final_consonant", "value": "p"},
                {"kind": "append_affix", "value": "ed"},
            ],
            "skipped",
        ),
        (
            "happy",
            [{"kind": "change_y_to_i"}, {"kind": "append_affix", "value": "er"}],
            "happier",
        ),
    ],
)
def test_replay_operation_families(
    source: str, operations: list[dict[str, object]], expected: str
) -> None:
    parsed = [TransformationOperation.model_validate(operation) for operation in operations]
    assert replay_operations(source, parsed) == expected


def test_verified_step_round_trips_and_replays() -> None:
    step = TransformationStep(
        rule_id="drop_e_rule",
        source_chain="smile -> smiling",
        step_index=0,
        base_word="smile",
        from_word="smile",
        to_word="smiling",
        ending="ing",
        operations=[
            TransformationOperation(kind="drop_final_e"),
            TransformationOperation(kind="append_affix", value="ing"),
        ],
        verification_status="verified",
    )
    assert verify_step(step)
    assert TransformationStep.model_validate_json(step.model_dump_json()) == step


def test_operation_parameters_fail_closed() -> None:
    with pytest.raises(ValidationError):
        TransformationOperation(kind="append_affix")


def test_legacy_stage_payloads_parse_without_transformations() -> None:
    from adapt.schema import ActivityItem
    from skill.schema import SourceItem

    assert (
        SourceItem(
            item_type="word_chain", content="cry -> try", source_region_index=0
        ).transformations
        == []
    )
    assert ActivityItem(item_id=1, content="cry", response_format="write").transformation is None
