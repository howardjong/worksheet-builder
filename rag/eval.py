"""Primary RAG experiment harness for retrieval quality and downstream impact."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import click
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from ab_eval import ExtractionMode, _freeze_source_and_skill, _run_variant_from_frozen
from adapt.schema import AdaptedActivityModel
from companion.schema import load_profile
from rag.retrieval import RAGContext, RetrievalResult, retrieve_context
from theme.engine import load_theme
from transform import _select_rag_adaptation_context

logger = logging.getLogger(__name__)


class EvalCaseResult(BaseModel):
    """Per-worksheet evaluation result."""

    input_name: str
    skill_domain: str
    specific_skill: str
    retrieval_at_3: float
    retrieval_latency_ms: float
    baseline_all_validators_passed: bool
    rag_all_validators_passed: bool
    baseline_formats: list[str]
    rag_formats: list[str]
    format_diversity_delta: int
    format_changed: bool
    baseline_curriculum_support_rate: float = 0.0
    rag_curriculum_support_rate: float = 0.0
    curriculum_support_delta: float = 0.0
    curriculum_reference_count: int = 0
    retrieval_context_found: bool = False
    distractor_novelty: float | None = None
    rag_selected_source: str = "none"
    rag_selected_count: int = 0
    rag_selected_avg_score: float | None = None
    rag_selected_doc_ids: list[str] = Field(default_factory=list)
    baseline_runtime_s: float = 0.0
    rag_runtime_s: float = 0.0
    rag_runtime_delta_s: float = 0.0


class EvalReport(BaseModel):
    """Aggregate evaluation report."""

    generated_at: str
    db_path: str
    case_count: int
    retrieval_at_3_mean: float
    retrieval_latency_ms_mean: float
    retrieval_context_rate: float
    curriculum_reference_hit_rate: float
    selected_avg_score_mean: float | None = None
    unique_rag_format_sets: int
    format_changed_rate: float
    distractor_novelty_mean: float | None = None
    baseline_validator_pass_rate: float
    rag_validator_pass_rate: float
    validator_pass_rate_delta: float
    baseline_curriculum_support_rate_mean: float = 0.0
    rag_curriculum_support_rate_mean: float = 0.0
    curriculum_support_delta_mean: float = 0.0
    rag_runtime_delta_mean_s: float = 0.0
    cases: list[EvalCaseResult]


def evaluate(
    test_dir: str,
    profile_path: str,
    db_path: str = "vector_store",
    theme_id: str = "roblox_obby",
    include_pattern: str = "*",
    output_root: str = "./samples/output/rag_eval",
    images: bool = False,
    extract_mode: ExtractionMode = "vision_only",
) -> EvalReport:
    """Evaluate retrieval quality and adaptation impact over a test set."""
    input_dir = Path(test_dir)
    files = sorted(path for path in input_dir.glob(include_pattern) if path.is_file())
    if not files:
        raise FileNotFoundError(f"No files matched {include_pattern} in {input_dir}")

    run_root = Path(output_root) / datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)

    profile = load_profile(profile_path)
    theme = load_theme(theme_id)
    cases: list[EvalCaseResult] = []

    for input_path in files:
        logger.info("Evaluating %s", input_path.name)
        case_dir = run_root / input_path.stem
        frozen = _freeze_source_and_skill(
            input_path,
            case_dir / "frozen",
            extract_mode=extract_mode,
        )
        source_model = frozen["source_model"]
        skill_model = frozen["skill_model"]
        skill_desc = f"{skill_model.domain}: {skill_model.specific_skill}"

        retrieval_started = perf_counter()
        rag_context = retrieve_context(
            skill_description=skill_desc,
            extracted_text=source_model.raw_text,
            grade_level=skill_model.grade_level,
            db_path=db_path,
        )
        retrieval_latency_ms = (perf_counter() - retrieval_started) * 1000.0
        selected_metadata, rag_debug = _select_rag_adaptation_context(rag_context)
        baseline_started = perf_counter()
        baseline = _run_variant_from_frozen(
            variant="A_no_rag",
            case_dir=case_dir,
            frozen=frozen,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            use_rag=False,
            images=images,
        )
        baseline_runtime_s = perf_counter() - baseline_started
        rag_started = perf_counter()
        rag_result = _run_variant_from_frozen(
            variant="B_with_rag",
            case_dir=case_dir,
            frozen=frozen,
            profile=profile,
            theme=theme,
            theme_id=theme_id,
            use_rag=True,
            images=images,
        )
        rag_runtime_s = perf_counter() - rag_started

        cases.append(
            EvalCaseResult(
                input_name=input_path.name,
                skill_domain=skill_model.domain,
                specific_skill=skill_model.specific_skill,
                retrieval_at_3=_retrieval_at_k(rag_context, skill_model.domain, k=3),
                retrieval_latency_ms=retrieval_latency_ms,
                baseline_all_validators_passed=bool(
                    baseline.get("all_validators_passed", False)
                ),
                rag_all_validators_passed=bool(rag_result.get("all_validators_passed", False)),
                baseline_formats=[str(x) for x in baseline.get("response_formats", [])],
                rag_formats=[str(x) for x in rag_result.get("response_formats", [])],
                format_diversity_delta=int(rag_result.get("response_format_count", 0))
                - int(baseline.get("response_format_count", 0)),
                format_changed=_format_set(
                    [str(x) for x in baseline.get("response_formats", [])]
                )
                != _format_set([str(x) for x in rag_result.get("response_formats", [])]),
                baseline_curriculum_support_rate=float(
                    baseline.get("curriculum_support_rate", 0.0)
                ),
                rag_curriculum_support_rate=float(rag_result.get("curriculum_support_rate", 0.0)),
                curriculum_support_delta=float(rag_result.get("curriculum_support_rate", 0.0))
                - float(baseline.get("curriculum_support_rate", 0.0)),
                curriculum_reference_count=len(rag_context.curriculum_references),
                retrieval_context_found=(
                    int(cast(int | str, rag_debug.get("selected_count", 0) or 0)) > 0
                ),
                distractor_novelty=_distractor_novelty(
                    _extract_distractors_from_variant(rag_result),
                    selected_metadata or [],
                ),
                rag_selected_source=str(rag_debug.get("selected_source", "none")),
                rag_selected_count=int(cast(int | str, rag_debug.get("selected_count", 0) or 0)),
                rag_selected_avg_score=cast(float | None, rag_debug.get("selected_avg_score")),
                rag_selected_doc_ids=[
                    str(doc_id)
                    for doc_id in cast(
                        list[object],
                        rag_debug.get("selected_doc_ids", []),
                    )
                ],
                baseline_runtime_s=baseline_runtime_s,
                rag_runtime_s=rag_runtime_s,
                rag_runtime_delta_s=rag_runtime_s - baseline_runtime_s,
            )
        )

    report = _build_report(db_path, cases)
    report_json = run_root / "report.json"
    report_json.write_text(report.model_dump_json(indent=2))
    report_md = run_root / "report.md"
    report_md.write_text(_render_markdown_report(run_root, files, report))
    logger.info("Evaluation report written to %s", report_json)
    return report


def _build_report(db_path: str, cases: list[EvalCaseResult]) -> EvalReport:
    unique_rag_format_sets = len({",".join(_format_set(case.rag_formats)) for case in cases})
    retrieval_scores = [case.retrieval_at_3 for case in cases]
    retrieval_latencies = [case.retrieval_latency_ms for case in cases]
    distractor_scores = [
        case.distractor_novelty for case in cases if case.distractor_novelty is not None
    ]
    selected_avg_scores = [
        case.rag_selected_avg_score for case in cases if case.rag_selected_avg_score is not None
    ]

    baseline_pass_rate = _mean(
        [1.0 if case.baseline_all_validators_passed else 0.0 for case in cases]
    )
    rag_pass_rate = _mean([1.0 if case.rag_all_validators_passed else 0.0 for case in cases])

    return EvalReport(
        generated_at=datetime.now(tz=UTC).isoformat(),
        db_path=db_path,
        case_count=len(cases),
        retrieval_at_3_mean=_mean(retrieval_scores),
        retrieval_latency_ms_mean=_mean(retrieval_latencies),
        retrieval_context_rate=_mean(
            [1.0 if case.retrieval_context_found else 0.0 for case in cases]
        ),
        curriculum_reference_hit_rate=_mean(
            [1.0 if case.curriculum_reference_count > 0 else 0.0 for case in cases]
        ),
        selected_avg_score_mean=_mean(selected_avg_scores) if selected_avg_scores else None,
        unique_rag_format_sets=unique_rag_format_sets,
        format_changed_rate=_mean([1.0 if case.format_changed else 0.0 for case in cases]),
        distractor_novelty_mean=_mean(distractor_scores) if distractor_scores else None,
        baseline_validator_pass_rate=baseline_pass_rate,
        rag_validator_pass_rate=rag_pass_rate,
        validator_pass_rate_delta=rag_pass_rate - baseline_pass_rate,
        baseline_curriculum_support_rate_mean=_mean(
            [case.baseline_curriculum_support_rate for case in cases]
        ),
        rag_curriculum_support_rate_mean=_mean(
            [case.rag_curriculum_support_rate for case in cases]
        ),
        curriculum_support_delta_mean=_mean([case.curriculum_support_delta for case in cases]),
        rag_runtime_delta_mean_s=_mean([case.rag_runtime_delta_s for case in cases]),
        cases=cases,
    )


def _retrieval_at_k(
    rag_context: RAGContext,
    expected_domain: str,
    k: int = 3,
) -> float:
    hits = _top_retrieval_hits(rag_context, k)
    if not hits:
        return 0.0
    matches = 0
    for hit in hits:
        if str(hit.metadata.get("domain", "")) == expected_domain:
            matches += 1
    return matches / len(hits)


def _top_retrieval_hits(rag_context: RAGContext, k: int) -> list[RetrievalResult]:
    ordered = [
        *rag_context.curated_exemplars,
        *rag_context.prior_adaptations,
        *rag_context.similar_skills,
    ]
    deduped: list[RetrievalResult] = []
    seen_doc_ids: set[str] = set()
    for hit in ordered:
        if hit.doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(hit.doc_id)
        deduped.append(hit)
        if len(deduped) >= k:
            break
    return deduped


def _extract_distractors_from_variant(result: dict[str, Any]) -> set[str]:
    variant_root = Path(str(result["output_dir"])).parent
    artifacts_dir = variant_root / "artifacts"
    adapted_paths = sorted(artifacts_dir.glob("adapted_model*.json"))
    distractors: set[str] = set()

    for path in adapted_paths:
        adapted = AdaptedActivityModel.model_validate_json(path.read_text())
        for chunk in adapted.chunks:
            for item in chunk.items:
                if item.response_format != "circle" or not item.options:
                    continue
                answers = {
                    answer.strip().lower()
                    for answer in (item.answer or "").split(",")
                    if answer.strip()
                }
                for option in item.options:
                    normalized = option.strip().lower()
                    if normalized and normalized not in answers:
                        distractors.add(normalized)

    return distractors


def _distractor_novelty(
    current_distractors: set[str],
    rag_metadata: list[dict[str, object]],
) -> float | None:
    if not current_distractors:
        return None

    prior_distractors: set[str] = set()
    for metadata in rag_metadata:
        raw = str(metadata.get("distractor_words", ""))
        for word in raw.split(","):
            normalized = word.strip().lower()
            if normalized:
                prior_distractors.add(normalized)

    if not prior_distractors:
        return 1.0

    novel = [word for word in current_distractors if word not in prior_distractors]
    return len(novel) / len(current_distractors)


def _format_set(formats: list[str]) -> list[str]:
    return sorted({fmt for fmt in formats if fmt})


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _render_markdown_report(
    run_root: Path,
    files: list[Path],
    report: EvalReport,
) -> str:
    lines = [
        "# RAG Evaluation Report",
        "",
        f"- Run root: `{run_root}`",
        f"- Inputs: {', '.join(path.name for path in files)}",
        f"- Vector store: `{report.db_path}`",
        "",
        "## Aggregate",
        "",
        "- `rag/eval.py` is the primary experiment harness.",
        f"- Cases: {report.case_count}",
        f"- retrieval@3 mean: {report.retrieval_at_3_mean:.2f}",
        f"- Retrieval latency mean (ms): {report.retrieval_latency_ms_mean:.1f}",
        f"- Retrieval context rate: {report.retrieval_context_rate:.2f}",
        f"- Curriculum reference hit rate: {report.curriculum_reference_hit_rate:.2f}",
        (
            f"- Selected context avg score mean: {report.selected_avg_score_mean:.2f}"
            if report.selected_avg_score_mean is not None
            else "- Selected context avg score mean: n/a"
        ),
        f"- Unique RAG format sets: {report.unique_rag_format_sets}",
        f"- Format changed rate: {report.format_changed_rate:.2f}",
        (
            f"- Distractor novelty mean: {report.distractor_novelty_mean:.2f}"
            if report.distractor_novelty_mean is not None
            else "- Distractor novelty mean: n/a"
        ),
        f"- Baseline validator pass rate: {report.baseline_validator_pass_rate:.2f}",
        f"- RAG validator pass rate: {report.rag_validator_pass_rate:.2f}",
        f"- Validator pass rate delta: {report.validator_pass_rate_delta:.2f}",
        (
            f"- Curriculum support delta mean: {report.curriculum_support_delta_mean:.2f}"
        ),
        f"- Mean RAG runtime overhead (s): {report.rag_runtime_delta_mean_s:.2f}",
        "",
        "## Per Case",
        "",
        (
            "| Input | retrieval@3 | latency ms | Baseline pass | RAG pass | "
            "Curriculum delta | Selected source | Selected avg | Novelty |"
        ),
        "|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]

    for case in report.cases:
        novelty = "n/a"
        if case.distractor_novelty is not None:
            novelty = f"{case.distractor_novelty:.2f}"
        selected_avg = "n/a"
        if case.rag_selected_avg_score is not None:
            selected_avg = f"{case.rag_selected_avg_score:.2f}"
        lines.append(
            f"| {case.input_name} | {case.retrieval_at_3:.2f} | "
            f"{case.retrieval_latency_ms:.1f} | "
            f"{int(case.baseline_all_validators_passed)} | "
            f"{int(case.rag_all_validators_passed)} | "
            f"{case.curriculum_support_delta:.2f} | "
            f"{case.rag_selected_source} | {selected_avg} | {novelty} |"
        )

    return "\n".join(lines) + "\n"


@click.command()
@click.option("--test-dir", required=True, help="Directory with test worksheet photos.")
@click.option("--profile", "profile_path", required=True, help="Learner profile YAML.")
@click.option("--db-path", default="vector_store", help="Vector store path.")
@click.option("--theme", "theme_id", default="roblox_obby", help="Theme name.")
@click.option("--include", "include_pattern", default="*", help="Glob pattern in test dir.")
@click.option(
    "--output-root",
    default="./samples/output/rag_eval",
    help="Directory where evaluation reports should be written.",
)
@click.option("--images/--no-images", default=False, help="Enable AI image generation.")
@click.option(
    "--extract-mode",
    type=click.Choice(["vision_only", "auto", "paddle", "tesseract"], case_sensitive=False),
    default="vision_only",
    show_default=True,
    help=(
        "Extraction backend for frozen eval inputs. "
        "'vision_only' fails fast if Gemini vision is unavailable; "
        "'auto' restores OCR fallback."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def main(
    test_dir: str,
    profile_path: str,
    db_path: str,
    theme_id: str,
    include_pattern: str,
    output_root: str,
    images: bool,
    extract_mode: str,
    verbose: bool,
) -> None:
    """Run the primary RAG experiment harness."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    report = evaluate(
        test_dir=test_dir,
        profile_path=profile_path,
        db_path=db_path,
        theme_id=theme_id,
        include_pattern=include_pattern,
        output_root=output_root,
        images=images,
        extract_mode=cast(ExtractionMode, extract_mode.lower()),
    )
    click.echo(
        f"Evaluated {report.case_count} case(s); "
        f"retrieval@3 mean={report.retrieval_at_3_mean:.2f}"
    )


if __name__ == "__main__":
    main()
