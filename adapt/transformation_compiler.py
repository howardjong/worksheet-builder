"""Compile verified word transformations into truthful student practice."""

from __future__ import annotations

from adapt.schema import ActivityChunk, ActivityItem, Example, Step
from skill.contract import TransformationContract
from skill.transformation import TransformationStep, verify_step


def _operation_kinds(step: TransformationStep) -> tuple[str, ...]:
    return tuple(operation.kind for operation in step.operations)


def instruction_steps_for(step: TransformationStep) -> list[Step]:
    """Return operation-accurate, calm instructions for one verified step."""
    kinds = _operation_kinds(step)
    if kinds == ("substitute_grapheme",):
        operation = step.operations[0]
        text = f'Change "{operation.old}" to "{operation.new}".'
        actions = ["Read the starting word.", text, "Write the new word."]
    elif kinds == ("insert_grapheme",):
        operation = step.operations[0]
        actions = [
            "Read the starting word.",
            f'Add "{operation.value}" in the shown place.',
            "Write the new word.",
        ]
    elif kinds == ("delete_grapheme",):
        operation = step.operations[0]
        actions = [
            "Read the starting word.",
            f'Remove "{operation.old or operation.value}".',
            "Write the new word.",
        ]
    elif kinds == ("prepend_affix",):
        actions = [
            "Read the base word.",
            f"Add {step.operations[0].value}- to the beginning.",
            "Write the whole word.",
        ]
    elif kinds == ("append_affix",):
        actions = [
            "Read the base word.",
            f"Add -{step.operations[0].value}.",
            "Write the whole word.",
        ]
    elif kinds == ("drop_final_e", "append_affix"):
        actions = ["Read the base word.", "Drop the final e.", "Add the ending and write."]
    elif kinds == ("double_final_consonant", "append_affix"):
        actions = [
            "Read the base word.",
            "Double the final consonant.",
            "Add the ending and write.",
        ]
    elif kinds == ("change_y_to_i", "append_affix"):
        actions = [
            "Read the base word.",
            "Change the final y to i.",
            "Add the ending and write.",
        ]
    else:
        actions = ["Read the base word.", "Make the verified change.", "Write the new word."]
    return [Step(number=index, text=text) for index, text in enumerate(actions, start=1)]


def _operation_phrase(step: TransformationStep) -> str:
    kinds = _operation_kinds(step)
    operation = step.operations[0]
    if kinds == ("substitute_grapheme",):
        return f'change "{operation.old}" to "{operation.new}"'
    if kinds == ("insert_grapheme",):
        return f'add "{operation.value}"'
    if kinds == ("delete_grapheme",):
        return f'remove "{operation.old or operation.value}"'
    if kinds == ("prepend_affix",):
        return f"add {operation.value}- to the beginning"
    if kinds == ("append_affix",):
        return f"add -{operation.value}"
    if kinds == ("drop_final_e", "append_affix"):
        return f"drop the final e, then add -{step.ending}"
    if kinds == ("double_final_consonant", "append_affix"):
        return f"double the final consonant, then add -{step.ending}"
    if kinds == ("change_y_to_i", "append_affix"):
        return f"change final y to i, then add -{step.ending}"
    return "make the verified change"


def worked_example_for(step: TransformationStep) -> Example:
    if not verify_step(step):
        raise ValueError("cannot compile an unverified transformation example")
    return Example(
        instruction="Watch one verified change:",
        content=f"{step.from_word} -> {step.to_word} ({_operation_phrase(step)})",
    )


def activity_item_for(step: TransformationStep, item_id: int) -> ActivityItem:
    """Create written production without displaying the expected answer."""
    if not verify_step(step):
        raise ValueError("cannot compile an unverified transformation item")
    kinds = _operation_kinds(step)
    if kinds == ("append_affix",):
        content = f"{step.from_word} + -{step.ending} → ______"
    elif kinds == ("drop_final_e", "append_affix"):
        content = (
            f'Start with "{step.from_word}". Drop the final e. Add -{step.ending}. Write: ______'
        )
    elif kinds == ("double_final_consonant", "append_affix"):
        content = (
            f'Start with "{step.from_word}". Double the final consonant. '
            f"Add -{step.ending}. Write: ______"
        )
    elif kinds == ("change_y_to_i", "append_affix"):
        content = (
            f'Start with "{step.from_word}". Change the final y to i. '
            f"Add -{step.ending}. Write: ______"
        )
    else:
        content = (
            f'Start with "{step.from_word}". {_operation_phrase(step).capitalize()}. Write: ______'
        )
    return ActivityItem(
        item_id=item_id,
        content=content,
        response_format="write",
        metadata={
            "display": "chain_step",
            "rule_id": step.rule_id,
            "spelling_rule": step.rule_id,
        },
        answer=step.to_word,
        transformation=step,
    )


def compile_transformation_chunk(
    steps: list[TransformationStep],
    contract: TransformationContract,
    *,
    chunk_id: int,
    item_id_start: int,
    max_items: int,
    include_example: bool = True,
) -> ActivityChunk | None:
    verified = [step for step in steps if verify_step(step)]
    if not verified:
        return None
    example_step = verified[0] if include_example and len(verified) > 1 else None
    practice = verified[1:] if example_step else verified
    practice = practice[:max_items]
    if not practice:
        return None
    items = [
        activity_item_for(step, item_id_start + index)
        for index, step in enumerate(practice, start=1)
    ]
    return ActivityChunk(
        chunk_id=chunk_id,
        micro_goal=f"Build {len(items)} new words",
        instructions=instruction_steps_for(practice[0]),
        worked_example=worked_example_for(example_step) if example_step else None,
        items=items,
        response_format="write",
        time_estimate="About 1 minute",
    )


def neutral_chain_item(chain: str, reason: str, item_id: int) -> ActivityItem:
    """Non-production fallback for an explicitly nonessential unknown chain."""
    return ActivityItem(
        item_id=item_id,
        content=chain,
        response_format="read_aloud",
        metadata={"display": "unverified_chain", "verification_reason": reason},
    )
