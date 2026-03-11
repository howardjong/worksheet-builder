"""RAG retrieval layer with hybrid search and ADHD-safe filtering."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rag.embeddings import embed_text
from rag.store import (
    ADAPTATIONS,
    EXEMPLARS,
    SKILLS,
    WORKSHEETS,
    get_or_create_collection,
    get_store,
    query_similar,
)


class RetrievalResult(BaseModel):
    """A retrieval hit with score and metadata."""

    doc_id: str
    score: float
    metadata: dict[str, Any]
    document: str = ""


class RAGContext(BaseModel):
    """Retrieved context for a pipeline run."""

    similar_worksheets: list[RetrievalResult] = Field(default_factory=list)
    similar_skills: list[RetrievalResult] = Field(default_factory=list)
    prior_adaptations: list[RetrievalResult] = Field(default_factory=list)
    curated_exemplars: list[RetrievalResult] = Field(default_factory=list)


def retrieve_context(
    skill_description: str | None = None,
    extracted_text: str | None = None,
    grade_level: str | None = None,
    n_results: int = 3,
    db_path: str = "vector_store",
) -> RAGContext:
    """Retrieve context using hybrid staged retrieval."""
    store = get_store(db_path)
    context = RAGContext()

    if skill_description:
        skill_emb = embed_text(skill_description, task_type="RETRIEVAL_QUERY")

        skill_col = get_or_create_collection(store, SKILLS)
        if int(skill_col.count()) > 0:
            skill_results = query_similar(skill_col, skill_emb.values, n_results=n_results)
            context.similar_skills = _parse_results(skill_results)

        exemplar_col = get_or_create_collection(store, EXEMPLARS)
        if int(exemplar_col.count()) > 0:
            where_filter: dict[str, Any] = {"all_validators_passed": True}
            if grade_level:
                where_filter = {
                    "$and": [
                        {"all_validators_passed": True},
                        {"grade_level": grade_level},
                    ]
                }
            exemplar_results = query_similar(
                exemplar_col,
                skill_emb.values,
                n_results=n_results,
                where=where_filter,
            )
            context.curated_exemplars = _parse_results(exemplar_results)

        adapt_col = get_or_create_collection(store, ADAPTATIONS)
        if int(adapt_col.count()) > 0:
            adapt_results = query_similar(
                adapt_col,
                skill_emb.values,
                n_results=n_results * 2,
            )
            context.prior_adaptations = _deduplicate_by_source(
                _parse_results(adapt_results),
                limit=n_results,
            )

    if extracted_text:
        text_emb = embed_text(extracted_text[:500], task_type="RETRIEVAL_QUERY")
        ws_col = get_or_create_collection(store, WORKSHEETS)
        if int(ws_col.count()) > 0:
            worksheet_results = query_similar(ws_col, text_emb.values, n_results=n_results)
            context.similar_worksheets = _deduplicate_by_source(
                _parse_results(worksheet_results),
                limit=n_results,
            )

    return context


def _parse_results(results: dict[str, Any]) -> list[RetrievalResult]:
    """Parse ChromaDB query results."""
    ids = (results.get("ids") or [[]])[0]
    if not ids:
        return []

    distances = (results.get("distances") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]

    parsed: list[RetrievalResult] = []
    for idx, doc_id in enumerate(ids):
        distance = 0.0
        if idx < len(distances):
            distance = float(distances[idx])
        score = 1.0 - distance

        metadata: dict[str, Any] = {}
        if idx < len(metadatas) and isinstance(metadatas[idx], dict):
            metadata = dict(metadatas[idx])

        document = ""
        if idx < len(documents) and isinstance(documents[idx], str):
            document = documents[idx]

        parsed.append(
            RetrievalResult(
                doc_id=str(doc_id),
                score=score,
                metadata=metadata,
                document=document,
            )
        )

    return parsed


def _deduplicate_by_source(results: list[RetrievalResult], limit: int) -> list[RetrievalResult]:
    """Return at most one result per source_hash."""
    seen_hashes: set[str] = set()
    deduped: list[RetrievalResult] = []

    for result in results:
        source_hash = str(result.metadata.get("source_hash") or result.doc_id)
        if source_hash in seen_hashes:
            continue
        seen_hashes.add(source_hash)
        deduped.append(result)
        if len(deduped) >= limit:
            break

    return deduped
