"""Private frozen inputs for rendering comparisons without re-planning content."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from adapt.approval import package_hash
from adapt.schema import AdaptedActivityModel
from companion.character_identity import CharacterIdentity
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel
from theme.schema import ThemeConfig


class FrozenRenderPackage(BaseModel):
    version: str = "frozen_render_v1"
    package_hash: str
    judged_package_hash: str | None
    approved: bool
    coverage_mode: Literal["photo_full", "lesson_objective"]
    skill: LiteracySkillModel
    profile: LearnerProfile
    theme: ThemeConfig
    identity: CharacterIdentity
    worksheets: list[AdaptedActivityModel]

    def verify(self) -> None:
        if self.version != "frozen_render_v1" or not self.worksheets:
            raise ValueError("Unsupported or empty frozen package")
        actual = package_hash(self.worksheets)
        if not self.approved or actual != self.package_hash or actual != self.judged_package_hash:
            raise ValueError("Replay requires affirmative approval bound to unchanged content")


def save_frozen_package(
    directory: Path,
    worksheets: list[AdaptedActivityModel],
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme: ThemeConfig,
    identity: CharacterIdentity,
    approved: bool,
    judged_hash: str | None,
    *,
    objective_mode: bool,
) -> None:
    package = FrozenRenderPackage(
        package_hash=package_hash(worksheets),
        judged_package_hash=judged_hash,
        approved=approved,
        coverage_mode="lesson_objective" if objective_mode else "photo_full",
        worksheets=worksheets,
        skill=skill,
        profile=profile,
        theme=theme,
        identity=identity,
    )
    (directory / "frozen_render_package.json").write_text(package.model_dump_json(indent=2))
