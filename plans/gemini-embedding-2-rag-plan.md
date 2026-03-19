# Gemini Embedding 2 RAG Architecture — Implementation Plan v2

> **Goal:** Leverage the multimodal capabilities of Gemini Embedding 2 to improve the
> ingest, storage, retrieval, and repackaging of input content for the worksheet builder
> service — with at least one retrieval-to-adaptation path shipping in v1.

> **Branch:** `feature/gemini-embedding-2-rag`
> **Base:** `main` (all 5 milestones complete, 239 tests passing)
> **Date:** 2026-03-11
> **Revision:** v2 — incorporates review feedback

---

## Table of Contents

1. [Why This Change](#1-why-this-change)
2. [Scope Split: What This Plan Does and Does Not Cover](#2-scope-split)
3. [Architecture Overview](#3-architecture-overview)
4. [Pre-Implementation: Branch Strategy](#4-pre-implementation-branch-strategy)
5. [Phase 1: RAG-Scoped Vertex AI Client](#5-phase-1-rag-scoped-vertex-ai-client)
6. [Phase 2: Embedding Service](#6-phase-2-embedding-service)
7. [Phase 3: Vector Store + Metadata Model](#7-phase-3-vector-store--metadata-model)
8. [Phase 4: RAG Retrieval Layer (Hybrid)](#8-phase-4-rag-retrieval-layer-hybrid)
9. [Phase 5: Retrieval-to-Adaptation Consumption](#9-phase-5-retrieval-to-adaptation-consumption)
10. [Phase 6: Pipeline Integration + RunArtifacts](#10-phase-6-pipeline-integration--runartifacts)
11. [Phase 7: Backfill + Evaluation](#11-phase-7-backfill--evaluation)
12. [Phase 8: Testing and Validation](#12-phase-8-testing-and-validation)
13. [Privacy and Data Governance](#13-privacy-and-data-governance)
14. [Batch Concurrency Strategy](#14-batch-concurrency-strategy)
15. [Files Changed / Created](#15-files-changed--created)
16. [Dependencies](#16-dependencies)
17. [Risk Register](#17-risk-register)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Open Questions](#19-open-questions)

---

## 1. Why This Change

### Current Limitations

The existing pipeline processes each worksheet in isolation:
- **Ingest:** Gemini vision extracts text from a single photo, but has no memory of
  previously seen worksheets. Each run starts from scratch.
- **Storage:** Master images are stored as hash-named PNGs. Intermediate artifacts
  (JSON) are stored per-run. No semantic indexing exists.
- **Retrieval:** There is no ability to find "similar worksheets" or reuse adaptation
  decisions from prior runs.
- **Repackaging:** The ADHD adaptation engine generates activities from scratch every
  time, with no reference to how similar skills were adapted before. Distractor words
  are drawn from a static list. Response format selection doesn't learn from prior
  successful runs.

### What Gemini Embedding 2 Unlocks

Gemini Embedding 2 is Google's first natively multimodal embedding model. It maps text,
images, and PDFs into a single unified vector space:

| Capability | Value to Worksheet Builder |
|---|---|
| **Image embedding** | Embed the worksheet photo itself — find visually similar worksheets |
| **Text embedding** | Embed extracted content, skill descriptions, adaptation decisions |
| **PDF embedding** | Embed rendered output PDFs for quality retrieval |
| **Interleaved multimodal** | Embed image+text together for richer semantic representations |
| **Matryoshka dimensionality** | 3072 (max quality) / 1536 / 768 (storage-efficient) |
| **Task-type aware** | `RETRIEVAL_DOCUMENT` vs `RETRIEVAL_QUERY` for asymmetric search |

### Why Vertex AI Backend for RAG (not Developer API)

This is a production app handling **children's data** (learner profiles for ages 5-8
with ADHD accommodations). The Vertex AI backend provides:

- **Enterprise data governance** — data stays within your GCP project boundary
- **No API key in client code** — uses Application Default Credentials (ADC)
- **Audit logging** — Cloud Audit Logs for all embedding API calls
- **VPC Service Controls** — can restrict data exfiltration
- **IAM** — fine-grained access control per service account

The Developer API (API key) provides none of these guarantees.

---

## 2. Scope Split

### This plan covers: RAG infrastructure + embedding + one adaptation path

This plan adds a new `rag/` package with its own Vertex AI client, embedding service,
vector store, retrieval layer, and a concrete retrieval-to-adaptation consumption path.

### This plan does NOT cover: repo-wide Gemini auth migration

The existing Gemini API key authentication in `extract/adapter.py`,
`extract/vision.py`, `validate/ai_review.py`, `render/asset_gen.py`, and
`companion/generate_overlays.py` (5 files, ~15 call sites) is **not changed** by this
plan. Those files continue to use `GEMINI_API_KEY` for their existing generative tasks.

Migrating all generative Gemini calls to Vertex AI is a separate effort because:
- It changes non-RAG behavior across the app (vision extraction, AI review, image gen,
  overlay gen)
- It changes auto-detection priority (currently OpenAI-first) which affects users who
  don't want Vertex AI for text tasks
- It touches 5 files + tests vs. the RAG plan's 0 files of existing code
- It requires a different rollback strategy (existing behavior is API-key-based)

**Recommendation:** File a separate issue for `chore/vertex-ai-migration` after the
RAG plan ships and is validated.

### Why the RAG client can use Vertex AI independently

The `rag/` package creates its own `genai.Client(vertexai=True, ...)` for embedding
calls only. This client is completely separate from the existing generative clients.
The two auth mechanisms coexist cleanly:
- Existing generative calls: `GEMINI_API_KEY` (unchanged)
- New embedding calls: `GOOGLE_CLOUD_PROJECT` + ADC (new)

---

## 3. Architecture Overview

### Current Pipeline
```
Photo -> Capture -> Extract (vision/OCR) -> Skill -> Adapt -> Theme -> Render -> Validate
         (isolated per-run, no memory)
```

### Proposed Pipeline with RAG
```
Photo -> Capture -> Extract (vision/OCR) -> Skill -> Adapt -------> Theme -> Render -> Validate
                         |                    |        ^                                   |
                         v                    v        |                                   v
                     [EMBED]              [EMBED]      |                               [EMBED]
                         |                    |     [consume]                               |
                         +--------+-----------+        |                                   |
                                  |                    |                                   |
                                  v                    |                                   v
                         [Vector Store (ChromaDB)]-----+-----------------------------------+
                                  |                                                   [index]
                                  v
                         [RAG Retrieval Layer]
                                  |
                     +------------+------------+
                     |            |            |
                     v            v            v
                Similar      Prior        Curated
                Worksheets   Adaptations  Exemplars
```

Key difference from v1: **retrieval results are consumed by the adaptation engine**,
not just logged. And **indexing happens through both pipeline branches** (single and
multi-worksheet).

### Hybrid Retrieval Strategy

Phone photos are noisy — image-only similarity is unreliable for matching worksheets
that teach the same skill. The retrieval layer uses a **staged hybrid approach**:

1. **Primary:** Skill text embedding (`"phonics: CVCe long vowel, grade 1"`) — most
   stable signal for finding relevant prior adaptations
2. **Secondary:** Extracted text summary — catches content overlap (same word lists)
3. **Tertiary:** Multimodal (text+image) — used for fused representations when indexing,
   but not as the primary query signal

This avoids over-reliance on image similarity for retrieval while still capturing
visual layout information when indexing.

### What Gets Embedded

| Content Type | Modality | Task Type | Dim | Purpose |
|---|---|---|---|---|
| Extracted text summary | Text | `RETRIEVAL_DOCUMENT` | 768 | Content-similar worksheets |
| Skill description | Text | `RETRIEVAL_DOCUMENT` | 768 | Same-skill worksheets |
| Photo + text (fused) | Multimodal | `RETRIEVAL_DOCUMENT` | 768 | Rich index representation |
| Adapted activity summary | Text | `RETRIEVAL_DOCUMENT` | 768 | Reuse adaptation decisions |
| Rendered PDF | PDF | `RETRIEVAL_DOCUMENT` | 768 | Curated exemplar retrieval |
| User query | Text | `RETRIEVAL_QUERY` | 768 | Asymmetric search queries |

**Dimensionality: 768** — Matryoshka's smallest tier. For a local ChromaDB with
<10K documents, 768 provides excellent quality while keeping storage under 100MB.

---

## 4. Pre-Implementation: Branch Strategy

### Create the feature branch

```bash
cd /Users/hjong/Documents/Projects/worksheet-builder
git checkout main
git pull origin main
git checkout -b feature/gemini-embedding-2-rag
```

### Commit strategy

One commit per phase. Each commit leaves the pipeline fully functional:
- Phase 1: RAG-scoped Vertex AI client (existing tests unchanged)
- Phase 2: Embedding service (new tests only)
- Phase 3: Vector store + metadata model (new tests only)
- Phase 4: RAG retrieval layer (new tests)
- Phase 5: Retrieval-to-adaptation consumption (adapt/ changes + tests)
- Phase 6: Pipeline integration + RunArtifacts (transform.py changes)
- Phase 7: Backfill + evaluation harness
- Phase 8: Full test suite pass

### Rollback plan

All RAG code lives in a new `rag/` package. The only existing file modified is
`transform.py` (Phase 6) and `adapt/engine.py` (Phase 5). Both changes are additive
(new optional parameters with defaults). Reverting the branch deletes `rag/` and
restores the two files — zero risk to existing behavior.

---

## 5. Phase 1: RAG-Scoped Vertex AI Client

### Objective

Create a Vertex AI–backed Gemini client used exclusively by the RAG package. This does
**not** touch any existing generative code.

### New module: `rag/client.py`

```python
"""Vertex AI Gemini client for RAG embedding operations only.

This client is separate from the existing generative Gemini client in
extract/adapter.py (which uses GEMINI_API_KEY). The RAG client uses Vertex AI
for enterprise data governance over embedded children's data.
"""

from __future__ import annotations

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Model configuration — preview model, expect ID to change at GA.
# Check https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings
# for current model availability.
EMBEDDING_MODEL = os.environ.get(
    "GEMINI_EMBEDDING_MODEL", "gemini-embedding-exp-03-07"
)
GENERATIVE_MODEL = os.environ.get(
    "GEMINI_GENERATIVE_MODEL", "gemini-2.5-flash"
)


def rag_available() -> bool:
    """Check if Vertex AI is configured for RAG operations."""
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


@lru_cache(maxsize=1)
def get_rag_client():
    """Return a singleton Gemini client using Vertex AI backend.

    Used exclusively for embedding operations in the RAG package.

    Authentication: Application Default Credentials (ADC).
    Set up via: gcloud auth application-default login
    Or: GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

    Required env vars:
        GOOGLE_CLOUD_PROJECT  — GCP project ID
        GOOGLE_CLOUD_LOCATION — e.g., "us-central1" (default)

    Optional env vars:
        GEMINI_EMBEDDING_MODEL — override embedding model ID
        GEMINI_GENERATIVE_MODEL — override generative model ID
    """
    from google import genai

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not project:
        raise EnvironmentError(
            "GOOGLE_CLOUD_PROJECT must be set for Vertex AI RAG backend. "
            "Run: gcloud auth application-default login && "
            "export GOOGLE_CLOUD_PROJECT=your-project-id"
        )

    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
    )

    # Startup check: verify the embedding model is accessible
    try:
        client.models.get(model=EMBEDDING_MODEL)
        logger.info(f"RAG client initialized: model={EMBEDDING_MODEL}, project={project}")
    except Exception as e:
        logger.warning(
            f"Embedding model '{EMBEDDING_MODEL}' may not be available: {e}. "
            f"Set GEMINI_EMBEDDING_MODEL to override."
        )

    return client
```

### What this does NOT change

- `extract/adapter.py` — still uses `GEMINI_API_KEY`, still OpenAI-first auto-detection
- `extract/vision.py` — still uses `GEMINI_API_KEY`
- `validate/ai_review.py` — still uses `GEMINI_API_KEY`
- `render/asset_gen.py` — still uses `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- `companion/generate_overlays.py` — still uses `GEMINI_API_KEY`
- Auto-detection priority — unchanged (OpenAI > Gemini > Claude > NoOp)

### Env var additions (`.env`)

```bash
# Existing (unchanged)
GEMINI_API_KEY=...
OPENAI_API_KEY=...

# New — Vertex AI backend for RAG embeddings only
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
# GEMINI_EMBEDDING_MODEL=gemini-embedding-exp-03-07  # override if model changes
```

---

## 6. Phase 2: Embedding Service

### Objective
Create a reusable embedding service wrapping `client.models.embed_content()` for all
supported modalities.

### New module: `rag/embeddings.py`

```python
"""Multimodal embedding service using Gemini Embedding 2 via Vertex AI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from google.genai import types
from pydantic import BaseModel

from rag.client import get_rag_client, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS = 768

TaskType = Literal[
    "RETRIEVAL_DOCUMENT",
    "RETRIEVAL_QUERY",
    "SEMANTIC_SIMILARITY",
]


class EmbeddingResult(BaseModel):
    """Result of an embedding operation."""
    values: list[float]
    model: str = EMBEDDING_MODEL
    dimensions: int = DEFAULT_DIMENSIONS
    task_type: str = "RETRIEVAL_DOCUMENT"
    content_type: str = "text"  # text | image | pdf | multimodal


def embed_text(
    text: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed a text string."""
    client = get_rag_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    return EmbeddingResult(
        values=response.embeddings[0].values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="text",
    )


def embed_image(
    image_path: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed an image file (PNG, JPEG)."""
    image_bytes = Path(image_path).read_bytes()
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    client = get_rag_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime)],
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    return EmbeddingResult(
        values=response.embeddings[0].values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="image",
    )


def embed_pdf(
    pdf_path: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed a PDF file (up to 6 pages)."""
    pdf_bytes = Path(pdf_path).read_bytes()

    client = get_rag_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        ],
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    return EmbeddingResult(
        values=response.embeddings[0].values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="pdf",
    )


def embed_multimodal(
    text: str,
    image_path: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed text + image together as a single fused embedding.

    Produces one vector capturing the relationship between the text
    description and the visual content. Used for indexing (not querying).
    """
    image_bytes = Path(image_path).read_bytes()
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    client = get_rag_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[
            types.Content(parts=[
                types.Part(text=text),
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
            ])
        ],
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    return EmbeddingResult(
        values=response.embeddings[0].values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="multimodal",
    )
```

---

## 7. Phase 3: Vector Store + Metadata Model

### Objective
Set up ChromaDB with an enriched metadata schema that captures ADHD-relevant signals
for safe exemplar reuse.

### Why ChromaDB
- Runs locally (no external service)
- Persistent storage to disk
- Built-in cosine similarity search with metadata filtering
- Officially supported by Gemini Embedding 2

### New module: `rag/store.py`

```python
"""ChromaDB vector store for worksheet embeddings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "vector_store"

# Collection names
WORKSHEETS = "worksheets"
SKILLS = "skills"
ADAPTATIONS = "adaptations"
EXEMPLARS = "exemplars"  # Curated, validator-passed outputs only


def get_store(db_path: str = DEFAULT_DB_PATH) -> chromadb.ClientAPI:
    """Get a persistent ChromaDB client."""
    Path(db_path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=db_path)


def get_or_create_collection(
    store: chromadb.ClientAPI,
    name: str,
) -> chromadb.Collection:
    """Get or create a collection with cosine similarity."""
    return store.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def add_document(
    collection: chromadb.Collection,
    doc_id: str,
    embedding: list[float],
    metadata: dict[str, Any],
    document: str = "",
) -> None:
    """Add or update a document in the collection."""
    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[document],
    )


def query_similar(
    collection: chromadb.Collection,
    query_embedding: list[float],
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query for similar documents by embedding vector with optional metadata filter."""
    kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": min(n_results, collection.count()) if collection.count() > 0 else 1,
    }
    if where:
        kwargs["where"] = where
    return collection.query(**kwargs)
```

### Enriched Metadata Model

The v1 metadata was too thin for ADHD-safe reuse. The enriched model captures
validation outcomes, cognitive load signals, and exemplar status.

**`worksheets` collection metadata:**
```json
{
  "source_image_hash": "abc123",
  "template_type": "ufli_word_work",
  "ocr_engine": "gemini_vision",
  "region_count": 10,
  "content_type": "multimodal",
  "created_at": "2026-03-11T10:00:00Z"
}
```

**`skills` collection metadata:**
```json
{
  "domain": "phonics",
  "specific_skill": "CVCe long vowel",
  "grade_level": "1",
  "source_hash": "abc123",
  "created_at": "2026-03-11T10:00:00Z"
}
```

**`adaptations` collection metadata (enriched for ADHD relevance):**
```json
{
  "domain": "phonics",
  "specific_skill": "CVCe long vowel",
  "grade_level": "1",
  "theme_id": "roblox_obby",
  "worksheet_title": "Word Discovery",
  "worksheet_mode": "multi",
  "chunk_count": 3,
  "total_items": 9,
  "response_formats": "match,trace,circle",
  "estimated_minutes": 5,
  "distractor_words": "the,cat,dog,big",
  "skill_parity_passed": true,
  "adhd_compliance_passed": true,
  "ai_review_passed": true,
  "all_validators_passed": true,
  "source_hash": "abc123",
  "created_at": "2026-03-11T10:00:00Z"
}
```

**`exemplars` collection metadata (curated outputs only):**
```json
{
  "pdf_path": "output/worksheet_abc123_1of3.pdf",
  "source_hash": "abc123",
  "domain": "phonics",
  "specific_skill": "CVCe long vowel",
  "grade_level": "1",
  "theme_id": "roblox_obby",
  "worksheet_mode": "multi",
  "page_count": 2,
  "all_validators_passed": true,
  "educator_approved": false,
  "created_at": "2026-03-11T10:00:00Z"
}
```

### Exemplar vs. Raw Separation

Not all indexed adaptations should be reused. The design separates:
- **`adaptations` collection:** All adaptation runs, including those with validator
  warnings. Used for analytics and the eval harness.
- **`exemplars` collection:** Only outputs where `all_validators_passed == true`.
  These are the only documents queried for retrieval-to-adaptation consumption.
  An `educator_approved` flag is reserved for future human-in-the-loop curation.

### Deduplication

To prevent near-duplicates from the same source dominating retrieval results:
- Documents are keyed by `{source_hash}_{theme_id}_{worksheet_num}`.
- `upsert` ensures re-processing the same worksheet overwrites rather than duplicates.
- Retrieval results are post-filtered to return at most 1 result per `source_hash`.

---

## 8. Phase 4: RAG Retrieval Layer (Hybrid)

### Objective
Build retrieval functions using a staged hybrid approach: skill text first, content
text second, multimodal only for enrichment.

### New module: `rag/retrieval.py`

```python
"""RAG retrieval layer — hybrid search with ADHD-relevance filtering."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from rag.embeddings import embed_text
from rag.store import (
    get_store, get_or_create_collection, query_similar,
    WORKSHEETS, SKILLS, ADAPTATIONS, EXEMPLARS,
)

logger = logging.getLogger(__name__)


class RetrievalResult(BaseModel):
    """A single retrieval result with similarity score."""
    doc_id: str
    score: float
    metadata: dict[str, Any]
    document: str = ""


class RAGContext(BaseModel):
    """Retrieved context for a pipeline run."""
    similar_worksheets: list[RetrievalResult] = []
    similar_skills: list[RetrievalResult] = []
    prior_adaptations: list[RetrievalResult] = []
    curated_exemplars: list[RetrievalResult] = []


def retrieve_context(
    skill_description: str | None = None,
    extracted_text: str | None = None,
    grade_level: str | None = None,
    n_results: int = 3,
    db_path: str = "vector_store",
) -> RAGContext:
    """Retrieve relevant context using hybrid staged retrieval.

    Retrieval priority (most stable to least stable):
    1. Skill text embedding — find prior adaptations for the same skill
    2. Extracted text embedding — find content-similar worksheets
    3. Curated exemplars — find validator-passed outputs for the grade band

    Image-based retrieval is NOT used for querying (too noisy on phone photos).
    Multimodal embeddings are only used for indexing richness.
    """
    store = get_store(db_path)
    context = RAGContext()

    # --- Stage 1: Skill-based retrieval (primary) ---
    if skill_description:
        skill_emb = embed_text(skill_description, task_type="RETRIEVAL_QUERY")

        # Find similar skills
        skill_col = get_or_create_collection(store, SKILLS)
        if skill_col.count() > 0:
            results = query_similar(
                skill_col, skill_emb.values, n_results=n_results,
            )
            context.similar_skills = _parse_results(results)

        # Find prior adaptations for similar skills (exemplars only)
        exemplar_col = get_or_create_collection(store, EXEMPLARS)
        if exemplar_col.count() > 0:
            where_filter = {"all_validators_passed": True}
            if grade_level:
                where_filter = {
                    "$and": [
                        {"all_validators_passed": True},
                        {"grade_level": grade_level},
                    ]
                }
            results = query_similar(
                exemplar_col, skill_emb.values, n_results=n_results,
                where=where_filter,
            )
            context.curated_exemplars = _parse_results(results)

        # Find all prior adaptations (including non-exemplar, for format mix data)
        adapt_col = get_or_create_collection(store, ADAPTATIONS)
        if adapt_col.count() > 0:
            results = query_similar(
                adapt_col, skill_emb.values, n_results=n_results * 2,
            )
            # Deduplicate by source_hash — max 1 per source worksheet
            context.prior_adaptations = _deduplicate_by_source(
                _parse_results(results), n_results,
            )

    # --- Stage 2: Content-based retrieval (secondary) ---
    if extracted_text:
        text_emb = embed_text(extracted_text[:500], task_type="RETRIEVAL_QUERY")

        ws_col = get_or_create_collection(store, WORKSHEETS)
        if ws_col.count() > 0:
            results = query_similar(
                ws_col, text_emb.values, n_results=n_results,
            )
            context.similar_worksheets = _deduplicate_by_source(
                _parse_results(results), n_results,
            )

    return context


def _parse_results(results: dict[str, Any]) -> list[RetrievalResult]:
    """Parse ChromaDB query results into RetrievalResult list."""
    parsed = []
    if not results or not results.get("ids") or not results["ids"][0]:
        return parsed

    ids = results["ids"][0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    documents = results.get("documents", [[]])[0]

    for i, doc_id in enumerate(ids):
        score = 1.0 - (distances[i] if i < len(distances) else 0.0)
        parsed.append(RetrievalResult(
            doc_id=doc_id,
            score=score,
            metadata=metadatas[i] if i < len(metadatas) else {},
            document=documents[i] if i < len(documents) else "",
        ))

    return parsed


def _deduplicate_by_source(
    results: list[RetrievalResult], limit: int,
) -> list[RetrievalResult]:
    """Return at most 1 result per source_hash, up to limit."""
    seen_hashes: set[str] = set()
    deduped: list[RetrievalResult] = []
    for r in results:
        source_hash = r.metadata.get("source_hash", r.doc_id)
        if source_hash not in seen_hashes:
            seen_hashes.add(source_hash)
            deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped
```

### New module: `rag/indexer.py`

```python
"""RAG indexer — embed and store pipeline artifacts after each run."""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from typing import Any

from rag.embeddings import embed_text, embed_multimodal, embed_pdf
from rag.store import (
    get_store, get_or_create_collection, add_document,
    WORKSHEETS, SKILLS, ADAPTATIONS, EXEMPLARS,
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
    worksheet_mode: str,  # "single" | "multi"
    db_path: str = "vector_store",
) -> None:
    """Index all artifacts from a pipeline run into the vector store.

    Called at the end of a successful pipeline run (after validation).
    Indexes into 4 collections: worksheets, skills, adaptations, exemplars.
    """
    store = get_store(db_path)
    now = datetime.now(UTC).isoformat()
    all_passed = all(validation_results.values())

    # 1. Index source worksheet (multimodal: image + text)
    try:
        ws_emb = embed_multimodal(extracted_text[:500], source_image_path)
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
            document=extracted_text[:1000],
        )
        logger.info(f"Indexed worksheet: ws_{source_image_hash}")
    except Exception as e:
        logger.warning(f"Failed to index worksheet: {e}")

    # 2. Index skill
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
    except Exception as e:
        logger.warning(f"Failed to index skill: {e}")

    # 3. Index each adaptation with enriched metadata
    adapt_collection = get_or_create_collection(store, ADAPTATIONS)
    for i, summary in enumerate(adapted_summaries):
        try:
            ws_num = i + 1
            adapt_text = json.dumps(summary, indent=0)
            adapt_emb = embed_text(adapt_text)
            doc_id = f"adapt_{source_image_hash}_{theme_id}_{ws_num}"
            add_document(
                adapt_collection,
                doc_id=doc_id,
                embedding=adapt_emb.values,
                metadata={
                    "domain": skill_domain,
                    "specific_skill": skill_name,
                    "grade_level": grade_level,
                    "theme_id": theme_id,
                    "worksheet_mode": worksheet_mode,
                    "source_hash": source_image_hash,
                    "all_validators_passed": all_passed,
                    **{k: v for k, v in summary.items()
                       if isinstance(v, (str, int, float, bool))},
                    "created_at": now,
                },
                document=adapt_text[:1000],
            )
        except Exception as e:
            logger.warning(f"Failed to index adaptation {i+1}: {e}")

    # 4. Index as exemplar only if all validators passed
    if all_passed:
        exemplar_collection = get_or_create_collection(store, EXEMPLARS)
        for i, pdf_path in enumerate(pdf_paths):
            try:
                ws_num = i + 1
                pdf_emb = embed_pdf(pdf_path)
                doc_id = f"exemplar_{source_image_hash}_{theme_id}_{ws_num}"
                add_document(
                    exemplar_collection,
                    doc_id=doc_id,
                    embedding=pdf_emb.values,
                    metadata={
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
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to index exemplar {i+1}: {e}")
    else:
        logger.info("Skipping exemplar indexing — validators did not all pass")
```

---

## 9. Phase 5: Retrieval-to-Adaptation Consumption

### Objective
Wire at least one concrete path from retrieved context into the adaptation engine so
that v1 actually improves worksheet quality, not just builds infrastructure.

### What the adaptation engine consumes

Three lowest-risk, highest-value consumption points:

#### 5.1 Distractor Blacklist

When generating circle/match activities, `_generate_distractors()` currently draws from
a static list of 16 words. With RAG context, it avoids re-using distractors that were
already used in prior worksheets for the same skill.

**Change to `adapt/engine.py`:**

```python
def _generate_distractors(
    target_words: list[str],
    count: int,
    blacklist: set[str] | None = None,
) -> list[str]:
    """Generate plausible non-pattern words as distractors.

    blacklist: words used as distractors in prior adaptations for the same
    skill (from RAG context). Avoids staleness across worksheet sets.
    """
    common_distractors = [
        "the", "and", "cat", "dog", "big", "run", "sit", "hat",
        "pen", "cup", "red", "hop", "fun", "bus", "map", "net",
    ]
    exclude = set(target_words)
    if blacklist:
        exclude |= blacklist
    available = [d for d in common_distractors if d not in exclude]
    return available[:count]
```

#### 5.2 Response Format Mix

When prior adaptations for the same skill exist, prefer a different response format
mix to provide variety across the learner's worksheet history.

**New helper in `adapt/engine.py`:**

```python
def _suggest_format_mix(
    prior_adaptations: list[dict],
    default_formats: list[str],
) -> list[str]:
    """Suggest response formats that differ from prior runs for the same skill.

    If the last 3 adaptations all used match+trace+circle, suggest
    trace+fill_blank+write to maintain novelty across sessions.
    """
    if not prior_adaptations:
        return default_formats

    # Collect formats used in prior runs
    prior_format_sets: list[set[str]] = []
    for adapt in prior_adaptations:
        formats_str = adapt.get("response_formats", "")
        if formats_str:
            prior_format_sets.append(set(formats_str.split(",")))

    if not prior_format_sets:
        return default_formats

    # If the default mix matches the most recent prior run, rotate
    default_set = set(default_formats)
    if prior_format_sets and default_set == prior_format_sets[0]:
        # Swap first two formats to change the mix
        rotated = default_formats.copy()
        if len(rotated) >= 2:
            rotated[0], rotated[1] = rotated[1], rotated[0]
        return rotated

    return default_formats
```

#### 5.3 adapt_lesson() and adapt_activity() Accept Optional RAG Context

**Signature change (backward compatible via defaults):**

```python
def adapt_activity(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_prior_adaptations: list[dict] | None = None,  # NEW
) -> AdaptedActivityModel:
```

```python
def adapt_lesson(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_prior_adaptations: list[dict] | None = None,  # NEW
) -> list[AdaptedActivityModel]:
```

When `rag_prior_adaptations` is provided:
- Extract used distractors → pass as `blacklist` to `_generate_distractors()`
- Extract used format mixes → pass to `_suggest_format_mix()`
- Log which prior adaptations influenced the current run (for auditability)

### What this does NOT do

- Does not change the deterministic core. Without RAG context, behavior is identical.
- Does not use RAG for chunking or scaffolding decisions (those are grade-rule-driven).
- Does not auto-accept RAG suggestions — the adaptation engine still enforces all ADHD
  compliance rules and validation checks.

---

## 10. Phase 6: Pipeline Integration + RunArtifacts

### Objective
Wire RAG into `transform.py` through both single-worksheet and multi-worksheet
branches using a shared `RunArtifacts` data structure.

### Problem with v1 plan

The v1 plan inserted RAG at "Stage 3b / 4b / 9" as if there were a single linear
post-validate step. But `transform.py` branches into `_run_single_worksheet_pipeline()`
and `_run_multi_worksheet_pipeline()` at line 139, and the multi-worksheet path produces
multiple adapted models and multiple PDFs.

### Solution: RunArtifacts

A shared data structure returned by both pipeline helpers, containing everything the
indexer needs:

```python
from pydantic import BaseModel

class RunArtifacts(BaseModel):
    """Collected artifacts from a pipeline run, used for RAG indexing."""
    source_image_path: str
    source_image_hash: str
    extracted_text: str
    template_type: str
    ocr_engine: str
    region_count: int
    skill_domain: str
    skill_name: str
    grade_level: str
    theme_id: str
    worksheet_mode: str  # "single" | "multi"
    adapted_summaries: list[dict]  # one per worksheet
    pdf_paths: list[str]           # one per worksheet
    validation_results: dict[str, bool]  # aggregated pass/fail
```

### Changes to `transform.py`

#### `run_pipeline()` — add RAG retrieval before branching

```python
def run_pipeline(...) -> str:
    # ... Stages 1-4 unchanged ...

    # Stage 4b: RAG retrieval (optional)
    rag_prior = None
    if rag_available():
        try:
            from rag.retrieval import retrieve_context
            skill_desc = f"{skill_model.domain}: {skill_model.specific_skill}"
            rag_context = retrieve_context(
                skill_description=skill_desc,
                extracted_text=source_model.raw_text,
                grade_level=skill_model.grade_level,
            )
            if rag_context.prior_adaptations:
                rag_prior = [r.metadata for r in rag_context.prior_adaptations]
                logger.info(f"  RAG: {len(rag_prior)} prior adaptations found")
        except Exception as e:
            logger.warning(f"  RAG retrieval skipped: {e}")

    # Branch into single/multi — both return RunArtifacts
    if theme.multi_worksheet:
        artifacts = _run_multi_worksheet_pipeline(
            ..., rag_prior_adaptations=rag_prior,
        )
    else:
        artifacts = _run_single_worksheet_pipeline(
            ..., rag_prior_adaptations=rag_prior,
        )

    # Stage 9: RAG indexing (after both branches)
    if rag_available():
        try:
            from rag.indexer import index_run
            index_run(
                source_image_path=artifacts.source_image_path,
                source_image_hash=artifacts.source_image_hash,
                extracted_text=artifacts.extracted_text,
                template_type=artifacts.template_type,
                ocr_engine=artifacts.ocr_engine,
                region_count=artifacts.region_count,
                skill_domain=artifacts.skill_domain,
                skill_name=artifacts.skill_name,
                grade_level=artifacts.grade_level,
                adapted_summaries=artifacts.adapted_summaries,
                pdf_paths=artifacts.pdf_paths,
                theme_id=artifacts.theme_id,
                validation_results=artifacts.validation_results,
                worksheet_mode=artifacts.worksheet_mode,
            )
        except Exception as e:
            logger.warning(f"  RAG indexing skipped: {e}")

    return artifacts.pdf_paths[0] if artifacts.pdf_paths else ""
```

#### Both pipeline helpers return `RunArtifacts`

`_run_single_worksheet_pipeline()` and `_run_multi_worksheet_pipeline()` are updated
to accept `rag_prior_adaptations: list[dict] | None = None` and return `RunArtifacts`
instead of `str`.

Each helper builds `adapted_summaries` with enriched metadata:
```python
adapted_summaries.append({
    "worksheet_title": adapted.worksheet_title or "Untitled",
    "chunk_count": len(adapted.chunks),
    "total_items": sum(len(c.items) for c in adapted.chunks),
    "response_formats": ",".join(sorted(set(c.response_format for c in adapted.chunks))),
    "estimated_minutes": sum(
        int(c.time_estimate.split()[1]) for c in adapted.chunks
        if c.time_estimate and c.time_estimate.startswith("About")
    ),
    "distractor_words": ",".join(sorted(all_distractors)),
})
```

#### `rag_available()` imported from rag package

```python
def rag_available() -> bool:
    """Check if RAG is configured (Vertex AI project set)."""
    try:
        from rag.client import rag_available as _rag_available
        return _rag_available()
    except ImportError:
        return False
```

---

## 11. Phase 7: Backfill + Evaluation

### Objective
Enable indexing of existing artifacts and provide a way to measure retrieval quality.

### New module: `rag/backfill.py`

Without a backfill command, the system has no memory until enough new runs accumulate.

```python
"""Backfill existing pipeline artifacts into the RAG vector store."""

import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@click.command()
@click.option("--artifacts-dir", required=True, help="Path to artifacts directory")
@click.option("--output-dir", required=True, help="Path to output PDFs directory")
@click.option("--db-path", default="vector_store", help="Vector store path")
def backfill(artifacts_dir: str, output_dir: str, db_path: str) -> None:
    """Index existing pipeline artifacts into the RAG vector store.

    Scans artifacts_dir for source_model.json and skill_model.json files,
    pairs them with output PDFs, and indexes everything.
    """
    # Implementation: scan for JSON artifacts, parse, embed, index
    # Uses the same index_run() function as the live pipeline
    ...
```

Usage:
```bash
python -m rag.backfill --artifacts-dir ./output/artifacts --output-dir ./output
```

### New module: `rag/eval.py`

Without an evaluation harness, the plan can't prove that retrieval improves worksheets.

```python
"""RAG evaluation harness — measures retrieval quality and adaptation impact."""

import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@click.command()
@click.option("--test-dir", required=True, help="Directory with test worksheet photos")
@click.option("--profile", required=True, help="Learner profile YAML")
@click.option("--db-path", default="vector_store", help="Vector store path")
def evaluate(test_dir: str, profile: str, db_path: str) -> None:
    """Evaluate RAG retrieval quality on a test set.

    Metrics:
    - retrieval@k: Are the top-k results from the same skill domain?
    - format_diversity: Does the RAG-influenced format mix differ from baseline?
    - distractor_novelty: Are distractors unique across sessions?
    - validator_pass_rate: Do RAG-influenced worksheets pass validators?

    Outputs a JSON report with per-worksheet scores.
    """
    ...
```

Usage:
```bash
python -m rag.eval --test-dir ./samples/input --profile profiles/ian.yaml
```

### Evaluation metrics

| Metric | Measures | Target |
|---|---|---|
| `retrieval@3` | Are top-3 results from the same skill domain? | >80% |
| `format_diversity` | Unique format sets across 5+ runs of same skill | >2 unique sets |
| `distractor_novelty` | % of distractor words not seen in prior runs | >50% |
| `validator_pass_rate` | % of RAG-influenced runs passing all validators | >=100% of baseline |

---

## 12. Phase 8: Testing and Validation

### Test files

**`tests/test_rag_embeddings.py`** — embedding service tests:
```
- test_embed_text_returns_correct_dimensions
- test_embed_text_retrieval_query_vs_document
- test_embed_image_returns_embedding
- test_embed_pdf_returns_embedding
- test_embed_multimodal_returns_embedding
- test_embedding_model_configurable_via_env
```

**`tests/test_rag_store.py`** — vector store tests (in-memory ChromaDB, no mocks):
```
- test_create_persistent_store
- test_add_and_query_document
- test_upsert_overwrites_same_id
- test_query_with_metadata_filter
- test_query_empty_collection_returns_empty
- test_four_collections_created
```

**`tests/test_rag_retrieval.py`** — retrieval tests:
```
- test_retrieve_empty_store_returns_empty_context
- test_retrieve_by_skill_finds_match
- test_retrieve_deduplicates_by_source_hash
- test_exemplars_only_include_validated
- test_grade_level_filter_applied
- test_hybrid_stages_run_in_order
```

**`tests/test_rag_indexer.py`** — indexer tests:
```
- test_index_run_creates_all_collections
- test_only_validated_runs_become_exemplars
- test_enriched_metadata_stored
- test_indexer_failures_dont_raise
```

**`tests/test_rag_integration.py`** — integration tests:
```
- test_pipeline_runs_without_vertex_ai (regression)
- test_pipeline_indexes_after_successful_run
- test_rag_context_passed_to_adaptation
- test_distractor_blacklist_from_rag
- test_format_mix_rotation_from_rag
```

### Testing strategy

| Test Type | Approach |
|---|---|
| Unit (embeddings) | Mock `get_rag_client()`, verify API calls + response parsing |
| Unit (store) | In-memory ChromaDB (`chromadb.Client()`) — no disk, no mocks |
| Unit (retrieval) | Seed ChromaDB with synthetic embeddings, verify queries |
| Unit (indexer) | Mock embedding calls, verify collection entries |
| Unit (adaptation) | Test `_generate_distractors(blacklist=...)` and `_suggest_format_mix()` directly |
| Integration | Mock Gemini API, test full retrieve -> adapt -> index flow |
| Regression | Verify pipeline works identically when `GOOGLE_CLOUD_PROJECT` unset |

### Existing test compatibility

- All 239 existing tests must continue to pass unchanged
- `tests/test_adapter.py` is NOT modified (no auth changes to existing code)
- New `rag_prior_adaptations` parameter has `None` default — all existing callers unaffected

---

## 13. Privacy and Data Governance

### What gets embedded and persisted

| Data | Stored Locally? | Contains PII? | Redaction |
|---|---|---|---|
| Worksheet photo embedding | Yes (768 floats) | No (vector, not reversible) | N/A |
| Extracted text (first 1000 chars) | Yes (ChromaDB document) | Possible (child's name in worksheet) | Redact learner names before indexing |
| Skill description | Yes | No | N/A |
| Adaptation summary (JSON) | Yes | No (structure only, no names) | N/A |
| PDF embedding | Yes (768 floats) | No (vector, not reversible) | N/A |
| PDF file path | Yes (metadata string) | No | N/A |
| Learner profile | **Not indexed** | Yes | Never stored in vector store |
| Source image file | **Not indexed** (only embedding) | Possible | Original image NOT stored in ChromaDB |

### Redaction rules

Before indexing `extracted_text`, strip any tokens that match the learner's name from
the profile:

```python
def _redact_learner_info(text: str, profile_name: str) -> str:
    """Remove learner name from text before indexing."""
    return text.replace(profile_name, "[LEARNER]")
```

### Retention and deletion

- `vector_store/` is local, gitignored, and under the user's control.
- No data is sent to external services other than Vertex AI embedding API calls.
- Vertex AI processes data within the GCP project boundary per its data governance
  terms (no training on customer data).
- **Deletion:** `rm -rf vector_store/` removes all indexed data. A future
  `rag/admin.py delete --source-hash abc123` command can remove specific entries.
- **No automatic retention policy** in v1. All indexed data persists until manually
  deleted.

### What is NOT safe to store locally without additional controls

- Full learner profiles (contains name, grade, accommodations)
- Full worksheet images (may contain handwritten child responses)
- Audio recordings (not applicable today, but noted for future multimodal expansion)

---

## 14. Batch Concurrency Strategy

### Problem

The batch processor (`batch.py`) runs multiple worker threads via
`ThreadPoolExecutor`. The RAG plan uses a local persistent ChromaDB store. Concurrent
writes from multiple threads could cause issues.

### Strategy: Index from the main thread only

RAG indexing is **not** performed inside `_process_single_file()`. Instead:

1. Each worker thread runs the pipeline and returns a `RunArtifacts` object.
2. The main thread collects all `RunArtifacts` from completed futures.
3. After all workers finish (or on graceful shutdown), the main thread indexes all
   artifacts sequentially.

This avoids concurrent ChromaDB writes entirely. The indexing overhead is small
(a few embed calls per worksheet) and runs after the time-sensitive pipeline work is
done.

```python
# In batch.py (main thread, after ThreadPoolExecutor completes)
if rag_available():
    logger.info("Indexing completed worksheets into RAG store...")
    for artifacts in completed_artifacts:
        try:
            index_run(**artifacts.model_dump())
        except Exception as e:
            logger.warning(f"RAG indexing failed for {artifacts.source_image_hash}: {e}")
```

### Alternative for future scaling

If batch indexing becomes a bottleneck (>100 worksheets), consider:
- A process-local queue with a single writer thread
- Switching to a server-backed vector store (Qdrant, Weaviate)

---

## 15. Files Changed / Created

### New Files

| File | Purpose |
|---|---|
| `rag/__init__.py` | RAG package init |
| `rag/client.py` | Vertex AI Gemini client for embeddings (separate from existing) |
| `rag/embeddings.py` | Multimodal embedding service |
| `rag/store.py` | ChromaDB vector store wrapper |
| `rag/retrieval.py` | Hybrid retrieval layer with dedup + metadata filtering |
| `rag/indexer.py` | Post-run indexing with enriched metadata |
| `rag/backfill.py` | Backfill existing artifacts into vector store |
| `rag/eval.py` | Evaluation harness for retrieval quality |
| `tests/test_rag_embeddings.py` | Embedding service tests |
| `tests/test_rag_store.py` | Vector store tests |
| `tests/test_rag_retrieval.py` | Retrieval tests |
| `tests/test_rag_indexer.py` | Indexer tests |
| `tests/test_rag_integration.py` | Integration + regression tests |

### Modified Files

| File | Change | Scope |
|---|---|---|
| `adapt/engine.py` | Add `rag_prior_adaptations` param to `adapt_activity()`/`adapt_lesson()`, add `blacklist` to `_generate_distractors()`, add `_suggest_format_mix()` | Additive, backward compatible |
| `transform.py` | Add `RunArtifacts`, RAG retrieval (Stage 4b), RAG indexing (Stage 9), both helpers return `RunArtifacts` | Additive |
| `requirements.txt` | Add `chromadb>=0.5` | One line |
| `.env` | Add `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` (keep existing keys) | Additive |
| `.gitignore` | Add `vector_store/` | One line |
| `CLAUDE.md` | Document RAG architecture, new env vars, rag/ module | Docs |
| `README.md` | Document RAG features, Vertex AI setup for embeddings | Docs |

### Files NOT Modified

| File | Reason |
|---|---|
| `extract/adapter.py` | Auth migration is a separate effort |
| `extract/vision.py` | Auth migration is a separate effort |
| `validate/ai_review.py` | Auth migration is a separate effort |
| `render/asset_gen.py` | Auth migration is a separate effort |
| `companion/generate_overlays.py` | Auth migration is a separate effort |
| `tests/test_adapter.py` | No auth changes, no mock changes needed |

---

## 16. Dependencies

### New Dependencies

| Package | Version | Purpose |
|---|---|---|
| `chromadb` | `>=0.5` | Local vector store with persistent storage |

### Existing Dependencies (no version change needed)

| Package | Notes |
|---|---|
| `google-genai>=1.0` | Already installed; `embed_content` API available |

### GCP Setup Required (for RAG only — existing features unaffected)

```bash
# One-time setup for RAG embeddings
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1

# Enable Vertex AI API
gcloud services enable aiplatform.googleapis.com --project=$GOOGLE_CLOUD_PROJECT
```

---

## 17. Risk Register

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| R1 | Embedding model ID changes at GA | Embed calls fail | `GEMINI_EMBEDDING_MODEL` env var override; startup compatibility check in `rag/client.py` |
| R2 | Vertex AI auth more complex than API key | Onboarding friction for RAG only | Clear docs; existing features work without Vertex AI |
| R3 | ChromaDB adds ~50MB to install size | Larger venv | Acceptable for semantic search capability |
| R4 | Embedding API rate limits under Vertex AI | Batch indexing may throttle | Sequential indexing from main thread; use existing `RateLimiter` if needed |
| R5 | Phone photo noise in multimodal embeddings | Low similarity for same-skill worksheets | Hybrid retrieval: skill text is primary query signal, not images |
| R6 | Near-duplicate results from same source | Stale retrieval results | Dedup by `source_hash`; keyed upsert prevents duplicates |
| R7 | PDF embedding limited to 6 pages | Multi-worksheet sets may exceed | Each PDF is 2-3 pages; embedded individually |
| R8 | Retrieved prior adaptations may have poor ADHD compliance | Unsafe reuse | Only `exemplars` collection (all validators passed) feeds into adaptation; `adaptations` collection is for analytics only |
| R9 | Concurrent batch writes to ChromaDB | Data corruption | Index from main thread only (Phase 14) |
| R10 | Local vector store has no encryption or access control | Children's metadata at rest | No PII stored; redact learner names; `vector_store/` is local and gitignored |

---

## 18. Acceptance Criteria

### Phase 1: RAG Client
- [ ] `rag/client.py` creates Vertex AI client with `vertexai=True`
- [ ] Existing generative code unchanged (still uses `GEMINI_API_KEY`)
- [ ] `rag_available()` returns `True` when `GOOGLE_CLOUD_PROJECT` set
- [ ] Startup compatibility check logs warning if model unavailable
- [ ] Model ID configurable via `GEMINI_EMBEDDING_MODEL` env var

### Phase 2: Embedding Service
- [ ] `embed_text()`, `embed_image()`, `embed_pdf()`, `embed_multimodal()` all work
- [ ] Matryoshka dimensionality (768) produces correct-length vectors
- [ ] Task type properly set for documents vs queries
- [ ] Unit tests with mocked client

### Phase 3: Vector Store
- [ ] ChromaDB persistent store creates on first run
- [ ] 4 collections: `worksheets`, `skills`, `adaptations`, `exemplars`
- [ ] Upsert keyed by `{source_hash}_{theme_id}_{ws_num}` — idempotent
- [ ] Metadata includes ADHD-relevant signals (validator results, format mix, timing)
- [ ] Only validator-passed runs enter `exemplars` collection
- [ ] `vector_store/` is gitignored

### Phase 4: RAG Retrieval
- [ ] Hybrid retrieval: skill text > content text > multimodal (indexed only)
- [ ] Metadata filtering by `grade_level` and `all_validators_passed`
- [ ] Deduplication by `source_hash`
- [ ] Empty store returns empty context (no errors)
- [ ] `curated_exemplars` field populated (not dead code)

### Phase 5: Retrieval-to-Adaptation
- [ ] `_generate_distractors()` accepts and uses `blacklist` parameter
- [ ] `_suggest_format_mix()` rotates formats when prior runs used same mix
- [ ] `adapt_activity()` and `adapt_lesson()` accept `rag_prior_adaptations`
- [ ] Without RAG context, behavior is identical to current (regression test)
- [ ] RAG-influenced adaptations still pass all ADHD compliance validators

### Phase 6: Pipeline Integration
- [ ] `RunArtifacts` returned by both single and multi-worksheet helpers
- [ ] RAG retrieval runs before branching (Stage 4b)
- [ ] RAG indexing runs after both branches complete (Stage 9)
- [ ] Multi-worksheet path indexes all worksheets and PDFs (not just one)
- [ ] RAG failures logged and swallowed — never block pipeline
- [ ] Pipeline works identically with and without Vertex AI

### Phase 7: Backfill + Eval
- [ ] `rag/backfill.py` indexes existing artifact directories
- [ ] `rag/eval.py` produces JSON report with retrieval@k, format diversity, etc.
- [ ] Backfill is idempotent (re-running doesn't duplicate)

### Phase 8: Testing
- [ ] All new RAG tests pass (~25-30 tests)
- [ ] All 239 existing tests still pass unchanged
- [ ] `make lint` passes
- [ ] `make typecheck` passes
- [ ] Learner names redacted from indexed text

---

## 19. Open Questions

| # | Question | Context | Status |
|---|----------|---------|--------|
| Q1 | **Age range: 5-8 or 6-9?** | Repo docs and plan say 5-8 (K-3). User request says 6-9. Grade filters, chunk sizing, and retrieval policy depend on this. | **Needs reconciliation** |
| Q2 | Should the Vertex AI auth migration for all generative calls be a separate PR? | This plan scopes it out, but there may be urgency to move off API keys entirely. | Open — file as `chore/vertex-ai-migration` |
| Q3 | Is `gemini-embedding-exp-03-07` the right model ID? | Google's Vertex AI page lists `gemini-embedding-2-preview`. Model IDs are in flux during preview. | Mitigated by `GEMINI_EMBEDDING_MODEL` env var |
| Q4 | Should educator approval be required before exemplars feed into adaptation? | The `educator_approved` metadata flag is stored but not enforced in v1. | Future enhancement — v1 uses validator-passed as the quality gate |
| Q5 | What is the retention policy for the local vector store? | No automatic cleanup in v1. Store grows indefinitely. | Future: add `rag/admin.py` with cleanup commands |

---

## Implementation Order

```
Phase 1 (RAG client)                ← Foundation, no existing code changes
  |
Phase 2 (Embedding service)         ← Uses Phase 1 client
  |
Phase 3 (Vector store + metadata)   ← Independent of Phase 2
  |                                    (Phases 2+3 can be parallelized)
  +--------+--------+
           |
Phase 4 (Hybrid retrieval)          ← Depends on Phases 2+3
  |
Phase 5 (Adaptation consumption)    ← Depends on Phase 4; first existing-code change
  |
Phase 6 (Pipeline integration)      ← Depends on Phase 5; transform.py changes
  |
Phase 7 (Backfill + eval)           ← Depends on Phase 6
  |
Phase 8 (Testing + validation)      ← Final pass
```

**New files:** 13
**Modified files:** 7 (only 2 are existing Python source: `adapt/engine.py`, `transform.py`)
**New tests:** ~25-30
**Existing tests affected:** 0
