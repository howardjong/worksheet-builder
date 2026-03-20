"""Audit-driven remediation for the UFLI curriculum corpus."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from corpus.ufli.audit_schema import AuditFlag, CorpusAuditSummary
from corpus.ufli.extract import LessonContent, extract_lesson

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------

STRATEGY_REEXTRACT = "re_extract"
STRATEGY_CONCEPT_BACKFILL = "concept_backfill"
STRATEGY_REINDEX = "re_index"
STRATEGY_DELETE_STALE = "delete_stale_index"
STRATEGY_AUDIO_REGEN = "audio_regen"
STRATEGY_MANUAL = "manual"

# Pilot lessons for Stage 1 audio generation
_PILOT_LESSONS = {1, 14, 95}

# Flag code -> strategy mapping
_TEXT_STRATEGIES: dict[str, str] = {
    "very_short_record": STRATEGY_REEXTRACT,
    "empty_extracted_text": STRATEGY_REEXTRACT,
    "missing_required_fields": STRATEGY_REEXTRACT,
    "missing_concept": STRATEGY_CONCEPT_BACKFILL,
    "missing_curriculum_index": STRATEGY_REINDEX,
    "stale_curriculum_index": STRATEGY_DELETE_STALE,
    "missing_raw_dir": STRATEGY_MANUAL,
    "malformed_jsonl": STRATEGY_MANUAL,
    "duplicate_lesson_id": STRATEGY_MANUAL,
    "near_duplicate_lesson_text": STRATEGY_MANUAL,
    "malformed_manifest_jsonl": STRATEGY_MANUAL,
}

_IMAGE_STRATEGIES: dict[str, str] = {
    "missing_image_file": STRATEGY_MANUAL,
    "empty_image_file": STRATEGY_MANUAL,
    "unreadable_image": STRATEGY_MANUAL,
    "missing_caption": STRATEGY_MANUAL,
    "missing_alt_text": STRATEGY_MANUAL,
    "short_caption": STRATEGY_MANUAL,
    "placeholder_caption": STRATEGY_MANUAL,
    "caption_concept_mismatch": STRATEGY_MANUAL,
    "exact_duplicate_image": STRATEGY_MANUAL,
    "near_duplicate_image": STRATEGY_MANUAL,
    "unknown_lesson_id": STRATEGY_MANUAL,
}

_AUDIO_STRATEGIES: dict[str, str] = {
    "missing_audio_file": STRATEGY_AUDIO_REGEN,
    "empty_audio_file": STRATEGY_AUDIO_REGEN,
    "unreadable_audio": STRATEGY_AUDIO_REGEN,
    "invalid_duration": STRATEGY_AUDIO_REGEN,
    "wpm_outlier": STRATEGY_AUDIO_REGEN,
    "missing_transcript": STRATEGY_MANUAL,
    "short_transcript": STRATEGY_MANUAL,
    "placeholder_transcript": STRATEGY_MANUAL,
    "transcript_concept_mismatch": STRATEGY_MANUAL,
    "duplicate_transcript": STRATEGY_MANUAL,
    "boilerplate_transcript_overuse": STRATEGY_MANUAL,
    "duplicate_sequence_index": STRATEGY_MANUAL,
    "non_contiguous_sequence_index": STRATEGY_MANUAL,
    "unknown_lesson_id": STRATEGY_MANUAL,
}

_ALL_STRATEGIES: dict[str, dict[str, str]] = {
    "text": _TEXT_STRATEGIES,
    "image": _IMAGE_STRATEGIES,
    "audio": _AUDIO_STRATEGIES,
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RemediationAction(BaseModel):
    """One planned or executed remediation action."""

    flag: AuditFlag
    strategy: str
    status: Literal["pending", "fixed", "skipped", "manual_review", "failed"] = "pending"
    detail: str = ""


class RemediationReport(BaseModel):
    """Summary of remediation execution."""

    generated_at: str = ""
    actions: list[RemediationAction] = Field(default_factory=list)
    fixed_count: int = 0
    skipped_count: int = 0
    manual_review_count: int = 0
    failed_count: int = 0
    reindexed_lesson_ids: list[str] = Field(default_factory=list)
    deleted_index_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_remediations(
    summary: CorpusAuditSummary,
    severity_filter: set[str] | None = None,
    code_filter: set[str] | None = None,
) -> list[RemediationAction]:
    """Map audit flags to remediation actions, deduplicating by lesson+strategy."""
    if severity_filter is None:
        severity_filter = {"fail", "warn"}

    actions: list[RemediationAction] = []
    # Track (lesson_id, strategy) to deduplicate
    seen: set[tuple[str, str]] = set()

    for flag in summary.flags:
        if flag.severity not in severity_filter:
            continue
        if code_filter and flag.code not in code_filter:
            continue

        strategy_map = _ALL_STRATEGIES.get(flag.record_type, {})
        strategy = strategy_map.get(flag.code)

        if strategy is None:
            actions.append(
                RemediationAction(
                    flag=flag,
                    strategy="unknown",
                    status="skipped",
                    detail=f"no automated fix available for {flag.code}",
                )
            )
            continue

        # Deduplicate: one re-extract per lesson, one audio regen per lesson
        dedup_key = (flag.lesson_id, strategy)
        if strategy in (STRATEGY_REEXTRACT, STRATEGY_AUDIO_REGEN) and dedup_key in seen:
            continue
        seen.add(dedup_key)

        initial_status: Literal["pending", "manual_review"]
        if strategy == STRATEGY_MANUAL:
            initial_status = "manual_review"
        else:
            initial_status = "pending"

        actions.append(
            RemediationAction(flag=flag, strategy=strategy, status=initial_status)
        )

    return actions


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_remediations(
    actions: list[RemediationAction],
    data_dir: str = "data/ufli",
    db_path: str = "vector_store",
    dry_run: bool = True,
    skip_reindex: bool = False,
) -> RemediationReport:
    """Execute remediation actions in phased order."""
    report = RemediationReport(generated_at=datetime.now(tz=UTC).isoformat())
    report.actions = actions

    if dry_run:
        # In dry-run mode, just tally what would happen
        for action in actions:
            if action.status == "manual_review":
                report.manual_review_count += 1
            elif action.status == "pending":
                action.detail = "dry run — no changes made"
        report.fixed_count = 0
        report.skipped_count = sum(1 for a in actions if a.status == "skipped")
        report.failed_count = 0
        return report

    manifest = _load_manifest_lookup(data_dir)

    # Phase 1: Re-extract
    reextract_lessons: dict[str, RemediationAction] = {}
    for action in actions:
        if action.strategy == STRATEGY_REEXTRACT and action.status == "pending":
            lid = action.flag.lesson_id
            if not lid:
                action.status = "skipped"
                action.detail = "lesson_id is empty — cannot identify lesson to re-extract"
                continue
            reextract_lessons[lid] = action

    patches: dict[str, LessonContent] = {}
    reextracted_ids: set[str] = set()
    for lid, action in reextract_lessons.items():
        manifest_entry = manifest.get(lid, {})
        lesson_group = manifest_entry.get("lesson_group", "")
        concept = manifest_entry.get("concept", "")
        try:
            result = extract_lesson(lid, lesson_group, concept, data_dir)
        except Exception as exc:
            action.status = "failed"
            action.detail = f"extract_lesson raised: {exc}"
            logger.error("Re-extract failed for lesson %s: %s", lid, exc)
            continue
        if result is None:
            action.status = "failed"
            action.detail = f"raw directory missing: data/ufli/raw/{lid}/"
            continue
        patches[lid] = result
        reextracted_ids.add(lid)
        action.status = "fixed"
        action.detail = "re-extracted from raw files"
        logger.info("Re-extracted lesson %s", lid)

    # Phase 2: Concept backfill
    for action in actions:
        if action.strategy == STRATEGY_CONCEPT_BACKFILL and action.status == "pending":
            lid = action.flag.lesson_id
            if lid in reextracted_ids:
                action.status = "skipped"
                action.detail = "already re-extracted in phase 1 (concept set via extract_lesson)"
                continue
            manifest_entry = manifest.get(lid, {})
            manifest_concept = manifest_entry.get("concept", "")
            if not manifest_concept:
                action.status = "skipped"
                action.detail = (
                    "manifest also has no concept for this lesson "
                    "(pre-phonics Getting Ready lesson)"
                )
                continue
            # Read existing record from normalized.jsonl and patch concept
            existing = _read_normalized_record(data_dir, lid)
            if existing is None:
                action.status = "failed"
                action.detail = f"lesson {lid} not found in normalized.jsonl"
                continue
            existing["concept"] = manifest_concept
            patches[lid] = LessonContent(
                lesson_id=existing.get("lesson_id", lid),
                lesson_group=existing.get("lesson_group", ""),
                concept=manifest_concept,
                slide_text=existing.get("slide_text", ""),
                slide_count=existing.get("slide_count", 0),
                decodable_text=existing.get("decodable_text", ""),
                home_practice_text=existing.get("home_practice_text", ""),
                additional_text=existing.get("additional_text", ""),
            )
            action.status = "fixed"
            action.detail = f"concept backfilled from manifest: {manifest_concept!r}"
            logger.info("Concept backfilled for lesson %s", lid)

    # Write all patches atomically
    if patches:
        _patch_normalized_jsonl(data_dir, patches)
        logger.info("Patched normalized.jsonl with %d lesson(s)", len(patches))

    # Phase 3: Index cleanup (delete stale entries)
    for action in actions:
        if action.strategy == STRATEGY_DELETE_STALE and action.status == "pending":
            lid = action.flag.lesson_id
            doc_id = f"curriculum_ufli_{lid}"
            try:
                from rag.store import (
                    CURRICULUM,
                    delete_document,
                    get_or_create_collection,
                    get_store,
                )

                store = get_store(db_path)
                collection = get_or_create_collection(store, CURRICULUM)
                delete_document(collection, doc_id)
                report.deleted_index_ids.append(lid)
                action.status = "fixed"
                action.detail = f"deleted stale index entry {doc_id}"
                logger.info("Deleted stale index for lesson %s", lid)
            except Exception as exc:
                action.status = "failed"
                action.detail = f"delete failed: {exc}"
                logger.error("Delete stale index failed for %s: %s", lid, exc)

    # Phase 4: Re-index
    if not skip_reindex:
        # Collect lessons needing re-indexing
        reindex_ids: set[str] = set()
        for action in actions:
            if action.strategy == STRATEGY_REINDEX and action.status == "pending":
                reindex_ids.add(action.flag.lesson_id)
        # Also re-index anything we re-extracted or concept-backfilled
        for action in actions:
            if action.status == "fixed" and action.strategy in (
                STRATEGY_REEXTRACT,
                STRATEGY_CONCEPT_BACKFILL,
            ):
                reindex_ids.add(action.flag.lesson_id)

        if reindex_ids:
            _reindex_lessons(actions, reindex_ids, data_dir, db_path, report)
    else:
        for action in actions:
            if action.strategy == STRATEGY_REINDEX and action.status == "pending":
                action.status = "skipped"
                action.detail = "re-indexing skipped (--skip-reindex)"

    # Phase 5: Audio re-generation
    audio_lessons: dict[str, RemediationAction] = {}
    for action in actions:
        if action.strategy == STRATEGY_AUDIO_REGEN and action.status == "pending":
            lid = action.flag.lesson_id
            audio_lessons[lid] = action

    for lid, action in audio_lessons.items():
        try:
            lesson_num = int(lid)
        except ValueError:
            action.status = "skipped"
            action.detail = f"lesson {lid} is not numeric — cannot regenerate audio"
            continue
        if lesson_num not in _PILOT_LESSONS:
            action.status = "skipped"
            action.detail = (
                f"lesson {lid} is outside Stage 1 pilot scope — "
                "will be available after Stage 2 rollout"
            )
            continue
        try:
            from corpus.ufli.audio_companion import generate_audio_companion

            generate_audio_companion(
                data_dir=data_dir,
                lesson_set="pilot_micro",
                lesson_id=str(lesson_num),
                dry_run=False,
                force=True,
            )
            action.status = "fixed"
            action.detail = f"audio regenerated for pilot lesson {lid}"
            logger.info("Regenerated audio for lesson %s", lid)
        except Exception as exc:
            action.status = "failed"
            action.detail = f"audio generation failed: {exc}"
            logger.error("Audio regen failed for lesson %s: %s", lid, exc)

    # Phase 6: Tally
    for action in actions:
        if action.status == "fixed":
            report.fixed_count += 1
        elif action.status == "skipped":
            report.skipped_count += 1
        elif action.status == "manual_review":
            report.manual_review_count += 1
        elif action.status == "failed":
            report.failed_count += 1

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_manifest_lookup(data_dir: str) -> dict[str, dict[str, Any]]:
    """Read manifest.jsonl into a lesson_id-keyed dict."""
    manifest_path = Path(data_dir) / "manifest.jsonl"
    lookup: dict[str, dict[str, Any]] = {}
    if not manifest_path.exists():
        logger.warning("manifest.jsonl not found at %s", manifest_path)
        return lookup
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            lid = rec.get("lesson_id", "")
            if lid:
                lookup[lid] = rec
        except json.JSONDecodeError:
            continue
    return lookup


def _read_normalized_record(data_dir: str, lesson_id: str) -> dict[str, Any] | None:
    """Read a single record from normalized.jsonl by lesson_id."""
    normalized_path = Path(data_dir) / "normalized.jsonl"
    if not normalized_path.exists():
        return None
    for line in normalized_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("lesson_id") == lesson_id:
                return rec
        except json.JSONDecodeError:
            continue
    return None


def _patch_normalized_jsonl(
    data_dir: str, patches: dict[str, LessonContent]
) -> None:
    """Atomically patch lessons in normalized.jsonl."""
    normalized_path = Path(data_dir) / "normalized.jsonl"
    if not normalized_path.exists():
        logger.error("normalized.jsonl not found — cannot patch")
        return

    lines = normalized_path.read_text().splitlines()
    output_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            output_lines.append(line)
            continue
        try:
            rec = json.loads(stripped)
            lid = rec.get("lesson_id", "")
            if lid in patches:
                patched = asdict(patches[lid])
                output_lines.append(json.dumps(patched, ensure_ascii=False))
            else:
                output_lines.append(line)
        except json.JSONDecodeError:
            # Preserve malformed lines as-is
            output_lines.append(line)

    # Atomic write via temp file + os.replace
    fd, tmp_path = tempfile.mkstemp(
        dir=str(normalized_path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
            if output_lines:
                f.write("\n")
        os.replace(tmp_path, str(normalized_path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _reindex_lessons(
    actions: list[RemediationAction],
    lesson_ids: set[str],
    data_dir: str,
    db_path: str,
    report: RemediationReport,
) -> None:
    """Re-embed and upsert lessons into ChromaDB."""
    try:
        from rag.client import rag_available
    except ImportError:
        for action in actions:
            if action.strategy == STRATEGY_REINDEX and action.status == "pending":
                action.status = "skipped"
                action.detail = "RAG package not available"
        return

    if not rag_available():
        for action in actions:
            if action.strategy == STRATEGY_REINDEX and action.status == "pending":
                action.status = "skipped"
                action.detail = (
                    "embedding API not available — re-run with API key configured"
                )
        return

    from rag.embeddings import embed_text
    from rag.store import CURRICULUM, add_document, get_or_create_collection, get_store

    store = get_store(db_path)
    collection = get_or_create_collection(store, CURRICULUM)
    normalized_path = Path(data_dir) / "normalized.jsonl"
    if not normalized_path.exists():
        return

    # Build a lookup of current normalized records
    records: dict[str, dict[str, Any]] = {}
    for line in normalized_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            records[rec.get("lesson_id", "")] = rec
        except json.JSONDecodeError:
            continue

    for lid in lesson_ids:
        rec = records.get(lid)
        if not rec:
            continue

        parts = [rec.get("slide_text", "")]
        if rec.get("decodable_text"):
            parts.append(rec["decodable_text"])
        if rec.get("home_practice_text"):
            parts.append(rec["home_practice_text"])
        if rec.get("additional_text"):
            parts.append(rec["additional_text"])
        combined_text = "\n\n".join(p for p in parts if p)

        if not combined_text.strip():
            continue

        doc_id = f"curriculum_ufli_{lid}"
        try:
            from corpus.ufli.grade_levels import derive_grade

            grade_level = derive_grade(lid)
            result = embed_text(combined_text[:2000], task_type="RETRIEVAL_DOCUMENT")
            metadata = {
                "source": "ufli_toolbox",
                "lesson_id": lid,
                "lesson_group": rec.get("lesson_group", ""),
                "concept": rec.get("concept", ""),
                "slide_count": rec.get("slide_count", 0),
                "grade_level": grade_level,
                "has_decodable": bool(rec.get("decodable_text")),
                "has_home_practice": bool(rec.get("home_practice_text")),
                "has_additional": bool(rec.get("additional_text")),
                "indexed_at": datetime.now(tz=UTC).isoformat(),
            }
            add_document(
                collection,
                doc_id=doc_id,
                embedding=result.values,
                metadata=metadata,
                document=combined_text[:1000],
            )
            report.reindexed_lesson_ids.append(lid)
            logger.info("Re-indexed lesson %s", lid)
        except Exception as exc:
            logger.error("Re-index failed for lesson %s: %s", lid, exc)
            # Mark the specific reindex action as failed
            for action in actions:
                if (
                    action.strategy == STRATEGY_REINDEX
                    and action.flag.lesson_id == lid
                    and action.status == "pending"
                ):
                    action.status = "failed"
                    action.detail = f"embedding failed: {exc}"

    # Mark remaining pending reindex actions as fixed
    for action in actions:
        if action.strategy == STRATEGY_REINDEX and action.status == "pending":
            if action.flag.lesson_id in report.reindexed_lesson_ids:
                action.status = "fixed"
                action.detail = "re-indexed into ChromaDB"
            # If not in reindexed list and not already failed, it wasn't in records
            elif action.flag.lesson_id not in records:
                action.status = "failed"
                action.detail = "lesson not found in normalized.jsonl"


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def write_remediation_report(
    report: RemediationReport,
    output_dir: str,
) -> None:
    """Write remediation report artifacts to the audit directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # JSON report
    (out / "remediation_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    # Markdown report
    md_lines = [
        "# Remediation Report",
        "",
        f"Generated: {report.generated_at}",
        "",
        "## Summary",
        "",
        f"- Fixed: {report.fixed_count}",
        f"- Skipped: {report.skipped_count}",
        f"- Manual review: {report.manual_review_count}",
        f"- Failed: {report.failed_count}",
        "",
    ]
    if report.reindexed_lesson_ids:
        md_lines.append(f"Re-indexed: {', '.join(report.reindexed_lesson_ids)}")
    if report.deleted_index_ids:
        md_lines.append(f"Deleted stale: {', '.join(report.deleted_index_ids)}")
    md_lines.extend([
        "",
        "## Actions",
        "",
        "| Lesson | Code | Strategy | Status | Detail |",
        "|--------|------|----------|--------|--------|",
    ])
    for action in report.actions:
        md_lines.append(
            f"| {action.flag.lesson_id} | {action.flag.code} | "
            f"{action.strategy} | {action.status} | {action.detail} |"
        )
    md_lines.append("")
    (out / "remediation_report.md").write_text(
        "\n".join(md_lines), encoding="utf-8"
    )

    # Manual review CSV
    manual_actions = [a for a in report.actions if a.status == "manual_review"]
    if manual_actions:
        csv_path = out / "manual_review_needed.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["lesson_id", "record_type", "code", "severity", "message"],
            )
            writer.writeheader()
            for action in manual_actions:
                writer.writerow(
                    {
                        "lesson_id": action.flag.lesson_id,
                        "record_type": action.flag.record_type,
                        "code": action.flag.code,
                        "severity": action.flag.severity,
                        "message": action.flag.message,
                    }
                )


# ---------------------------------------------------------------------------
# Audit directory discovery
# ---------------------------------------------------------------------------


def find_latest_audit_dir(audit_root: str) -> str | None:
    """Find the most recent timestamped audit directory."""
    root = Path(audit_root)
    if not root.exists():
        return None
    candidates = [
        d
        for d in root.iterdir()
        if d.is_dir() and re.fullmatch(r"\d{8}_\d{6}", d.name)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: d.name)
    return str(candidates[-1])
