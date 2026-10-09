"""On-demand text-free artwork: one combined visual gate per candidate."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from pathlib import Path

from PIL import Image, ImageChops
from pydantic import BaseModel, Field

from ai import openrouter
from ai.run_limits import RunLimitExceededError, check_run_limits
from ai.telemetry import candidate, stage
from companion.character_identity import CharacterIdentity
from render.design_spec import WorksheetDesignSpec
from render.scene_geometry import meaningful_page_fraction
from render.strategies import RenderContext
from theme.schema import ThemeConfig

SCENE_VERSION = "live_scene_v5_relevant_procedure"
HAIKU_MODEL = "anthropic/claude-haiku-5.5"
DECISIONS_MODEL = "openai/gpt-6-luna-decisions"
# Owner-reviewed trial art was relevant at 0.40 task / 0.42 action / 0.90
# identity, while clear wrong-action/outfit controls scored 0. These are trial
# cutoffs from a tiny labeled set, not production-calibrated accuracy estimates.
PRIOR_DECISION_THRESHOLDS = {
    "identity_ok": 0.85,
    "supports_task": 0.35,
    "action_ok": 0.35,
    "outfit_ok": 0.85,
    "child_safe": 0.95,
    "no_text": 0.95,
    "answer_free": 0.95,
    "meaningful_area": 0.95,
}
# Seven semantic checks block approval. The estimated pixel-coverage probability
# is diagnostic only: confidence in a statement is not a geometric measurement.
DECISION_THRESHOLDS = {
    name: cutoff for name, cutoff in PRIOR_DECISION_THRESHOLDS.items() if name != "meaningful_area"
}
AREA_POLICY = (
    "foreground bounding extent >=55%; printed extent >=spec minimum; model coverage advisory"
)


class SceneAction(BaseModel):
    kind: str
    action: str
    props: str
    costume: str
    section_number: int = 1


def _legacy_scene_action(
    spec: WorksheetDesignSpec, theme: ThemeConfig | None = None
) -> SceneAction:
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


def scene_action(
    spec: WorksheetDesignSpec, theme: ThemeConfig | None = None, *, prior_rubric: bool = False
) -> SceneAction:
    """Model one concrete learner procedure; bind its illustration to that section."""
    if not spec.sections:
        return _legacy_scene_action(spec, theme)
    # Prefer word manipulation when present; otherwise illustrate the first task,
    # rather than letting a package-wide skill override what the child is doing.
    index = next(
        (
            number
            for number, section in enumerate(spec.sections)
            if any(word in section.micro_goal.lower() for word in ("build", "chain", "segment"))
        ),
        0,
    )
    section = spec.sections[index]
    formats = [item.response_format for item in section.items]
    dominant = max(dict.fromkeys(formats), key=formats.count) if formats else "write"
    goal = section.micro_goal.lower()
    if "build" in goal or "chain" in goal:
        kind, action, props = (
            "build",
            "moving one blank word-part tile to join another, demonstrating word building",
            "two adjacent groups of unmarked word-part tiles and a spare tile",
        )
    elif dominant == "sound_box" or "segment" in goal:
        kind, action, props = (
            "segment",
            "tapping one blank sound tile at a time while speaking",
            "a row of blank sound tiles",
        )
    elif dominant in {"read_aloud", "verbal"}:
        passage = any(len(item.content.split()) > 3 for item in section.items)
        kind, action, props = (
            "read",
            "tracking a blank book line with a finger while reading aloud"
            if passage
            else "tracking successive blank word cards with a finger while reading aloud",
            "an open blank book" if passage else "a row of blank word cards",
        )
    elif dominant == "circle":
        kind, action, props = (
            "choose",
            "using a pencil to circle one blank choice card among several"
            if prior_rubric
            else "holding a pencil above three blank choice cards while considering them, "
            "without touching, circling or marking any card",
            "a pencil and three blank choice cards",
        )
    else:
        kind, action, props = (
            "write",
            "copying from a blank model card onto a blank writing line with a pencil",
            "a blank model card, blank practice paper and pencil",
        )
    return SceneAction(
        kind=kind,
        action=action,
        props=props,
        costume=theme.character_spec.body_description if theme else "appropriate to the theme",
        section_number=index + 1,
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
    probabilities: dict[str, float] = Field(default_factory=dict)

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


def judge_reference(identity: object | None) -> bytes | None:
    """Immutable identity authority for gate evaluation.

    Always resolves exactly what ``_reference()`` resolves today. Changing a
    generation reference pack must never change these bytes or their hash:
    scenes are always judged against the original customized character, never
    a derived anchor, crop, or pose variant.
    """
    return _reference(identity)


def generation_reference_pack(
    identity: object | None, extra: tuple[bytes, ...] = ()
) -> list[bytes]:
    """Ordered reference pack for image generation: primary first, then extras.

    The primary is the same original ``_reference()`` returns; ``extra`` holds
    experiment inputs such as a face/hair crop derived from original bytes.
    Order is significant: prompts must bind ordinal phrases ("first image")
    to this order.
    """
    primary = _reference(identity)
    pack = [primary] if primary else []
    pack.extend(extra)
    return pack


def derive_face_crop(
    png: bytes, rect: tuple[float, float, float, float]
) -> tuple[bytes, dict[str, object]]:
    """Crop a fractional rect (x0, y0, x1, y1) from original reference bytes.

    No generative retouching: a straight pixel crop of the supplied bytes.
    Returns the cropped PNG and its provenance (rect, source hash, size).
    """
    import hashlib

    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        image.load()
        width, height = image.size
        x0, y0, x1, y1 = rect
        box = (
            int(x0 * width),
            int(y0 * height),
            int(x1 * width),
            int(y1 * height),
        )
        cropped = image.crop(box)
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        out = buffer.getvalue()
    provenance: dict[str, object] = {
        "rect": [x0, y0, x1, y1],
        "source_sha256": hashlib.sha256(png).hexdigest(),
        "crop_sha256": hashlib.sha256(out).hexdigest(),
        "crop_size": [cropped.size[0], cropped.size[1]],
        "source_size": [width, height],
    }
    return out, provenance


def scene_prompt(
    spec: WorksheetDesignSpec,
    theme: ThemeConfig,
    identity: object | None,
    *,
    legacy: bool = False,
    prior_rubric: bool = False,
) -> str:
    character = (
        identity.character_block
        if isinstance(identity, CharacterIdentity)
        else "a friendly learner"
    )
    tasks = "; ".join(section.micro_goal for section in spec.sections)
    action = (
        _legacy_scene_action(spec, theme)
        if legacy
        else scene_action(spec, theme, prior_rubric=prior_rubric)
    )
    prompt = (
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
    if not legacy and spec.sections:
        section = spec.sections[action.section_number - 1]
        prompt += (
            f" Focus ONLY on section {action.section_number}: {section.micro_goal}. "
            "Model the procedure the child should perform in this section, not generic posing "
            "or a comparison action just because the overall lesson includes comparisons. "
            "Do not illustrate or reveal any of the student's target words or answers."
        )
    return prompt


def scene_rubric(
    spec: WorksheetDesignSpec, theme: ThemeConfig | None = None
) -> tuple[str, dict[str, str]]:
    """Shared semantic criteria for Luna and the structured vision comparison."""
    action = scene_action(spec, theme)
    questions = {
        "identity_ok": (
            "Does the LAST image preserve the FIRST reference's face, hair and proportions? "
            "Theme clothing may change."
        ),
        "supports_task": (
            "Does the LAST image clearly support the declared learning goal and activities "
            "rather than being decorative posing?"
        ),
        "action_ok": (
            "Does the LAST image depict a recognizable version of the required learning action "
            "with its required props? Minor pose details need not be perfect."
        ),
        "outfit_ok": "Is the character dressed appropriately for the declared theme costume?",
        "child_safe": "Is the image safe, calm and appropriate for a child aged five to eight?",
        "no_text": (
            "Is the LAST image entirely free of visible letters, words, numbers or labels?"
        ),
        "answer_free": (
            "Is the LAST image free of any specific completed answer to a child practice item? "
            "Answer yes only when no target word, solved item or marked correct choice is "
            "visible. Blank or unmarked learning materials and general instructional scenes "
            "are answer-free. If uncertain, answer no."
        ),
        "meaningful_area": (
            "Does the actual learning character/action/material (excluding background/"
            "decorations) occupy at least 55% of the LAST image?"
        ),
    }
    section_goal = (
        spec.sections[action.section_number - 1].micro_goal if spec.sections else spec.learning_goal
    )
    state = (
        "Evaluate the LAST image. FIRST image is canonical character reference. "
        "Uncertainty or inability to verify must count as criterion not satisfied. "
        f"Goal: {spec.learning_goal}. Required action: {action.action}. "
        f"Props: {action.props}. Costume: {action.costume}. "
        f"Illustrated section: {section_goal}. "
        "Judge relevance and a recognizable procedure, not artistic perfection. "
        "The character may wear a theme costume instead of reference clothes."
    )
    return state, questions


def judge_scene(
    png: bytes,
    reference: bytes | None,
    spec: WorksheetDesignSpec,
    theme: ThemeConfig | None = None,
    *,
    backend: str | None = None,
    model_ids: list[str] | None = None,
) -> SceneGate | None:
    backend = backend or os.environ.get("WORKSHEET_SCENE_GATE_BACKEND", "decisions")
    gate_models = model_ids if model_ids is not None else _scene_judge_models(backend)
    if backend not in {"decisions", "vision"} or not gate_models:
        raise ValueError("Unknown scene gate backend or empty model list")
    if backend == "decisions" and gate_models != [DECISIONS_MODEL]:
        raise ValueError("Composed Decisions gates require the verified image-capable Luna model")
    state, questions = scene_rubric(spec, theme)
    if backend == "decisions":
        if not reference:
            return None
        probabilities = openrouter.decide_yes_no(
            state, questions, model=gate_models[0], images=[reference, png]
        )
        if probabilities is None or set(probabilities) != set(questions):
            return None
        passed = {
            name: probabilities[name] >= cutoff for name, cutoff in DECISION_THRESHOLDS.items()
        }
        passed["no_answers"] = passed.pop("answer_free")
        with Image.open(io.BytesIO(png)) as image:
            rgba = image.convert("RGBA")
            white = Image.new("RGBA", rgba.size, "white")
            rgb = Image.alpha_composite(white, rgba).convert("RGB")
            mask = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white"))
            bounds = mask.convert("L").point(lambda value: 255 if value > 18 else 0).getbbox()
            width, height = rgb.size
        normalized = (
            (bounds[0] / width, bounds[1] / height, bounds[2] / width, bounds[3] / height)
            if bounds
            else (0.0, 0.0, 0.0, 0.0)
        )
        return SceneGate(
            **passed,
            bounds=normalized,
            issues=[
                name + " below provisional threshold" for name, value in passed.items() if not value
            ],
            probabilities=probabilities,
        )
    prompt = (
        state + "\n" + json.dumps(questions) + "\n"
        "Return ONLY JSON with booleans identity_ok, supports_task, action_ok, outfit_ok, "
        "child_safe, no_text, no_answers (use the answer_free criterion), "
        "bounds (four numbers), and issues (short concrete blocking defects only). "
        "Estimate the tight bounding extent around the learning character and materials, "
        "excluding background and decorations, in normalized [left,top,right,bottom] "
        "coordinates. This is an extent, NOT painted-pixel coverage; white gaps are allowed. "
        "The meaningful_area probability/coverage question is advisory and must NOT add an "
        "issue or change a semantic check. No required check may pass if it cannot be verified. "
        "Missing identity reference means identity_ok=false. "
        "Relevant, recognizable artwork is enough; cosmetic imperfections are not defects."
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
        model_ids=gate_models,
        max_tokens=768,
        validate=validates,
        json_schema=schema,
        reasoning_effort=os.environ.get(
            "WORKSHEET_OPENROUTER_SCENE_JUDGE_REASONING_EFFORT",
            "low" if gate_models == [HAIKU_MODEL] else None,
        ),
    )
    gate = SceneGate.model_validate(raw) if raw is not None else None
    return gate.model_copy(update={"identity_ok": False}) if gate and not reference else gate


def _scene_judge_models(backend: str | None = None) -> list[str]:
    backend = backend or os.environ.get("WORKSHEET_SCENE_GATE_BACKEND", "decisions")
    if backend == "decisions":
        model = os.environ.get("WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL", DECISIONS_MODEL)
        if model != DECISIONS_MODEL:
            raise ValueError(
                "Composed Decisions gates require the verified image-capable Luna model"
            )
        return [model]
    if backend != "vision":
        raise ValueError("Unknown scene gate backend")
    return openrouter.stage_models("scene_judge", role="vision")


def _scene_key(
    prompt: str,
    reference: bytes | None,
    *,
    legacy: bool = False,
    prior_calibration: bool = False,
    prior_rubric: bool = False,
) -> str:
    version = (
        "live_scene_v2_action_contract"
        if legacy
        else "live_scene_v3_decisions"
        if prior_calibration
        else "live_scene_v4_luna_calibrated"
        if prior_rubric
        else SCENE_VERSION
    )
    return hashlib.sha256(
        (
            version
            + prompt
            + json.dumps(openrouter.models("image"))
            + json.dumps(
                openrouter.stage_models("scene_judge", role="vision")
                if legacy
                else _scene_judge_models()
            )
            + (
                ""
                if legacy
                else json.dumps(
                    0.95
                    if prior_calibration
                    else PRIOR_DECISION_THRESHOLDS
                    if prior_rubric
                    else {
                        "thresholds": DECISION_THRESHOLDS,
                        "area_policy": AREA_POLICY,
                        "effort": os.environ.get(
                            "WORKSHEET_OPENROUTER_SCENE_JUDGE_REASONING_EFFORT",
                            "low"
                            if _scene_judge_models() == [HAIKU_MODEL]
                            else os.environ.get("WORKSHEET_OPENROUTER_REASONING_EFFORT", "medium"),
                        ),
                    }
                )
            )
        ).encode()
        + (reference or b"")
    ).hexdigest()


def _approved_scene(directory: Path, key: str, spec: WorksheetDesignSpec) -> str | None:
    path = directory / "learning_scene.png"
    try:
        report = json.loads((directory / "learning_scene.json").read_text())
        gate = SceneGate.model_validate(report["gate"])
        png = path.read_bytes()
        if (
            report["key"] != key
            or report["status"] != "approved"
            or not gate.approved
            or report["sha256"] != hashlib.sha256(png).hexdigest()
        ):
            return None
        with Image.open(io.BytesIO(png)) as image:
            width, height = image.size
            image.verify()
        if (
            width < 800
            or height < 450
            or meaningful_page_fraction(width, height, gate.bounds)
            < spec.learning_scene_min_area_fraction
        ):
            return None
        return str(path)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load_approved_scene(context: RenderContext) -> str | None:
    """Read an unchanged gated scene without any inference or regeneration fallback."""
    theme = ThemeConfig.model_validate(context.theme)
    try:
        report = json.loads((context.artifacts_dir / "learning_scene.json").read_text())
    except (OSError, ValueError):
        return None
    version = report.get("scene_version")
    if version not in {
        SCENE_VERSION,
        "live_scene_v3_decisions",
        "live_scene_v4_luna_calibrated",
        "live_scene_v2_action_contract",
    }:
        return None
    prompt = scene_prompt(
        context.design_spec,
        theme,
        context.character_identity,
        legacy=version == "live_scene_v2_action_contract",
        prior_rubric=version in {"live_scene_v3_decisions", "live_scene_v4_luna_calibrated"},
    )
    key = _scene_key(
        prompt,
        _reference(context.character_identity),
        legacy=version == "live_scene_v2_action_contract",
        prior_calibration=version == "live_scene_v3_decisions",
        prior_rubric=version == "live_scene_v4_luna_calibrated",
    )
    return _approved_scene(context.artifacts_dir, key, context.design_spec)


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
    key = _scene_key(prompt, reference)
    path = directory / "learning_scene.png"
    report_path = directory / "learning_scene.json"
    if cached := _approved_scene(directory, key, spec):
        return cached

    attempts: list[dict[str, object]] = []

    def save_report(status: str, **extra: object) -> None:
        report_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "key": key,
                    "scene_version": SCENE_VERSION,
                    "gate_models": _scene_judge_models(),
                    "gate_backend": os.environ.get("WORKSHEET_SCENE_GATE_BACKEND", "decisions"),
                    "decision_thresholds": (
                        DECISION_THRESHOLDS
                        if os.environ.get("WORKSHEET_SCENE_GATE_BACKEND", "decisions")
                        == "decisions"
                        else None
                    ),
                    "area_policy": AREA_POLICY,
                    "bounds_source": (
                        "local_nonwhite_foreground_extent"
                        if os.environ.get("WORKSHEET_SCENE_GATE_BACKEND", "decisions")
                        == "decisions"
                        else "vision_semantic_extent"
                    ),
                    "advisory_checks": ["meaningful_area"],
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
