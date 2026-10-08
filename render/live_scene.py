"""On-demand text-free artwork: one combined visual gate per candidate."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from ai import openrouter
from ai.telemetry import stage
from companion.character_identity import CharacterIdentity
from render.design_spec import WorksheetDesignSpec
from render.scene_geometry import meaningful_page_fraction
from render.strategies import RenderContext
from theme.schema import ThemeConfig

SCENE_VERSION = "live_scene_v1"


class SceneGate(BaseModel):
    identity_ok: bool = Field(strict=True)
    supports_task: bool = Field(strict=True)
    no_text: bool = Field(strict=True)
    no_answers: bool = Field(strict=True)
    bounds: tuple[float, float, float, float]
    issues: list[str] = Field(default_factory=list)

    @property
    def approved(self) -> bool:
        x0, y0, x1, y1 = self.bounds
        return (
            self.identity_ok
            and self.supports_task
            and self.no_text
            and self.no_answers
            and not self.issues
            and 0 <= x0 < x1 <= 1
            and 0 <= y0 < y1 <= 1
            and (x1 - x0) * (y1 - y0) >= 0.55
        )


def _reference(identity: object | None) -> bytes | None:
    if not isinstance(identity, CharacterIdentity):
        return None
    root = Path(__file__).parents[1]
    for value in (
        identity.pose_reference_path,
        identity.canonical_reference_path,
        identity.base_image_path,
    ):
        if value and (root / value).is_file():
            return (root / value).read_bytes()
    return None


def scene_prompt(spec: WorksheetDesignSpec, theme: ThemeConfig, identity: object | None) -> str:
    character = (
        identity.character_block
        if isinstance(identity, CharacterIdentity)
        else "a friendly learner"
    )
    tasks = "; ".join(section.micro_goal for section in spec.sections)
    return (
        "Draw only a substantial instructional illustration, never a worksheet. "
        "Landscape 16:9; fill the image with the meaningful scene, calm white background. "
        f"Show {character} actively practising reading, writing or building words. "
        f"Learning goal: {spec.learning_goal}. Activities: {tasks}. "
        f"Theme environment: {theme.character_spec.scene_environment or theme.name}. "
        f"Theme costume: {theme.character_spec.body_description}. "
        "Preserve the reference character's face, hair and proportions. Theme clothing may "
        "replace the reference outfit; keep identifying motifs where possible. "
        "Use appropriate learning materials with abstract unmarked surfaces. "
        "NO text, letters, numbers, labels, practice answers, borders or worksheet boxes. "
        "Do not depict blank easels or a character merely posing; show an actual learning action."
    )


def judge_scene(png: bytes, reference: bytes | None, spec: WorksheetDesignSpec) -> SceneGate | None:
    prompt = (
        "Evaluate the LAST image as instructional artwork. The first image, if present, "
        "is the character reference. Compare stable face/hair/proportions; allow theme costumes. "
        f"Goal: {spec.learning_goal}. "
        "Check meaningful reading/writing/word-building action (not an unrelated portrait), "
        "no visible text/letters/numbers, no practice answers. Return the tight bounding box "
        "of meaningful artwork in normalized [left,top,right,bottom] coordinates. "
        "Missing identity reference means identity_ok=true, not invented identity evidence. "
        "Return ONLY JSON with booleans identity_ok, supports_task, no_text, no_answers, "
        "bounds (four numbers), and issues (array of strings). Any uncertainty must fail its check."
    )

    def validates(value: object) -> bool:
        try:
            SceneGate.model_validate(value)
            return True
        except ValueError:
            return False

    schema = SceneGate.model_json_schema()
    # Provider structured-output dialects commonly support homogeneous arrays,
    # not JSON Schema tuple prefixItems. Local Pydantic validation still fixes length.
    schema["properties"]["bounds"] = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 4,
        "maxItems": 4,
    }
    raw = openrouter.complete_json(
        prompt,
        images=([reference, png] if reference else [png]),
        role="vision",
        model_ids=_scene_judge_models(),
        max_tokens=512,
        validate=validates,
        json_schema=schema,
    )
    return SceneGate.model_validate(raw) if raw is not None else None


def _scene_judge_models() -> list[str]:
    return openrouter.stage_models("scene_judge", role="vision")


def generate_scene(context: RenderContext) -> str | None:
    """Keep provider fallback sequential per scene; callers parallelize independent scenes.

    Cache is repeat-request reuse, never a prerequisite for novel content. An image
    cannot enter it without a passing visual gate and a matching byte hash.
    """
    spec = context.design_spec
    theme = ThemeConfig.model_validate(context.theme)
    directory = context.artifacts_dir
    directory.mkdir(parents=True, exist_ok=True)
    prompt = scene_prompt(spec, theme, context.character_identity)
    reference = _reference(context.character_identity)
    key = hashlib.sha256(
        (
            SCENE_VERSION
            + prompt
            + json.dumps(openrouter.models("image"))
            + json.dumps(_scene_judge_models())
        ).encode()
        + (reference or b"")
    ).hexdigest()
    path = directory / "learning_scene.png"
    report_path = directory / "learning_scene.json"
    try:
        cached = json.loads(report_path.read_text())
        cached_gate = SceneGate.model_validate(cached["gate"])
        if (
            cached["key"] == key
            and cached["status"] == "approved"
            and cached_gate.approved
            and cached["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            return str(path)
    except (OSError, ValueError, KeyError, TypeError):
        pass

    attempts: list[dict[str, object]] = []
    try:
        budget = min(4, max(1, int(os.environ.get("WORKSHEET_SCENE_MAX_CANDIDATES", "2"))))
    except ValueError:
        budget = 2
    models = openrouter.models("image")[:budget]
    reason = "no OpenRouter key or artwork generation disabled"
    if openrouter.available() and os.environ.get("WORKSHEET_SKIP_ASSET_GEN") != "1":
        for model in models:
            started = time.perf_counter()
            with stage(f"scene_{spec.worksheet_number}"):
                try:
                    png = openrouter.generate_image(
                        prompt, reference, model=model, aspect_ratio="16:9"
                    )
                except openrouter.CredentialsUnavailableError:
                    reason = "OpenRouter credentials or credit unavailable"
                    break
                except Exception:
                    png = None
                try:
                    gate = judge_scene(png, reference, spec) if png else None
                except openrouter.CredentialsUnavailableError:
                    reason = "OpenRouter credentials or credit unavailable"
                    break
                except Exception:
                    gate = None
            attempts.append(
                {
                    "model": model,
                    "elapsed_s": time.perf_counter() - started,
                    "gate": gate.model_dump() if gate else None,
                }
            )
            if png and gate and gate.approved:
                try:
                    with Image.open(io.BytesIO(png)) as image:
                        image.verify()
                        width, height = image.size
                except (OSError, ValueError):
                    reason = "artwork is not a decodable image"
                    continue
                # Text remains vector; ensure artwork fills a substantial slot
                # and is not a thumbnail. Exact page-space check occurs in composition.
                if (
                    width < 800
                    or height < 450
                    or meaningful_page_fraction(width, height, gate.bounds)
                    < spec.learning_scene_min_area_fraction
                ):
                    reason = "artwork resolution or meaningful scene area too low"
                    continue
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(png)
                temporary.replace(path)
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "approved",
                            "key": key,
                            "sha256": hashlib.sha256(png).hexdigest(),
                            "gate": gate.model_dump(),
                            "attempts": attempts,
                        },
                        indent=2,
                    )
                )
                return str(path)
            reason = "artwork failed visual checks or provider unavailable"
    report_path.write_text(
        json.dumps({"status": "fallback", "reason": reason, "attempts": attempts}, indent=2)
    )
    if os.environ.get("WORKSHEET_ALLOW_PDF_FALLBACK") == "0":
        raise RuntimeError(f"Learning scene unavailable: {reason}")
    return None
