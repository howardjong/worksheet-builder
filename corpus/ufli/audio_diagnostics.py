"""Controlled probe harness for UFLI audio root-cause analysis."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

from corpus.ufli.audio_companion import (
    _BUNDLE_DIR,
    _PRONUNCIATION_LEXICON,
    _VOICE_PROFILES,
    _audio_settings,
    _clause_pause_only_tts,
    _elevenlabs_api_key,
    _ensure_parent,
    _load_lessons,
    _request_elevenlabs_audio,
    _timestamp,
    load_audio_bundles,
    load_pronunciation_lexicon,
    load_voice_profiles,
)
from corpus.ufli.audio_companion_schema import (
    AudioClipDefinition,
    AudioClipKind,
    AudioInputFormat,
    AudioJudgeClipResult,
    AudioProbeFinding,
    AudioProbeRunSummary,
    AudioProbeVariant,
    AudioSynthesisProvider,
    AudioVoiceSettings,
    GoogleCloudTtsSettings,
    LessonAudioBundle,
    ProbeAssessment,
    PronunciationLexicon,
    VoiceProfile,
)
from corpus.ufli.audio_judge import DEFAULT_JUDGE_MODEL, _judge_clip_with_gemini
from corpus.ufli.extract import LessonContent
from rag.client import get_rag_client

_DEFAULT_PROBE_SEGMENTS = (
    "lesson_001_phoneme_01_a",
    "lesson_014_review",
    "lesson_014_passage_sentence_03",
    "lesson_095_passage_full",
)
_GOOGLE_CHIRP3_LEDA = "en-US-Chirp3-HD-Leda"
_GEMINI_TTS_LEDA = "Leda"
_GOOGLE_TTS_REGIONS = {
    "global",
    "us",
    "eu",
    "asia-southeast1",
    "europe-west2",
    "asia-northeast1",
}
_GOOGLE_SPEAKING_RATE_BY_CLIP: dict[AudioClipKind, float] = {
    "lesson_instruction": 0.85,
    "phoneme_model": 0.65,
    "word_model": 0.78,
    "passage_sentence": 0.85,
    "passage_full": 0.85,
    "review": 0.85,
}


def run_audio_probe_matrix(
    data_dir: str = "data/ufli",
    voice_profile: str | None = None,
    segment_ids: list[str] | None = None,
    output_dir: str | None = None,
    live: bool = False,
    judge: bool = False,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    provider_scope: str = "elevenlabs",
    google_voice_name: str = _GOOGLE_CHIRP3_LEDA,
    google_region: str | None = None,
    google_speaking_rate: float | None = None,
    google_model_name: str = "",
    google_style_prompt: str = "",
    google_sample_rate_hz: int = 0,
    google_volume_gain_db: float = 0.0,
) -> AudioProbeRunSummary:
    """Generate controlled variants to separate input-shaping issues from TTS limits."""
    if judge and not live:
        raise RuntimeError("Audio probes must be live-generated before they can be judged")
    if provider_scope not in {"elevenlabs", "google", "both"}:
        raise ValueError(f"Unknown provider_scope: {provider_scope}")

    base = Path(data_dir)
    companion_dir = base / "companion"
    bundles = load_audio_bundles(companion_dir / _BUNDLE_DIR)
    if not bundles:
        raise RuntimeError("No built lesson bundles found. Run build-audio first.")

    lessons = {lesson.lesson_id: lesson for lesson in _load_lessons(base / "normalized.jsonl")}
    voice_catalog = load_voice_profiles(companion_dir / _VOICE_PROFILES)
    selected_voice_name = voice_profile or voice_catalog.default_profile
    if selected_voice_name not in voice_catalog.profiles:
        raise ValueError(f"Unknown voice profile: {selected_voice_name}")
    selected_voice = voice_catalog.profiles[selected_voice_name]
    lexicon = load_pronunciation_lexicon(companion_dir / _PRONUNCIATION_LEXICON)
    google_settings: GoogleCloudTtsSettings | None = None
    if provider_scope in {"google", "both"}:
        google_settings = _google_canary_settings(
            voice_name=google_voice_name,
            region=google_region,
            speaking_rate=google_speaking_rate,
            model_name=google_model_name,
            style_prompt=google_style_prompt,
            sample_rate_hz=google_sample_rate_hz,
            volume_gain_db=google_volume_gain_db,
        )

    segment_map = _selected_segments(
        bundles=bundles,
        segment_ids=segment_ids or list(_DEFAULT_PROBE_SEGMENTS),
    )
    generated_at = _timestamp()
    run_dir = (
        Path(output_dir)
        if output_dir is not None
        else companion_dir / "diagnostics" / generated_at
    )
    if output_dir is None:
        run_dir = companion_dir / "diagnostics" / generated_at
    run_dir.mkdir(parents=True, exist_ok=True)

    variants: list[AudioProbeVariant] = []
    for source_segment_id, (bundle, clip) in segment_map.items():
        variants.extend(
            _build_probe_variants(
                bundle=bundle,
                clip=clip,
                voice_profile=selected_voice,
                lexicon=lexicon,
                provider_scope=provider_scope,
                google_settings=google_settings,
            )
        )

    if live:
        api_key = ""
        if provider_scope in {"elevenlabs", "both"}:
            api_key = _elevenlabs_api_key()
            if not api_key:
                raise RuntimeError(
                    "ELEVENLABS_API_KEY is required for live "
                    "ElevenLabs probe generation"
                )
        for variant in variants:
            audio_bytes = _synthesize_probe_variant(
                variant=variant,
                voice_profile=selected_voice,
                api_key=api_key,
            )
            target_path = run_dir / variant.audio_path
            _ensure_parent(target_path)
            target_path.write_bytes(audio_bytes)
            variant.generation_status = "generated"

    if judge:
        client = get_rag_client()
        for variant in variants:
            if variant.generation_status != "generated":
                continue
            bundle, source_clip = segment_map[variant.source_segment_id]
            lesson = lessons[source_clip.lesson_id]
            variant.judge_result = _judge_probe_variant(
                client=client,
                judge_model=judge_model,
                lesson=lesson,
                bundle=bundle,
                source_clip=source_clip,
                variant=variant,
                run_dir=run_dir,
            )

    findings = _derive_probe_findings(variants)
    summary = AudioProbeRunSummary(
        generated_at=generated_at,
        output_dir=str(run_dir),
        data_dir=str(base),
        voice_profile=selected_voice.name,
        judge_model=judge_model if judge else "",
        live=live,
        judged=judge,
        segment_ids=list(segment_map),
        variant_count=len(variants),
        findings=findings,
        variants=variants,
    )
    _write_probe_summary(run_dir / "probe_summary.json", summary)
    _write_probe_results_jsonl(run_dir / "probe_results.jsonl", variants)
    _write_probe_report(run_dir / "probe_report.md", summary)
    return summary


def _selected_segments(
    bundles: list[LessonAudioBundle],
    segment_ids: list[str],
) -> dict[str, tuple[LessonAudioBundle, AudioClipDefinition]]:
    index: dict[str, tuple[LessonAudioBundle, AudioClipDefinition]] = {}
    for bundle in bundles:
        for clip in bundle.clips:
            index[clip.segment_id] = (bundle, clip)

    selected: dict[str, tuple[LessonAudioBundle, AudioClipDefinition]] = {}
    for segment_id in segment_ids:
        if segment_id not in index:
            raise ValueError(f"Unknown segment_id for audio probe: {segment_id}")
        selected[segment_id] = index[segment_id]
    return selected


def _build_probe_variants(
    bundle: LessonAudioBundle,
    clip: AudioClipDefinition,
    voice_profile: VoiceProfile,
    lexicon: PronunciationLexicon,
    provider_scope: str,
    google_settings: GoogleCloudTtsSettings | None,
) -> list[AudioProbeVariant]:
    variants: list[AudioProbeVariant] = []

    def add_variant(
        variant_family: str,
        hypothesis: str,
        tts_text: str,
        model_id: str,
        audio_settings: AudioVoiceSettings | GoogleCloudTtsSettings,
        *,
        provider: AudioSynthesisProvider = "elevenlabs",
        provider_input: str | None = None,
        input_format: AudioInputFormat = "text",
    ) -> None:
        variant_id = f"{clip.segment_id}__{variant_family}__{model_id}"
        variants.append(
            AudioProbeVariant(
                source_segment_id=clip.segment_id,
                variant_id=variant_id,
                lesson_id=clip.lesson_id,
                lesson_number=clip.lesson_number,
                segment_type=clip.segment_type,
                variant_family=variant_family,
                hypothesis=hypothesis,
                voice_profile=voice_profile.name,
                provider=provider,
                model_id=model_id,
                transcript_text=clip.transcript_text,
                tts_text=tts_text,
                provider_input=provider_input or tts_text,
                input_format=input_format,
                audio_settings=audio_settings,
                audio_path=f"audio/{clip.segment_id}/{variant_id}.mp3",
            )
        )

    if provider_scope in {"elevenlabs", "both"}:
        settings = _audio_settings(voice_profile, clip.segment_type)
        add_variant(
            "current_pipeline",
            "Current pipeline text with the default model.",
            clip.tts_text,
            voice_profile.default_model,
            settings,
        )
        add_variant(
            "current_pipeline",
            "Current pipeline text with the fallback model to isolate model behavior.",
            clip.tts_text,
            voice_profile.fallback_model,
            settings,
        )

        if clip.segment_type in {"lesson_instruction", "review"}:
            add_variant(
                "exact_transcript",
                "Remove pause shaping to test whether the input pacing "
                "markup is helping or hurting.",
                clip.transcript_text,
                voice_profile.default_model,
                settings,
            )
        elif clip.segment_type in {"passage_sentence", "passage_full"}:
            add_variant(
                "exact_transcript",
                "Use exact transcript text with no added pause shaping.",
                clip.transcript_text,
                voice_profile.default_model,
                settings,
            )
            add_variant(
                "clause_pause_only",
                "Use punctuation-only clause pauses without mid-sentence inserted pauses.",
                _clause_pause_only_tts(clip.transcript_text),
                voice_profile.default_model,
                settings,
            )
        elif clip.segment_type == "phoneme_model":
            add_variant(
                "approved_phoneme",
                "Use the generic approved phoneme wording instead of the modeled override.",
                _approved_phoneme_tts(bundle, clip, lexicon),
                voice_profile.default_model,
                settings,
            )

    if provider_scope in {"google", "both"} and google_settings is not None:
        google_clip_settings = _google_settings_for_clip(google_settings, clip.segment_type)
        controlled_text = _google_markup_from_tts_text(
            clip.tts_text,
            clip.segment_type,
            google_clip_settings,
        )
        google_input_format: AudioInputFormat = (
            "text" if google_clip_settings.model_name.startswith("gemini-2.5-") else "markup"
        )
        google_label = (
            f"{google_settings.model_name} / {google_settings.voice_name}"
            if google_settings.model_name
            else google_settings.voice_name
        )
        add_variant(
            "current_pipeline",
            f"Current pipeline text translated into Google markup for {google_label}.",
            clip.tts_text,
            google_settings.voice_name,
            google_clip_settings,
            provider="google_cloud_tts",
            provider_input=controlled_text,
            input_format=google_input_format,
        )
        if clip.segment_type in {
            "lesson_instruction",
            "review",
            "passage_sentence",
            "passage_full",
        }:
            add_variant(
                "exact_transcript",
                f"Exact transcript on {google_label} without provider-specific pause markup.",
                clip.transcript_text,
                google_settings.voice_name,
                google_clip_settings,
                provider="google_cloud_tts",
                provider_input=clip.transcript_text,
                input_format="text",
            )

    deduped: list[AudioProbeVariant] = []
    seen: set[tuple[str, str, str]] = set()
    for variant in variants:
        key = (variant.provider, variant.model_id, variant.provider_input or variant.tts_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def _approved_phoneme_tts(
    bundle: LessonAudioBundle,
    clip: AudioClipDefinition,
    lexicon: PronunciationLexicon,
) -> str:
    grapheme_key = ""
    phoneme_key = ""
    for target in clip.pronunciation_targets:
        if target.startswith("grapheme:"):
            grapheme_key = target.split(":", 1)[1]
        if target.startswith("phoneme:"):
            phoneme_key = target.split(":", 1)[1]
    grapheme = lexicon.graphemes[grapheme_key]
    phoneme = lexicon.phonemes[phoneme_key]
    example_word = grapheme.anchor_word or (bundle.word_targets[0] if bundle.word_targets else "")
    parts = [f"{grapheme.approved_tts_text}.", f"{phoneme.approved_tts_text}."]
    if example_word:
        parts.append(f"As in {example_word}.")
    return " ".join(parts)

def _synthesize_probe_variant(
    variant: AudioProbeVariant,
    voice_profile: VoiceProfile,
    api_key: str,
) -> bytes:
    if variant.provider == "google_cloud_tts":
        settings = variant.audio_settings
        if not isinstance(settings, GoogleCloudTtsSettings):
            raise TypeError("google_cloud_tts variants require GoogleCloudTtsSettings")
        return _request_google_cloud_tts_audio(
            text=variant.provider_input or variant.tts_text,
            input_format=variant.input_format,
            settings=settings,
        )

    probe_profile = voice_profile.model_copy(deep=True)
    settings = variant.audio_settings
    if not isinstance(settings, AudioVoiceSettings):
        raise TypeError("elevenlabs variants require AudioVoiceSettings")
    probe_profile.clip_settings[variant.segment_type] = settings
    return _request_elevenlabs_audio(
        text=variant.provider_input or variant.tts_text,
        audio_type=variant.segment_type,
        voice_profile=probe_profile,
        api_key=api_key,
        seed=_probe_seed(variant.variant_id),
        model_id=variant.model_id,
    )


def _judge_probe_variant(
    client: object,
    judge_model: str,
    lesson: LessonContent,
    bundle: LessonAudioBundle,
    source_clip: AudioClipDefinition,
    variant: AudioProbeVariant,
    run_dir: Path,
) -> AudioJudgeClipResult:
    probe_clip = source_clip.model_copy(deep=True)
    probe_clip.segment_id = variant.variant_id
    probe_clip.transcript_text = variant.transcript_text
    probe_clip.tts_text = variant.tts_text
    probe_clip.audio_path = variant.audio_path
    probe_clip.voice_profile = variant.voice_profile
    probe_clip.speaker = variant.voice_profile
    return _judge_clip_with_gemini(
        client=client,
        judge_model=judge_model,
        lesson=lesson,
        bundle=bundle,
        clip=probe_clip,
        companion_dir=run_dir,
    )


def _derive_probe_findings(variants: list[AudioProbeVariant]) -> list[AudioProbeFinding]:
    grouped: dict[str, list[AudioProbeVariant]] = defaultdict(list)
    for variant in variants:
        grouped[variant.source_segment_id].append(variant)

    findings: list[AudioProbeFinding] = []
    for source_segment_id, group in grouped.items():
        ranked = sorted(group, key=_variant_rank, reverse=True)
        best = ranked[0]
        current_default = next(
            (variant for variant in group if variant.variant_family == "current_pipeline"),
            None,
        )
        text_variants = _best_ranked_variant(
            variant
            for variant in group
            if current_default is not None
            and variant.variant_id != current_default.variant_id
            and variant.model_id == current_default.model_id
            and variant.tts_text != current_default.tts_text
        )
        model_variants = _best_ranked_variant(
            variant
            for variant in group
            if current_default is not None
            and variant.variant_id != current_default.variant_id
            and variant.tts_text == current_default.tts_text
            and variant.model_id != current_default.model_id
        )

        cause: ProbeAssessment = "mixed_or_inconclusive"
        evidence: list[str] = []
        next_step = "Inspect the best-scoring variant and rerun a narrower comparison."
        current_rank = _variant_rank(current_default)
        text_improves = text_variants is not None and _variant_rank(text_variants) > current_rank
        model_improves = model_variants is not None and _variant_rank(model_variants) > current_rank

        if text_improves and model_improves:
            evidence.append(
                "Both a same-model text change and a same-text model change "
                "outperformed the current pipeline variant."
            )
            next_step = (
                "Treat this clip as mixed: simplify the script and compare "
                "models or voices before scaling."
            )
        elif text_improves:
            cause = "pipeline_input_problem"
            evidence.append(
                "A same-model text variant outperformed the current pipeline "
                "text."
            )
            next_step = (
                "Refine transcript shaping for this clip family before testing "
                "other voices."
            )
        elif model_improves:
            cause = "model_or_voice_limitation"
            evidence.append(
                "The same text performed better when only the model path changed."
            )
            next_step = "Compare models or voices before changing the lesson content further."
        elif current_default and current_default.judge_result is not None and (
            current_default.judge_result.blocker
            or current_default.judge_result.recommendation != "use"
        ):
            cause = "model_or_voice_limitation"
            evidence.append(
                "The current pipeline variant remained the best option, but it still "
                "failed the instructional gate."
            )
            next_step = (
                "Compare a different voice or provider before spending more time "
                "on input shaping for this clip."
            )
        elif current_default and best.variant_id == current_default.variant_id:
            cause = "current_pipeline_preferred"
            evidence.append("The current pipeline variant remained the best controlled result.")
            next_step = "Keep the current shaping and focus on another segment family."
        else:
            evidence.append("Variant results were mixed across text and model changes.")

        findings.append(
            AudioProbeFinding(
                source_segment_id=source_segment_id,
                probable_cause=cause,
                best_variant_id=best.variant_id,
                evidence=evidence,
                recommended_next_step=next_step,
            )
        )
    return findings


def _best_ranked_variant(variants: Iterable[AudioProbeVariant]) -> AudioProbeVariant | None:
    ranked = sorted(list(variants), key=_variant_rank, reverse=True)
    return ranked[0] if ranked else None


def _variant_rank(variant: AudioProbeVariant | None) -> tuple[int, int, int]:
    if variant is None or variant.judge_result is None:
        return (-1, -1, -1)
    recommendation_rank = {"block": 0, "revise": 1, "use": 2}[variant.judge_result.recommendation]
    blocker_penalty = 0 if variant.judge_result.blocker else 1
    score_sum = (
        variant.judge_result.pacing_suitability_score
        + variant.judge_result.pacing_consistency_score
        + variant.judge_result.pronunciation_accuracy_score
    )
    return (recommendation_rank, blocker_penalty, score_sum)


def _probe_seed(text: str) -> int:
    value = 0
    for char in text:
        value = (value * 131 + ord(char)) % (2**32)
    return value


def _write_probe_summary(path: Path, summary: AudioProbeRunSummary) -> None:
    _ensure_parent(path)
    path.write_text(summary.model_dump_json(indent=2))


def _write_probe_results_jsonl(path: Path, variants: list[AudioProbeVariant]) -> None:
    _ensure_parent(path)
    with path.open("w") as handle:
        for variant in variants:
            handle.write(variant.model_dump_json() + "\n")


def _write_probe_report(path: Path, summary: AudioProbeRunSummary) -> None:
    _ensure_parent(path)
    lines = [
        "# UFLI Audio Probe Report",
        "",
        f"- Voice profile: `{summary.voice_profile}`",
        f"- Live generated: `{summary.live}`",
        f"- Judged: `{summary.judged}`",
        f"- Variants: `{summary.variant_count}`",
        "",
        "## Findings",
        "",
    ]
    for finding in summary.findings:
        lines.append(
            f"- `{finding.source_segment_id}`: `{finding.probable_cause}` "
            f"best=`{finding.best_variant_id}`"
        )
        for item in finding.evidence:
            lines.append(f"  - {item}")
        if finding.recommended_next_step:
            lines.append(f"  - Next: {finding.recommended_next_step}")
    lines.extend(["", "## Variants", ""])
    for variant in summary.variants:
        judge_bits = ""
        if variant.judge_result is not None:
            judge_bits = (
                f" recommendation=`{variant.judge_result.recommendation}`"
                f" blocker={variant.judge_result.blocker}"
                f" wpm={variant.judge_result.actual_wpm}"
            )
        lines.append(
            f"- `{variant.variant_id}` family=`{variant.variant_family}`"
            f" provider=`{variant.provider}` model=`{variant.model_id}`"
            f" status=`{variant.generation_status}`{judge_bits}"
        )
    path.write_text("\n".join(lines) + "\n")


def _google_canary_settings(
    voice_name: str,
    region: str | None,
    speaking_rate: float | None,
    model_name: str,
    style_prompt: str,
    sample_rate_hz: int,
    volume_gain_db: float,
) -> GoogleCloudTtsSettings:
    target_region = _resolve_google_tts_region(region)
    api_endpoint = (
        "https://texttospeech.googleapis.com"
        if target_region == "global"
        else f"https://{target_region}-texttospeech.googleapis.com"
    )
    rate = speaking_rate if speaking_rate is not None else 1.0
    return GoogleCloudTtsSettings(
        api_endpoint=api_endpoint,
        voice_name=voice_name,
        speaking_rate=rate,
        model_name=model_name,
        style_prompt=style_prompt,
        sample_rate_hz=sample_rate_hz,
        volume_gain_db=volume_gain_db,
    )


def _resolve_google_tts_region(region: str | None) -> str:
    candidate = (
        (region or "").strip()
        or os.environ.get("GOOGLE_TTS_LOCATION", "").strip()
        or os.environ.get("GOOGLE_CLOUD_LOCATION", "").strip()
    )
    return candidate if candidate in _GOOGLE_TTS_REGIONS else "us"


def _google_settings_for_clip(
    base_settings: GoogleCloudTtsSettings,
    clip_kind: AudioClipKind,
) -> GoogleCloudTtsSettings:
    return base_settings.model_copy(
        update={
            "speaking_rate": _GOOGLE_SPEAKING_RATE_BY_CLIP.get(
                clip_kind,
                base_settings.speaking_rate,
            )
            if base_settings.speaking_rate == 1.0
            else base_settings.speaking_rate
        }
    )


def _google_markup_from_tts_text(
    text: str,
    clip_kind: AudioClipKind,
    settings: GoogleCloudTtsSettings | None = None,
) -> str:
    if settings is not None and settings.model_name.startswith("gemini-2.5-"):
        pause_tag = "[long pause]" if clip_kind == "passage_full" else "[medium pause]"
    else:
        pause_tag = "[pause long]" if clip_kind == "passage_full" else "[pause]"
    parts = [part.strip() for part in text.split("...")]
    joined = f" {pause_tag} ".join(part for part in parts if part)
    compact = re.sub(r"\s+", " ", joined).strip()
    return compact or text


def _request_google_cloud_tts_audio(
    text: str,
    input_format: str,
    settings: GoogleCloudTtsSettings,
) -> bytes:
    credentials, project_id = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())  # type: ignore[no-untyped-call]
    token = credentials.token
    if not token:
        raise RuntimeError("Google Cloud TTS auth failed: missing access token")

    input_payload: dict[str, object] = (
        {"markup": text} if input_format == "markup" else {"text": text}
    )
    if settings.style_prompt:
        input_payload["prompt"] = settings.style_prompt
    payload = {
        "input": input_payload,
        "voice": {
            "languageCode": settings.language_code,
            "name": settings.voice_name,
            **({"modelName": settings.model_name} if settings.model_name else {}),
        },
        "audioConfig": {
            "audioEncoding": settings.audio_encoding,
            "speakingRate": settings.speaking_rate,
            **(
                {"sampleRateHertz": settings.sample_rate_hz}
                if settings.sample_rate_hz > 0
                else {}
            ),
            "volumeGainDb": settings.volume_gain_db,
        },
    }
    request = urllib.request.Request(
        f"{settings.api_endpoint}/v1/text:synthesize",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            **(
                {"x-goog-user-project": project_id}
                if project_id
                else {}
            ),
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310
                response_payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:  # pragma: no cover - exercised live only
            body = exc.read().decode("utf-8", errors="ignore")
            if exc.code >= 500 and attempt < 2:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"Google Cloud TTS failed ({exc.code}): {body}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - exercised live only
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"Google Cloud TTS transport failed: {exc}") from exc

    audio_content = response_payload.get("audioContent", "")
    if not isinstance(audio_content, str) or not audio_content:
        raise RuntimeError("Google Cloud TTS returned no audioContent")
    return base64.b64decode(audio_content)
