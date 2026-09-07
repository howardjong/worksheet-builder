"""Typed, replayable word transformations shared by every source path.

The source curriculum may supply an arrow chain, an OCR result, or an
AI-authored plan.  None of those surfaces is trusted as an explanation of the
spelling change.  This module derives operations from the word pair, replays
them, and marks the step unsupported unless the replay is exact.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from skill.contract import TransformationContract

OperationKind = Literal[
    "substitute_grapheme",
    "insert_grapheme",
    "delete_grapheme",
    "prepend_affix",
    "append_affix",
    "drop_final_e",
    "double_final_consonant",
    "change_y_to_i",
]

_SourceItemT = TypeVar("_SourceItemT")


class TransformationOperation(BaseModel):
    """One deterministic edit in a word transformation."""

    kind: OperationKind
    value: str | None = None
    index: int | None = None
    old: str | None = None
    new: str | None = None

    @model_validator(mode="after")
    def validate_parameters(self) -> TransformationOperation:
        if self.kind == "substitute_grapheme":
            if self.index is None or not self.old or not self.new:
                raise ValueError("substitution requires index, old, and new")
        elif self.kind == "insert_grapheme":
            if self.index is None or not self.value:
                raise ValueError("insertion requires index and value")
        elif self.kind == "delete_grapheme":
            if self.index is None or not (self.old or self.value):
                raise ValueError("deletion requires index and old/value")
        elif self.kind in {"prepend_affix", "append_affix"} and not self.value:
            raise ValueError(f"{self.kind} requires a value")
        return self


class TransformationStep(BaseModel):
    """A source word, expected result, and mechanically checkable operations."""

    rule_id: str
    source_chain: str
    step_index: int = Field(ge=0)
    base_word: str
    from_word: str
    to_word: str
    ending: str | None = None
    operations: list[TransformationOperation] = Field(default_factory=list)
    verification_status: Literal["verified", "unsupported"]
    verification_reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> TransformationStep:
        if self.verification_status == "verified" and not self.operations:
            raise ValueError("verified transformations require operations")
        if self.verification_status == "unsupported" and not self.verification_reason:
            raise ValueError("unsupported transformations require a reason")
        return self


class TransformationReplayError(ValueError):
    """An operation could not be applied to the supplied word."""


def replay_operations(from_word: str, operations: list[TransformationOperation]) -> str:
    """Apply operations in order or fail with a precise deterministic error."""
    word = from_word.casefold()
    for operation in operations:
        if operation.kind == "substitute_grapheme":
            assert operation.index is not None and operation.old and operation.new
            end = operation.index + len(operation.old)
            if word[operation.index : end] != operation.old:
                raise TransformationReplayError("substitution source does not match")
            word = word[: operation.index] + operation.new + word[end:]
        elif operation.kind == "insert_grapheme":
            assert operation.index is not None and operation.value
            if not 0 <= operation.index <= len(word):
                raise TransformationReplayError("insertion index is outside the word")
            word = word[: operation.index] + operation.value + word[operation.index :]
        elif operation.kind == "delete_grapheme":
            assert operation.index is not None
            old = operation.old or operation.value
            assert old
            end = operation.index + len(old)
            if word[operation.index : end] != old:
                raise TransformationReplayError("deletion source does not match")
            word = word[: operation.index] + word[end:]
        elif operation.kind == "prepend_affix":
            assert operation.value
            word = operation.value + word
        elif operation.kind == "append_affix":
            assert operation.value
            word += operation.value
        elif operation.kind == "drop_final_e":
            if not word.endswith("e"):
                raise TransformationReplayError("word has no final e to drop")
            word = word[:-1]
        elif operation.kind == "double_final_consonant":
            if not word or word[-1] in "aeiou":
                raise TransformationReplayError("word has no final consonant to double")
            if operation.value and operation.value != word[-1]:
                raise TransformationReplayError("doubling value does not match final consonant")
            word += word[-1]
        elif operation.kind == "change_y_to_i":
            if not word.endswith("y"):
                raise TransformationReplayError("word has no final y to change")
            word = word[:-1] + "i"
    return word


def verify_step(step: TransformationStep) -> bool:
    """Return true only when a verified step replays to its expected answer."""
    if step.verification_status != "verified":
        return False
    try:
        return replay_operations(step.from_word, step.operations) == step.to_word.casefold()
    except TransformationReplayError:
        return False


def _unsupported(
    left: str,
    right: str,
    contract: TransformationContract,
    source_chain: str,
    step_index: int,
    base_word: str,
    reason: str,
) -> TransformationStep:
    return TransformationStep(
        rule_id=contract.rule_id,
        source_chain=source_chain,
        step_index=step_index,
        base_word=base_word,
        from_word=left,
        to_word=right,
        verification_status="unsupported",
        verification_reason=reason,
    )


def _single_edit(left: str, right: str) -> list[TransformationOperation] | None:
    """Infer one exact substitution, insertion, or deletion."""
    if len(left) == len(right):
        changed = [i for i, pair in enumerate(zip(left, right, strict=True)) if pair[0] != pair[1]]
        if changed and changed == list(range(changed[0], changed[-1] + 1)):
            i = changed[0]
            end = changed[-1] + 1
            if end - i > 2:
                return None
            return [
                TransformationOperation(
                    kind="substitute_grapheme",
                    index=i,
                    old=left[i:end],
                    new=right[i:end],
                )
            ]
        return None

    if abs(len(left) - len(right)) != 1:
        return None
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    while index < len(shorter) and shorter[index] == longer[index]:
        index += 1
    inserted = longer[index]
    if shorter[:index] + inserted + shorter[index:] != longer:
        return None
    if len(left) < len(right):
        return [TransformationOperation(kind="insert_grapheme", index=index, value=inserted)]
    return [TransformationOperation(kind="delete_grapheme", index=index, old=inserted)]


def _candidate_recipes(
    left: str, right: str, contract: TransformationContract
) -> list[tuple[list[TransformationOperation], str | None]]:
    """Return mechanically plausible recipes in pedagogically truthful order."""
    candidates: list[tuple[list[TransformationOperation], str | None]] = []
    endings = sorted(contract.allowed_endings, key=len, reverse=True)
    prefixes = sorted(contract.allowed_prefixes, key=len, reverse=True)

    # Orthographic changes must win over a merely surface-plausible suffix
    # split (e.g. greedy -> greediness, not greedi + -ness).
    for ending in endings:
        if left.endswith("y") and right == f"{left[:-1]}i{ending}":
            candidates.append(
                (
                    [
                        TransformationOperation(kind="change_y_to_i"),
                        TransformationOperation(kind="append_affix", value=ending),
                    ],
                    ending,
                )
            )
        if left.endswith("e") and right == f"{left[:-1]}{ending}":
            candidates.append(
                (
                    [
                        TransformationOperation(kind="drop_final_e"),
                        TransformationOperation(kind="append_affix", value=ending),
                    ],
                    ending,
                )
            )
        if left and right == f"{left}{left[-1]}{ending}":
            candidates.append(
                (
                    [
                        TransformationOperation(kind="double_final_consonant", value=left[-1]),
                        TransformationOperation(kind="append_affix", value=ending),
                    ],
                    ending,
                )
            )
        if right == f"{left}{ending}":
            candidates.append(
                ([TransformationOperation(kind="append_affix", value=ending)], ending)
            )
    for prefix in prefixes:
        if right == f"{prefix}{left}":
            candidates.append(([TransformationOperation(kind="prepend_affix", value=prefix)], None))
    simple = _single_edit(left, right)
    if simple:
        candidates.append((simple, None))
    return candidates


def analyze_pair(
    left: str,
    right: str,
    contract: TransformationContract,
    *,
    base_word: str | None = None,
    source_chain: str = "",
    step_index: int = 0,
) -> TransformationStep:
    """Analyze one pair against contract-permitted recipes and verify replay."""
    normalized_left = re.sub(r"[^a-z]", "", left.casefold())
    normalized_right = re.sub(r"[^a-z]", "", right.casefold())
    base = re.sub(r"[^a-z]", "", (base_word or left).casefold())
    if not normalized_left or not normalized_right or normalized_left == normalized_right:
        return _unsupported(
            normalized_left,
            normalized_right,
            contract,
            source_chain,
            step_index,
            base,
            "pair does not contain two different alphabetic words",
        )

    permitted = {tuple(recipe) for recipe in contract.permitted_recipes}
    for operations, ending in _candidate_recipes(normalized_left, normalized_right, contract):
        recipe = tuple(op.kind for op in operations)
        if recipe not in permitted:
            continue
        step = TransformationStep(
            rule_id=contract.rule_id,
            source_chain=source_chain,
            step_index=step_index,
            base_word=base,
            from_word=normalized_left,
            to_word=normalized_right,
            ending=ending,
            operations=operations,
            verification_status="verified",
        )
        if verify_step(step):
            return step
    return _unsupported(
        normalized_left,
        normalized_right,
        contract,
        source_chain,
        step_index,
        base,
        "no permitted operation recipe replays to the target word",
    )


_ARROW_RE = re.compile(r"\s*(?:->|→)\s*")


def analyze_chain(text: str, contract: TransformationContract) -> list[TransformationStep]:
    """Analyze an arrow chain using the contract's anchoring policy."""
    words = [word for word in _ARROW_RE.split(text) if word.strip()]
    if len(words) < 2:
        return []
    base = words[0]
    steps: list[TransformationStep] = []
    for index, right in enumerate(words[1:]):
        left = base if contract.chain_anchoring == "base_anchored" else words[index]
        step = analyze_pair(
            left,
            right,
            contract,
            base_word=base,
            source_chain=text,
            step_index=index,
        )
        if contract.chain_anchoring == "per_step_infer" and not verify_step(step):
            step = analyze_pair(
                base,
                right,
                contract,
                base_word=base,
                source_chain=text,
                step_index=index,
            )
        steps.append(step)
    return steps


