"""RAG indexer for embedding and storing pipeline artifacts."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from rag.embeddings import embed_multimodal, embed_pdf, embed_text
from rag.store import (
    ADAPTATIONS,
    EXEMPLARS,
    SKILLS,
    WORKSHEETS,
    add_document,
    get_or_create_collection,
    get_store,
)

logger = logging.getLogger(__name__)


def index_run(
    source_image_path: str,
    source_image_hash: str,
    extracted_text: str,
    template_type: str,
    ocr_engine: str,
    region_count: int,
    skill_domain: str,
    skill_name: str,
    grade_level: str,
    adapted_summaries: list[dict[str, Any]],
    pdf_paths: list[str],
    theme_id: str,
    validation_results: dict[str, bool],
    worksheet_mode: str,
    db_path: str = "vector_store",
    profile_name: str | None = None,
) -> None:
    """Index artifacts from a pipeline run into the vector store."""
    store = get_store(db_path)
    now = datetime.now(UTC).isoformat()
    all_passed = bool(validation_results) and all(validation_results.values())
    redacted_text = _redact_learner_info(extracted_text, profile_name)

    try:
        ws_emb = embed_multimodal(redacted_text[:500], source_image_path)
        ws_collection = get_or_create_collection(store, WORKSHEETS)
        add_document(
            ws_collection,
            doc_id=f"ws_{source_image_hash}",
            embedding=ws_emb.values,
            metadata={
                "source_image_hash": source_image_hash,
                "template_type": template_type,
                "ocr_engine": ocr_engine,
                "region_count": region_count,
                "content_type": "multimodal",
                "created_at": now,
            },
            document=redacted_text[:1000],
        )
    except Exception as exc:
        logger.warning("Failed to index worksheet: %s", exc)

    try:
        skill_desc = f"{skill_domain}: {skill_name} (grade {grade_level})"
        skill_emb = embed_text(skill_desc)
        skill_collection = get_or_create_collection(store, SKILLS)
        add_document(
            skill_collection,
            doc_id=f"skill_{source_image_hash}",
            embedding=skill_emb.values,
            metadata={
                "domain": skill_domain,
                "specific_skill": skill_name,
                "grade_level": grade_level,
                "source_hash": source_image_hash,
                "created_at": now,
            },
            document=skill_desc,
        )
    except Exception as exc:
        logger.warning("Failed to index skill: %s", exc)

    adapt_collection = get_or_create_collection(store, ADAPTATIONS)
    for idx, summary in enumerate(adapted_summaries, start=1):
        try:
            adapt_text = json.dumps(summary, sort_keys=True, separators=(",", ":"))
            adapt_emb = embed_text(adapt_text)
            doc_id = f"adapt_{source_image_hash}_{theme_id}_{idx}"
            metadata = {
                "domain": skill_domain,
                "specific_skill": skill_name,
                "grade_level": grade_level,
                "theme_id": theme_id,
                "worksheet_mode": worksheet_mode,
                "source_hash": source_image_hash,
                "all_validators_passed": all_passed,
                "created_at": now,
            }
            metadata.update(_primitive_metadata(summary))

            add_document(
                adapt_collection,
                doc_id=doc_id,
                embedding=adapt_emb.values,
                metadata=metadata,
                document=adapt_text[:1000],
            )
        except Exception as exc:
            logger.warning("Failed to index adaptation %s: %s", idx, exc)

    if not all_passed:
        logger.info("Skipping exemplar indexing because validations did not all pass")
        return

    exemplar_collection = get_or_create_collection(store, EXEMPLARS)
    for idx, pdf_path in enumerate(pdf_paths, start=1):
        try:
            pdf_emb = embed_pdf(pdf_path)
            doc_id = f"exemplar_{source_image_hash}_{theme_id}_{idx}"
            exemplar_summary: dict[str, Any] = {}
            if idx - 1 < len(adapted_summaries):
                exemplar_summary = adapted_summaries[idx - 1]
            metadata = {
                "pdf_path": pdf_path,
                "source_hash": source_image_hash,
                "domain": skill_domain,
                "specific_skill": skill_name,
                "grade_level": grade_level,
                "theme_id": theme_id,
                "worksheet_mode": worksheet_mode,
                "all_validators_passed": True,
                "educator_approved": False,
                "created_at": now,
            }
            metadata.update(_primitive_metadata(exemplar_summary))
            add_document(
                exemplar_collection,
                doc_id=doc_id,
                embedding=pdf_emb.values,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Failed to index exemplar %s: %s", idx, exc)


def _primitive_metadata(summary: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Keep only primitive metadata fields accepted by ChromaDB."""
    primitives: dict[str, str | int | float | bool] = {}
    for key, value in summary.items():
        if isinstance(value, (str, int, float, bool)):
            primitives[key] = value
    return primitives


def _redact_learner_info(text: str, profile_name: str | None) -> str:
    """Redact learner name from text before indexing."""
    if not profile_name:
        return text
    pattern = re.compile(re.escape(profile_name), flags=re.IGNORECASE)
    return pattern.sub("[LEARNER]", text)
