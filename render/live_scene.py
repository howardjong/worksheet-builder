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
from ai.run_limits import RunLimitExceededError, check_run_limits
from ai.telemetry import candidate, stage
from companion.character_identity import CharacterIdentity
from render.design_spec import WorksheetDesignSpec
from render.scene_geometry import meaningful_page_fraction
from render.strategies import RenderContext
from theme.schema import ThemeConfig

SCENE_VERSION = "live_scene_v2_action_contract"


class SceneAction(BaseModel):
    kind: str
    action: str
    props: str
    costume: str


def scene_action(spec: WorksheetDesignSpec, theme: ThemeConfig | None = None) -> SceneAction:
    """One declared dominant action per mini-worksheet, reused on continuation pages."""
    formats = [item.response_format for section in spec.sections for item in section.items]
    dominant = max(dict.fromkeys(formats), key=formats.count) if formats else "write"
    skill = spec.specific_skill.lower()
    if dominant not in {"read_aloud", "verbal"} and ("er_est" in skill or "compar" in skill):
        kind, action, props = (
            "compare",
            "pointing to the largest of three otherwise identical objects of increasing size",
            "three unlabelled objects arranged from small to large",
        )
    elif dominant == "sound_box" or "segment" in skill:
        kind, action, props = (
            "segment",
            "tapping a finger for each spoken sound",
            "blank sound tiles",
        )
    elif "blend" in skill or any(
        item.response_format == "sound_box" for section in spec.sections for item in section.items
    ):
        kind, action, props = (
            "blend",
            "pushing blank sound blocks together",
            "unmarked sound blocks",
        )
    elif dominant in {"read_aloud", "verbal"}:
        kind, action, props = (
            "read",
            "following a blank open book with a finger while reading aloud",
            "an open book with completely blank pages",
        )
    elif dominant == "circle":
        kind, action, props = (
            "choose",
            "pointing deliberately to one of several blank task cards",
            "blank task cards",
        )
    else:
        kind, action, props = (
            "write",
            "holding a pencil against a blank clipboard in a writing gesture",
            "a pencil and blank clipboard",
        )
    return SceneAction(
        kind=kind,
        action=action,
        props=props,
        costume=theme.character_spec.body_description
        if theme
        else "appropriate to the declared theme",
    )


class SceneGate(BaseModel):
    identity_ok: bool = Field(strict=True)
    supports_task: bool = Field(strict=True)
    action_ok: bool = Field(strict=True)
    outfit_ok: bool = Field(strict=True)
    child_safe: bool = Field(strict=True)
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
            and self.action_ok
            and self.outfit_ok
            and self.child_safe
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
    action = scene_action(spec, theme)
    return (
        "Draw only a substantial instructional illustration, never a worksheet. "
        "Landscape 16:9; fill the image with the meaningful scene, calm white background. "
        f"Show {character} {action.action}. Required props: {action.props}. "
        f"Learning goal: {spec.learning_goal}. Activities: {tasks}. "
        f"Theme environment: {theme.character_spec.scene_environment or theme.name}. "
        f"Theme costume: {theme.character_spec.body_description}. "
        "Preserve the reference character's face, hair and proportions. Theme clothing may "
        "replace the reference outfit; keep identifying motifs where possible. "
        "Use appropriate learning materials with abstract unmarked surfaces. "
        "NO text, letters, numbers, labels, practice answers, borders or worksheet boxes. "
        "Do not depict blank easels or a character merely posing; show an actual learning action."
    )