def analyze_chain_with_registry(text: str, skill_id: str) -> list[TransformationStep]:
    """Resolve a skill contract, analyze the chain, and fail closed if unknown."""
    from skill.contract import contract_for_skill_id

    contract = contract_for_skill_id(skill_id)
    if contract is None:
        return []
    return analyze_chain(text, contract)


def infer_base_step_for_derived(
    derived_word: str, contract: TransformationContract
) -> TransformationStep | None:
    """Infer a truthful base-to-derived suffix step for a standalone target.

    This is used only when a source supplies a derived target without its base.
    Orthographic candidates are preferred and every candidate is replayed.
    """
    target = re.sub(r"[^a-z]", "", derived_word.casefold())
    for ending in sorted(contract.allowed_endings, key=len, reverse=True):
        if not target.endswith(ending) or len(target) <= len(ending) + 1:
            continue
        stem = target[: -len(ending)]
        candidates: list[str] = []
        if stem.endswith("i"):
            candidates.append(stem[:-1] + "y")
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            candidates.append(stem[:-1])
        candidates.append(stem + "e")
        candidates.append(stem)
        for base in candidates:
            step = analyze_pair(base, target, contract, base_word=base, source_chain=target)
            if verify_step(step):
                return step
    return None


def attach_transformations_to_source_items(
    source_items: list[_SourceItemT], skill_id: str
) -> list[_SourceItemT]:
    """Return source items with word chains enriched at the stage boundary.

    The loose ``object`` signature keeps this low-level module independent of
    ``skill.schema`` during model import. Runtime validation still occurs when
    each copied SourceItem and the enclosing LiteracySkillModel are built.
    """
    enriched: list[_SourceItemT] = []
    for item in source_items:
        if getattr(item, "item_type", None) != "word_chain":
            enriched.append(item)
            continue
        content = str(getattr(item, "content", ""))
        steps = analyze_chain_with_registry(content, skill_id)
        if not steps:
            # Ordinary word chains have a conservative, verified semantic
            # fallback. Unknown morphology/rule objectives do not.
            steps = analyze_chain_with_registry(content, "letter_chain")
        enriched.append(item.model_copy(update={"transformations": steps}))  # type: ignore[attr-defined]
    return enriched
