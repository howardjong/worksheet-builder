"""Controlled probe harness for UFLI audio root-cause analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

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
    AudioJudgeClipResult,
    AudioProbeFinding,
    AudioProbeRunSummary,
    AudioProbeVariant,
    AudioVoiceSettings,
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


def run_audio_probe_matrix(
    data_dir: str = "data/ufli",
    voice_profile: str | None = None,
    segment_ids: list[str] | None = None,
    output_dir: str | None = None,
    live: bool = False,
    judge: bool = False,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> AudioProbeRunSummary:
    """Generate controlled variants to separate input-shaping issues from TTS limits."""
    if judge and not live:
        raise RuntimeError("Audio probes must be live-generated before they can be judged")

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
            )
        )

    if live:
        api_key = _elevenlabs_api_key()
        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is required for live probe generation")
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
) -> list[AudioProbeVariant]:
    settings = _audio_settings(voice_profile, clip.segment_type)
    variants: list[AudioProbeVariant] = []

    def add_variant(
        variant_family: str,
        hypothesis: str,
        tts_text: str,
        model_id: str,
        audio_settings: AudioVoiceSettings,
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
                model_id=model_id,
                transcript_text=clip.transcript_text,
                tts_text=tts_text,
                audio_settings=audio_settings,
                audio_path=f"audio/{clip.segment_id}/{variant_id}.mp3",
            )
        )

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
            "Remove pause shaping to test whether the input pacing markup is helping or hurting.",
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

    deduped: list[AudioProbeVariant] = []
    seen: set[tuple[str, str]] = set()
    for variant in variants:
        key = (variant.model_id, variant.tts_text)
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
    probe_profile = voice_profile.model_copy(deep=True)
    probe_profile.clip_settings[variant.segment_type] = variant.audio_settings
    return _request_elevenlabs_audio(
        text=variant.tts_text,
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
            f" model=`{variant.model_id}` status=`{variant.generation_status}`{judge_bits}"
        )
    path.write_text("\n".join(lines) + "\n")