def judge_scene(
    png: bytes, reference: bytes | None, spec: WorksheetDesignSpec, theme: ThemeConfig | None = None
) -> SceneGate | None:
    action = scene_action(spec, theme)
    prompt = (
        "Evaluate the LAST image as instructional artwork. The first image, if present, "
        "is the character reference. Compare stable face/hair/proportions; allow theme costumes. "
        f"Goal: {spec.learning_goal}. "
        f"Required action: {action.action}. Props: {action.props}. Costume: {action.costume}. "
        "Check meaningful reading/writing/word-building action (not an unrelated portrait), "
        "no visible text/letters/numbers, no practice answers. Return the tight bounding box "
        "of meaningful artwork in normalized [left,top,right,bottom] coordinates. "
        "Check the exact declared action, appropriate outfit and child-safe calm imagery. "
        "Missing identity reference means identity_ok=false; identity cannot be verified. "
        "Return ONLY JSON with booleans identity_ok, supports_task, action_ok, outfit_ok, "
        "child_safe, no_text, no_answers, "
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
    gate = SceneGate.model_validate(raw) if raw is not None else None
    return gate.model_copy(update={"identity_ok": False}) if gate and not reference else gate


def _scene_judge_models() -> list[str]:
    return openrouter.stage_models("scene_judge", role="vision")


def generate_scene(context: RenderContext) -> str | None:
    """Keep provider fallback sequential per scene; callers parallelize independent scenes.

    Cache is repeat-request reuse, never a prerequisite for novel content. An image
    cannot enter it without a passing visual gate and a matching byte hash.
    """
    spec = context.design_spec
    check_run_limits()
    theme = ThemeConfig.model_validate(context.theme)
    directory = context.artifacts_dir
    directory.mkdir(parents=True, exist_ok=True)
    prompt = scene_prompt(spec, theme, context.character_identity)
    action = scene_action(spec, theme)
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

    def save_report(status: str, **extra: object) -> None:
        report_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "key": key,
                    "scene_version": SCENE_VERSION,
                    "action_contract": action.model_dump(),
                    "attempts": attempts,
                    **extra,
                },
                indent=2,
            )
        )

    try:
        budget = min(4, max(1, int(os.environ.get("WORKSHEET_SCENE_MAX_CANDIDATES", "2"))))
    except ValueError:
        budget = 2
    models = openrouter.models("image")[:budget]
    reason = "no OpenRouter key or artwork generation disabled"
    if openrouter.available() and os.environ.get("WORKSHEET_SKIP_ASSET_GEN") != "1":
        for model in models:
            check_run_limits()
            started = time.perf_counter()
            candidate_id = f"candidate_{len(attempts) + 1}"
            attempt: dict[str, object] = {
                "candidate_id": candidate_id,
                "model": model,
                "selected": False,
                "outcome": "provider_unavailable",
            }
            attempts.append(attempt)
            png: bytes | None = None
            with stage(f"scene_{spec.worksheet_number}"), candidate(candidate_id):
                try:
                    png = openrouter.generate_image(
                        prompt, reference, model=model, aspect_ratio="16:9"
                    )
                    if png:
                        candidate_path = directory / f"{candidate_id}.png"
                        candidate_path.write_bytes(png)
                        attempt.update(
                            image_path=candidate_path.name, sha256=hashlib.sha256(png).hexdigest()
                        )
                except RunLimitExceededError:
                    attempt["outcome"] = "run_limit_exceeded"
                    save_report("failed", reason="run limits exhausted")
                    raise
                except openrouter.CredentialsUnavailableError:
                    reason = "OpenRouter credentials or credit unavailable"
                    break
                except Exception:
                    png = None
                try:
                    gate = judge_scene(png, reference, spec, theme) if png else None
                except RunLimitExceededError:
                    attempt["outcome"] = "run_limit_exceeded"
                    save_report("failed", reason="run limits exhausted")
                    raise
                except openrouter.CredentialsUnavailableError:
                    reason = "OpenRouter credentials or credit unavailable"
                    break
                except Exception:
                    gate = None
            attempt.update(
                elapsed_s=time.perf_counter() - started,
                gate=gate.model_dump() if gate else None,
                outcome="gate_rejected" if png else "provider_unavailable",
            )
            # Persist each paid outcome before another candidate can be admitted.
            save_report("pending")
            if png and gate and gate.approved:
                try:
                    with Image.open(io.BytesIO(png)) as image:
                        image.verify()
                        width, height = image.size
                except (OSError, ValueError):
                    reason = "artwork is not a decodable image"
                    attempt["outcome"] = "invalid_image"
                    save_report("pending", reason=reason)
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
                    attempt["outcome"] = "geometry_rejected"
                    save_report("pending", reason=reason)
                    continue
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(png)
                temporary.replace(path)
                attempt.update(selected=True, outcome="approved")
                save_report(
                    "approved", sha256=hashlib.sha256(png).hexdigest(), gate=gate.model_dump()
                )
                return str(path)
            reason = "artwork failed visual checks or provider unavailable"
    save_report("fallback", reason=reason)
    if os.environ.get("WORKSHEET_ALLOW_PDF_FALLBACK") == "0":
        raise RuntimeError(f"Learning scene unavailable: {reason}")
    return None
