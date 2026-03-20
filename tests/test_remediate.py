"""Tests for audit-driven corpus remediation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from corpus.ufli.audit_schema import AuditFlag, CorpusAuditSummary
from corpus.ufli.extract import LessonContent
from corpus.ufli.remediate import (
    STRATEGY_AUDIO_REGEN,
    STRATEGY_CONCEPT_BACKFILL,
    STRATEGY_DELETE_STALE,
    STRATEGY_MANUAL,
    STRATEGY_REEXTRACT,
    STRATEGY_REINDEX,
    RemediationAction,
    RemediationReport,
    _patch_normalized_jsonl,
    execute_remediations,
    find_latest_audit_dir,
    plan_remediations,
    write_remediation_report,
)


def _make_flag(
    code: str,
    lesson_id: str = "43",
    record_type: str = "text",
    severity: str = "fail",
    message: str = "test flag",
) -> AuditFlag:
    return AuditFlag(
        lesson_id=lesson_id,
        record_type=record_type,
        severity=severity,
        code=code,
        message=message,
    )


def _make_summary(flags: list[AuditFlag]) -> CorpusAuditSummary:
    return CorpusAuditSummary(
        generated_at="2026-03-19T00:00:00Z",
        data_dir="data/ufli",
        db_path="vector_store",
        output_dir="data/ufli/audit/20260319_000000",
        text_status="completed",
        image_status="not_present",
        audio_status="not_present",
        flags=flags,
    )


# ---------------------------------------------------------------------------
# Planning tests
# ---------------------------------------------------------------------------


class TestPlanRemediations:
    def test_filters_by_severity(self) -> None:
        """Only fail+warn flags produce actions; info flags are excluded."""
        flags = [
            _make_flag("empty_extracted_text", lesson_id="43", severity="fail"),
            _make_flag("very_short_record", lesson_id="44", severity="warn"),
            _make_flag("very_short_record", lesson_id="99", severity="info"),
        ]
        summary = _make_summary(flags)
        actions = plan_remediations(summary)
        # info flag should be excluded
        assert all(a.flag.severity != "info" for a in actions)
        assert len(actions) == 2

    def test_deduplicates_by_lesson(self) -> None:
        """Multiple flags for the same lesson produce one re-extract action."""
        flags = [
            _make_flag("empty_extracted_text", lesson_id="43"),
            _make_flag("very_short_record", lesson_id="43"),
        ]
        summary = _make_summary(flags)
        actions = plan_remediations(summary)
        reextract_actions = [a for a in actions if a.strategy == STRATEGY_REEXTRACT]
        assert len(reextract_actions) == 1

    def test_deduplicates_audio_by_lesson(self) -> None:
        """Multiple audio flags for same lesson produce one regen action."""
        flags = [
            _make_flag("missing_audio_file", lesson_id="14", record_type="audio"),
            _make_flag("invalid_duration", lesson_id="14", record_type="audio"),
        ]
        summary = _make_summary(flags)
        actions = plan_remediations(summary)
        audio_actions = [a for a in actions if a.strategy == STRATEGY_AUDIO_REGEN]
        assert len(audio_actions) == 1

    def test_manual_flags_get_manual_review_status(self) -> None:
        flags = [_make_flag("near_duplicate_lesson_text", severity="warn")]
        summary = _make_summary(flags)
        actions = plan_remediations(summary)
        assert len(actions) == 1
        assert actions[0].status == "manual_review"

    def test_code_filter(self) -> None:
        """Code filter limits which flags are acted on."""
        flags = [
            _make_flag("empty_extracted_text"),
            _make_flag("very_short_record", severity="warn"),
        ]
        summary = _make_summary(flags)
        actions = plan_remediations(
            summary, code_filter={"empty_extracted_text"}
        )
        assert len(actions) == 1
        assert actions[0].flag.code == "empty_extracted_text"

    def test_unknown_code_skipped(self) -> None:
        """Flags with unknown codes get skipped status."""
        flags = [_make_flag("some_future_code")]
        summary = _make_summary(flags)
        actions = plan_remediations(summary)
        assert len(actions) == 1
        assert actions[0].status == "skipped"
        assert "no automated fix" in actions[0].detail


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


class TestExecuteRemediations:
    def test_dry_run_changes_nothing(self, tmp_path: Path) -> None:
        """Dry run returns report but normalized.jsonl is unchanged."""
        data_dir = str(tmp_path)
        normalized = tmp_path / "normalized.jsonl"
        normalized.write_text(
            json.dumps({"lesson_id": "43", "concept": "", "slide_text": "test"})
            + "\n"
        )
        file_hash_before = hashlib.md5(normalized.read_bytes()).hexdigest()

        flag = _make_flag("empty_extracted_text", lesson_id="43")
        actions = [
            RemediationAction(flag=flag, strategy=STRATEGY_REEXTRACT, status="pending")
        ]
        report = execute_remediations(actions, data_dir=data_dir, dry_run=True)

        file_hash_after = hashlib.md5(normalized.read_bytes()).hexdigest()
        assert file_hash_before == file_hash_after
        assert report.fixed_count == 0

    @patch("corpus.ufli.remediate.extract_lesson")
    def test_reextract_failed_when_raw_dir_missing(
        self, mock_extract: MagicMock, tmp_path: Path
    ) -> None:
        """Re-extract for a lesson with no raw dir produces failed status."""
        mock_extract.return_value = None
        data_dir = str(tmp_path)
        normalized = tmp_path / "normalized.jsonl"
        normalized.write_text(
            json.dumps({"lesson_id": "43", "slide_text": "old"}) + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text(
            json.dumps({"lesson_id": "43", "lesson_group": "G", "concept": "c"})
            + "\n"
        )

        flag = _make_flag("empty_extracted_text", lesson_id="43")
        actions = [
            RemediationAction(flag=flag, strategy=STRATEGY_REEXTRACT, status="pending")
        ]
        execute_remediations(
            actions, data_dir=data_dir, dry_run=False, skip_reindex=True
        )
        assert actions[0].status == "failed"
        assert "raw directory missing" in actions[0].detail

    @patch("corpus.ufli.remediate.extract_lesson")
    def test_reextract_needs_manifest_metadata(
        self, mock_extract: MagicMock, tmp_path: Path
    ) -> None:
        """Re-extract looks up lesson_group and concept from manifest."""
        mock_extract.return_value = LessonContent(
            lesson_id="43",
            lesson_group="G",
            concept="short vowels",
            slide_text="new text",
            slide_count=5,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        )
        data_dir = str(tmp_path)
        normalized = tmp_path / "normalized.jsonl"
        normalized.write_text(
            json.dumps({"lesson_id": "43", "slide_text": "old"}) + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text(
            json.dumps(
                {"lesson_id": "43", "lesson_group": "G", "concept": "short vowels"}
            )
            + "\n"
        )

        flag = _make_flag("empty_extracted_text", lesson_id="43")
        actions = [
            RemediationAction(flag=flag, strategy=STRATEGY_REEXTRACT, status="pending")
        ]
        execute_remediations(
            actions, data_dir=data_dir, dry_run=False, skip_reindex=True
        )
        mock_extract.assert_called_once_with("43", "G", "short vowels", data_dir)
        assert actions[0].status == "fixed"

    def test_concept_backfill_from_manifest(self, tmp_path: Path) -> None:
        """missing_concept with non-empty manifest concept patches normalized.jsonl."""
        data_dir = str(tmp_path)
        normalized = tmp_path / "normalized.jsonl"
        normalized.write_text(
            json.dumps(
                {
                    "lesson_id": "43",
                    "lesson_group": "G",
                    "concept": "",
                    "slide_text": "test",
                    "slide_count": 3,
                    "decodable_text": "",
                    "home_practice_text": "",
                    "additional_text": "",
                }
            )
            + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text(
            json.dumps(
                {
                    "lesson_id": "43",
                    "lesson_group": "G",
                    "concept": "short a",
                }
            )
            + "\n"
        )

        flag = _make_flag("missing_concept", lesson_id="43", severity="warn")
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_CONCEPT_BACKFILL, status="pending"
            )
        ]
        execute_remediations(
            actions, data_dir=data_dir, dry_run=False, skip_reindex=True
        )
        assert actions[0].status == "fixed"

        # Verify normalized.jsonl was patched
        rec = json.loads(normalized.read_text().strip())
        assert rec["concept"] == "short a"

    def test_concept_backfill_skipped_for_empty_manifest(
        self, tmp_path: Path
    ) -> None:
        """missing_concept for lesson A (manifest concept also empty) -> skipped."""
        data_dir = str(tmp_path)
        normalized = tmp_path / "normalized.jsonl"
        normalized.write_text(
            json.dumps(
                {
                    "lesson_id": "A",
                    "lesson_group": "",
                    "concept": "",
                    "slide_text": "test",
                    "slide_count": 1,
                    "decodable_text": "",
                    "home_practice_text": "",
                    "additional_text": "",
                }
            )
            + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text(
            json.dumps({"lesson_id": "A", "lesson_group": "", "concept": ""}) + "\n"
        )

        flag = _make_flag("missing_concept", lesson_id="A", severity="warn")
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_CONCEPT_BACKFILL, status="pending"
            )
        ]
        execute_remediations(
            actions, data_dir=data_dir, dry_run=False, skip_reindex=True
        )
        assert actions[0].status == "skipped"
        assert "pre-phonics" in actions[0].detail

    @patch("corpus.ufli.remediate.extract_lesson")
    def test_concept_backfill_skipped_when_reextract_handled_lesson(
        self, mock_extract: MagicMock, tmp_path: Path
    ) -> None:
        """If phase 1 re-extract already replaced a lesson, phase 2 skips it."""
        mock_extract.return_value = LessonContent(
            lesson_id="43",
            lesson_group="G",
            concept="short vowels",
            slide_text="text",
            slide_count=3,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        )
        data_dir = str(tmp_path)
        normalized = tmp_path / "normalized.jsonl"
        normalized.write_text(
            json.dumps({"lesson_id": "43", "slide_text": "old", "concept": ""}) + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text(
            json.dumps(
                {"lesson_id": "43", "lesson_group": "G", "concept": "short vowels"}
            )
            + "\n"
        )

        actions = [
            RemediationAction(
                flag=_make_flag("empty_extracted_text", lesson_id="43"),
                strategy=STRATEGY_REEXTRACT,
                status="pending",
            ),
            RemediationAction(
                flag=_make_flag("missing_concept", lesson_id="43", severity="warn"),
                strategy=STRATEGY_CONCEPT_BACKFILL,
                status="pending",
            ),
        ]
        execute_remediations(
            actions, data_dir=data_dir, dry_run=False, skip_reindex=True
        )
        assert actions[0].status == "fixed"  # re-extract worked
        assert actions[1].status == "skipped"  # concept backfill skipped
        assert "already re-extracted" in actions[1].detail


# ---------------------------------------------------------------------------
# Patch tests
# ---------------------------------------------------------------------------


class TestPatchNormalizedJsonl:
    def test_preserves_order(self, tmp_path: Path) -> None:
        """Patching one lesson doesn't reorder others."""
        data_dir = str(tmp_path)
        lines = [
            json.dumps({"lesson_id": "1", "slide_text": "one"}),
            json.dumps({"lesson_id": "2", "slide_text": "two"}),
            json.dumps({"lesson_id": "3", "slide_text": "three"}),
        ]
        (tmp_path / "normalized.jsonl").write_text("\n".join(lines) + "\n")

        patch = LessonContent(
            lesson_id="2",
            lesson_group="",
            concept="updated",
            slide_text="two-new",
            slide_count=0,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        )
        _patch_normalized_jsonl(data_dir, {"2": patch})

        result_lines = (tmp_path / "normalized.jsonl").read_text().strip().split("\n")
        assert len(result_lines) == 3
        ids = [json.loads(ln)["lesson_id"] for ln in result_lines]
        assert ids == ["1", "2", "3"]
        assert json.loads(result_lines[1])["concept"] == "updated"

    def test_atomic_write(self, tmp_path: Path) -> None:
        """Write failure doesn't leave a half-written file."""
        data_dir = str(tmp_path)
        original = json.dumps({"lesson_id": "1", "slide_text": "original"}) + "\n"
        (tmp_path / "normalized.jsonl").write_text(original)

        patch = LessonContent(
            lesson_id="1",
            lesson_group="",
            concept="",
            slide_text="new",
            slide_count=0,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        )

        with patch_os_replace_to_fail():
            with pytest.raises(OSError):
                _patch_normalized_jsonl(data_dir, {"1": patch})

        # Original file should be intact
        assert (tmp_path / "normalized.jsonl").read_text() == original

    def test_preserves_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed (non-JSON) lines in normalized.jsonl are preserved as-is."""
        data_dir = str(tmp_path)
        lines = [
            json.dumps({"lesson_id": "1", "slide_text": "one"}),
            "this is not valid json {{{",
            json.dumps({"lesson_id": "3", "slide_text": "three"}),
        ]
        (tmp_path / "normalized.jsonl").write_text("\n".join(lines) + "\n")

        patch = LessonContent(
            lesson_id="3",
            lesson_group="",
            concept="patched",
            slide_text="three-new",
            slide_count=0,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        )
        _patch_normalized_jsonl(data_dir, {"3": patch})

        result_lines = (tmp_path / "normalized.jsonl").read_text().strip().split("\n")
        assert len(result_lines) == 3
        assert result_lines[1] == "this is not valid json {{{"
        assert json.loads(result_lines[2])["concept"] == "patched"


class _RaiseOnReplace:
    """Context manager to make os.replace raise."""

    def __init__(self) -> None:
        self._original = os.replace

    def __enter__(self) -> None:
        os.replace = self._raise  # type: ignore[assignment]

    def __exit__(self, *args: object) -> None:
        os.replace = self._original  # type: ignore[assignment]

    @staticmethod
    def _raise(src: str, dst: str) -> None:
        # Clean up the temp file to simulate partial failure
        try:
            os.unlink(src)
        except OSError:
            pass
        raise OSError("simulated os.replace failure")


def patch_os_replace_to_fail() -> _RaiseOnReplace:
    return _RaiseOnReplace()


# ---------------------------------------------------------------------------
# Index deletion tests
# ---------------------------------------------------------------------------


class TestStaleIndexDeletion:
    def test_stale_index_deleted_not_upserted(self, tmp_path: Path) -> None:
        """stale_curriculum_index flag triggers delete, not add_document."""
        data_dir = str(tmp_path)
        (tmp_path / "normalized.jsonl").write_text("")
        (tmp_path / "manifest.jsonl").write_text("")

        mock_collection = MagicMock()

        flag = _make_flag("stale_curriculum_index", lesson_id="99", severity="warn")
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_DELETE_STALE, status="pending"
            )
        ]

        with (
            patch("rag.store.get_store") as mock_get_store,
            patch(
                "rag.store.get_or_create_collection",
                return_value=mock_collection,
            ),
            patch("rag.store.delete_document") as mock_delete,
        ):
            mock_get_store.return_value = MagicMock()
            execute_remediations(
                actions, data_dir=data_dir, dry_run=False, skip_reindex=True
            )

        mock_delete.assert_called_once_with(
            mock_collection, "curriculum_ufli_99"
        )
        assert actions[0].status == "fixed"


# ---------------------------------------------------------------------------
# Re-index tests
# ---------------------------------------------------------------------------


class TestReindex:
    def test_reindex_skipped_without_api_key(self, tmp_path: Path) -> None:
        """Re-index with unavailable embedding API produces skipped status."""
        data_dir = str(tmp_path)
        (tmp_path / "normalized.jsonl").write_text(
            json.dumps({"lesson_id": "43", "slide_text": "text"}) + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text("")

        flag = _make_flag(
            "missing_curriculum_index", lesson_id="43", severity="warn"
        )
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_REINDEX, status="pending"
            )
        ]

        with patch("rag.client.rag_available", return_value=False):
            execute_remediations(
                actions, data_dir=data_dir, dry_run=False, skip_reindex=False
            )

        assert actions[0].status == "skipped"
        assert "API" in actions[0].detail or "api" in actions[0].detail.lower()

    def test_reindex_uses_upsert(self, tmp_path: Path) -> None:
        """Re-indexed lesson overwrites old ChromaDB entry."""
        data_dir = str(tmp_path)
        (tmp_path / "normalized.jsonl").write_text(
            json.dumps(
                {
                    "lesson_id": "43",
                    "slide_text": "some content",
                    "lesson_group": "G",
                    "concept": "test",
                }
            )
            + "\n"
        )
        (tmp_path / "manifest.jsonl").write_text("")

        flag = _make_flag(
            "missing_curriculum_index", lesson_id="43", severity="warn"
        )
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_REINDEX, status="pending"
            )
        ]

        mock_embed_result = MagicMock()
        mock_embed_result.values = [0.1] * 768
        mock_collection = MagicMock()

        with (
            patch("rag.client.rag_available", return_value=True),
            patch("rag.embeddings.embed_text", return_value=mock_embed_result),
            patch("rag.store.get_store", return_value=MagicMock()),
            patch(
                "rag.store.get_or_create_collection",
                return_value=mock_collection,
            ),
            patch("rag.store.add_document") as mock_add,
        ):
            execute_remediations(
                actions, data_dir=data_dir, dry_run=False, skip_reindex=False
            )

        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs[1]["doc_id"] == "curriculum_ufli_43"
        assert actions[0].status == "fixed"


# ---------------------------------------------------------------------------
# Audio re-generation tests
# ---------------------------------------------------------------------------


class TestAudioRegen:
    def test_audio_regen_calls_generate_audio_companion(
        self, tmp_path: Path
    ) -> None:
        """Audio flag for pilot lesson routes to generate_audio_companion."""
        data_dir = str(tmp_path)
        (tmp_path / "normalized.jsonl").write_text("")
        (tmp_path / "manifest.jsonl").write_text("")

        flag = _make_flag(
            "missing_audio_file", lesson_id="14", record_type="audio"
        )
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_AUDIO_REGEN, status="pending"
            )
        ]

        with patch(
            "corpus.ufli.audio_companion.generate_audio_companion"
        ) as mock_gen:
            mock_gen.return_value = {"planned": 1, "generated": 1, "skipped": 0}
            execute_remediations(
                actions,
                data_dir=data_dir,
                dry_run=False,
                skip_reindex=True,
            )

        mock_gen.assert_called_once_with(
            data_dir=data_dir,
            lesson_set="pilot_micro",
            lesson_id="14",
            dry_run=False,
            force=True,
        )
        assert actions[0].status == "fixed"

    def test_audio_regen_skipped_for_non_pilot_lesson(
        self, tmp_path: Path
    ) -> None:
        """Audio flag for lesson 43 (not pilot) produces skipped status."""
        data_dir = str(tmp_path)
        (tmp_path / "normalized.jsonl").write_text("")
        (tmp_path / "manifest.jsonl").write_text("")

        flag = _make_flag(
            "missing_audio_file", lesson_id="43", record_type="audio"
        )
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_AUDIO_REGEN, status="pending"
            )
        ]
        execute_remediations(
            actions, data_dir=data_dir, dry_run=False, skip_reindex=True
        )
        assert actions[0].status == "skipped"
        assert "pilot scope" in actions[0].detail

    def test_audio_regen_skipped_without_api_key(self, tmp_path: Path) -> None:
        """Audio regen without ElevenLabs key produces failed status."""
        data_dir = str(tmp_path)
        (tmp_path / "normalized.jsonl").write_text("")
        (tmp_path / "manifest.jsonl").write_text("")

        flag = _make_flag(
            "missing_audio_file", lesson_id="1", record_type="audio"
        )
        actions = [
            RemediationAction(
                flag=flag, strategy=STRATEGY_AUDIO_REGEN, status="pending"
            )
        ]

        with patch(
            "corpus.ufli.audio_companion.generate_audio_companion",
            side_effect=RuntimeError("ELEVENLABS_API_KEY not set"),
        ):
            execute_remediations(
                actions,
                data_dir=data_dir,
                dry_run=False,
                skip_reindex=True,
            )

        assert actions[0].status == "failed"
        assert "audio generation failed" in actions[0].detail


# ---------------------------------------------------------------------------
# delete_document wrapper test
# ---------------------------------------------------------------------------


class TestDeleteDocumentWrapper:
    def test_delete_document_calls_collection_delete(self) -> None:
        """delete_document() calls collection.delete(ids=[doc_id])."""
        from rag.store import delete_document

        mock_collection = MagicMock()
        delete_document(mock_collection, "test_doc_123")
        mock_collection.delete.assert_called_once_with(ids=["test_doc_123"])


# ---------------------------------------------------------------------------
# Report and discovery tests
# ---------------------------------------------------------------------------


class TestWriteReport:
    def test_writes_all_artifacts(self, tmp_path: Path) -> None:
        flag = _make_flag("near_duplicate_lesson_text", severity="warn")
        report = RemediationReport(
            generated_at="2026-03-19T00:00:00Z",
            actions=[
                RemediationAction(
                    flag=flag,
                    strategy=STRATEGY_MANUAL,
                    status="manual_review",
                )
            ],
            manual_review_count=1,
        )
        write_remediation_report(report, str(tmp_path))
        assert (tmp_path / "remediation_report.json").exists()
        assert (tmp_path / "remediation_report.md").exists()
        assert (tmp_path / "manual_review_needed.csv").exists()


class TestFindLatestAuditDir:
    def test_finds_latest_timestamp(self, tmp_path: Path) -> None:
        (tmp_path / "20260101_100000").mkdir()
        (tmp_path / "20260319_123456").mkdir()
        (tmp_path / "20260201_080000").mkdir()
        result = find_latest_audit_dir(str(tmp_path))
        assert result is not None
        assert result.endswith("20260319_123456")

    def test_ignores_non_timestamp_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "latest").mkdir()
        (tmp_path / "backup").mkdir()
        (tmp_path / "20260319_123456").mkdir()
        result = find_latest_audit_dir(str(tmp_path))
        assert result is not None
        assert result.endswith("20260319_123456")

    def test_returns_none_when_empty(self, tmp_path: Path) -> None:
        result = find_latest_audit_dir(str(tmp_path))
        assert result is None

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        (tmp_path / "not_a_timestamp").mkdir()
        result = find_latest_audit_dir(str(tmp_path))
        assert result is None


class TestManualReviewFlagsNotAutoFixed:
    def test_manual_review_status(self) -> None:
        """near_duplicate_lesson_text produces manual_review status."""
        flags = [_make_flag("near_duplicate_lesson_text", severity="warn")]
        summary = _make_summary(flags)
        actions = plan_remediations(summary)
        assert len(actions) == 1
        assert actions[0].status == "manual_review"
        assert actions[0].strategy == STRATEGY_MANUAL
