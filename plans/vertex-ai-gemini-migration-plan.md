# Vertex AI Gemini Migration — Implementation Plan v1

> **Goal:** Migrate all Gemini-backed app functionality from direct Gemini Developer API
> key usage to Vertex AI, while preserving the current deterministic pipeline behavior
> and keeping OpenAI / Claude integrations unchanged.

> **Status:** Planning only. Not yet implemented.
> **Date:** 2026-03-15
> **Branch Target:** follow-up to `codex/feature-gemini-embedding-2-rag`

---

## Table of Contents

1. [Why This Change](#1-why-this-change)
2. [Current State](#2-current-state)
3. [Migration Goals](#3-migration-goals)
4. [Non-Goals](#4-non-goals)
5. [Target Architecture](#5-target-architecture)
6. [Environment and Auth Model](#6-environment-and-auth-model)
7. [File-by-File Migration Scope](#7-file-by-file-migration-scope)
8. [Implementation Phases](#8-implementation-phases)
9. [Testing Strategy](#9-testing-strategy)
10. [Operational Rollout](#10-operational-rollout)
11. [Risks and Mitigations](#11-risks-and-mitigations)
12. [Acceptance Criteria](#12-acceptance-criteria)
13. [Open Questions](#13-open-questions)

---

## 1. Why This Change

The repo currently uses two different Google access patterns:

- Direct Gemini API key access for most generative features
- Vertex-capable access only inside the RAG embedding stack

That split was intentional during the RAG work, but it creates long-term problems:

- Auth behavior is inconsistent across modules
- Error handling and configuration differ by feature
- There is no single place to reason about Google model access
- Production governance is weaker for the non-RAG Gemini paths
- Future evals and production debugging are harder because Gemini behavior depends on
  which module is calling it

The migration goal is to standardize Gemini access on Vertex AI for all Google-backed
features while keeping the rest of the app architecture stable.

---

## 2. Current State

### Current Gemini access by module

| Area | File(s) | Current access mode | Notes |
|---|---|---|---|
| RAG embeddings + retrieval | `rag/client.py`, `rag/embeddings.py`, `rag/retrieval.py`, `rag/indexer.py`, `corpus/ufli/ingest.py` | Mixed: direct Gemini API or Vertex AI | `RAG_GEMINI_BACKEND=auto|api_key|vertex`; auto currently prefers API key when present |
| Vision extraction | `extract/vision.py` | Direct Gemini API | Uses `genai.Client(api_key=...)`; now accepts `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Generic Gemini adapter | `extract/adapter.py` | Direct Gemini API | Auto-detection still checks `GEMINI_API_KEY` only |
| AI review | `validate/ai_review.py` | Direct Gemini API | Gemini first, OpenAI fallback |
| Asset generation | `render/asset_gen.py` | Direct Gemini API | Uses `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Avatar/overlay variant generation | `companion/generate_overlays.py` | Direct Gemini API | Uses `GEMINI_API_KEY` only |

### Important current behavior

- Embeddings are the only area with real Vertex support today.
- In this workspace, the RAG stack currently resolves to API-key mode because:
  - `GEMINI_API_KEY` is present
  - `GOOGLE_CLOUD_PROJECT` is present
  - `RAG_GEMINI_BACKEND` is unset
  - `rag/client.py` prefers API key over Vertex in `auto`
- Existing non-RAG Gemini code does not use ADC or `vertexai=True`.

---

## 3. Migration Goals

### Primary goals

1. Replace direct Gemini API key client creation with Vertex AI client creation for all
   Gemini-backed codepaths.
2. Centralize Google client construction and model selection in one shared module.
3. Standardize environment validation and error messages.
4. Preserve current product behavior:
   - deterministic core still works with Google access unavailable
   - OpenAI and Claude integrations remain unchanged
   - current model tasks and outputs remain as close as possible
5. Make Vertex the default and only Gemini runtime for production use.

### Secondary goals

1. Remove module-by-module Gemini env handling drift.
2. Make test coverage explicit for both configured and unconfigured Google access.
3. Eliminate ambiguity about whether a given feature is using API key or Vertex.

---

## 4. Non-Goals

This plan does not include:

- Replacing OpenAI or Claude features
- Redesigning the extraction, adaptation, or rendering pipeline
- Changing deterministic fallback behavior
- Reworking ChromaDB / RAG retrieval logic beyond client/auth unification
- Solving Codex sandbox DNS/network limits
- Building a separate GCP deployment system

If a later decision requires removing Google API key support from local development
entirely, that should be treated as a rollout policy choice, not a prerequisite for
the code migration itself.

---

## 5. Target Architecture

### New shared Google client module

Create a shared module for all Google model access. Proposed location:

- `google_ai/client.py`

Responsibilities:

- Build `google.genai.Client(vertexai=True, project=..., location=...)`
- Validate required Vertex env and ADC availability
- Expose small helper functions for:
  - generative text client access
  - image generation client access
  - embedding client access
- Centralize model naming constants
- Centralize logging and startup diagnostics

### Why not keep `rag/client.py` as the shared module

`rag/client.py` currently encodes RAG-specific concerns:

- embedding fallback models
- backend auto-selection
- RAG-specific availability semantics

That is the wrong abstraction for vision extraction, review, and image generation.
The migration should move shared Google access to a neutral module and then make
`rag/client.py` a thin wrapper or delete its client factory logic entirely.

### Target call pattern

All Gemini-backed modules should converge on a shared pattern:

```python
from google_ai.client import get_vertex_genai_client

client = get_vertex_genai_client()
response = client.models.generate_content(...)
```

For embeddings:

```python
from google_ai.client import get_vertex_genai_client

client = get_vertex_genai_client()
response = client.models.embed_content(...)
```

### Fallback philosophy

- No Vertex config or ADC:
  - Gemini-backed features should fail closed and return the existing deterministic
    fallback or no-op path.
- OpenAI / Claude:
  - continue to work exactly as they do today

This keeps the deterministic core intact.

---

## 6. Environment and Auth Model

### Required Vertex configuration

Standardize on:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION` with default `us-central1`

### Required runtime auth

Use Application Default Credentials:

- local: `gcloud auth application-default login`
- CI / production: service account with Vertex permissions

### Optional migration-period compatibility

During implementation only, support a temporary feature flag:

- `GOOGLE_GENAI_BACKEND=vertex|api_key`

Recommended behavior during migration:

- default: `vertex`
- temporary fallback: `api_key` only if explicitly requested for local debugging

Recommended behavior after rollout:

- remove `api_key` option for non-RAG codepaths
- simplify to Vertex-only Google runtime

### Required IAM / service setup

- Vertex AI API enabled
- principals have permission to call Gemini models via Vertex
- project/location are aligned with model availability

---

## 7. File-by-File Migration Scope

### New files

- `google_ai/__init__.py`
- `google_ai/client.py`
- `tests/test_google_ai_client.py`

### Existing files to change

#### 1. `rag/client.py`

Changes:

- stop owning general backend selection logic for Gemini
- either:
  - delegate to `google_ai/client.py`, or
  - keep only embedding-model fallback selection
- remove default preference for API-key mode in `auto`

#### 2. `rag/embeddings.py`

Changes:

- use the shared Vertex client provider
- keep embedding model fallback behavior
- preserve current task types and dimensions

#### 3. `extract/vision.py`

Changes:

- replace direct API-key client construction with shared Vertex client
- keep current deterministic fallback to OCR
- update availability and error logging to mention Vertex config / ADC

#### 4. `extract/adapter.py`

Changes:

- update `GeminiAdapter` to use the shared Vertex client
- update auto-detection semantics
- decide whether Gemini auto-detection should depend on Vertex availability rather
  than `GEMINI_API_KEY`
- update image generation helper path accordingly

#### 5. `validate/ai_review.py`

Changes:

- swap direct Gemini API client for shared Vertex client
- keep OpenAI fallback unchanged

#### 6. `render/asset_gen.py`

Changes:

- replace direct Gemini API client with shared Vertex client
- keep caching behavior unchanged
- keep no-op behavior when Google access is unavailable

#### 7. `companion/generate_overlays.py`

Changes:

- replace direct Gemini API client with shared Vertex client
- keep OpenAI judge fallback unchanged

#### 8. `README.md`

Changes:

- replace Gemini API key instructions with Vertex setup guidance where applicable
- clearly document which providers use which auth paths

#### 9. `CLAUDE.md` and `AGENTS.md`

Changes:

- update environment expectations if needed
- clarify that Gemini access is Vertex-based after migration

---

## 8. Implementation Phases

### Phase 1: Shared Vertex client foundation

Deliverables:

- `google_ai/client.py`
- common env validation
- common client construction
- common model availability probe helper

Validation:

- unit tests for configured / unconfigured project + location
- client factory tests with mocked `google.genai.Client`

### Phase 2: Migrate embeddings to shared client

Deliverables:

- `rag/client.py` simplified or partially retired
- `rag/embeddings.py` uses shared client

Validation:

- existing RAG client / embedding tests updated
- minimal live embedding smoke test with `vertex` forced

### Phase 3: Migrate generative text paths

Deliverables:

- `extract/vision.py`
- `extract/adapter.py` Gemini text calls
- `validate/ai_review.py`

Validation:

- unit tests for fallback behavior when Vertex unavailable
- targeted live smoke tests:
  - vision extract on one sample input
  - AI review on one synthetic adapted model

### Phase 4: Migrate image generation paths

Deliverables:

- `render/asset_gen.py`
- `extract/adapter.py` Gemini image generation
- `companion/generate_overlays.py`

Validation:

- unit tests with mocked image responses
- one live asset generation smoke test
- one live overlay generation smoke test

### Phase 5: Remove broad Gemini API-key assumptions

Deliverables:

- update auto-detection and docs
- stop checking `GEMINI_API_KEY` as the primary availability signal for Gemini paths
- decide whether temporary API-key fallback remains anywhere

Validation:

- grep-based audit confirms no direct `genai.Client(api_key=...)` remains outside
  explicit temporary compatibility code

### Phase 6: Full regression and eval pass

Deliverables:

- targeted repo test slices for all touched areas
- live eval reruns using Vertex-backed Gemini

Validation:

- relevant unit tests pass
- live evals produce equivalent or better results vs pre-migration baseline

---

## 9. Testing Strategy

### Unit tests to add or update

- `tests/test_google_ai_client.py`
- `tests/test_rag_client.py`
- `tests/test_rag_embeddings.py`
- `tests/test_adapter.py`
- `tests/test_vision.py`
- tests covering `validate/ai_review.py`
- tests covering `render/asset_gen.py`
- tests covering `companion/generate_overlays.py`

### Required test cases

- Vertex configured and available
- Vertex config missing
- ADC missing or invalid
- model call failure
- deterministic fallback still works
- OpenAI fallback still works where applicable

### Live smoke tests

Run small targeted probes, not full evals first:

1. embed one text string
2. vision-extract one worksheet photo
3. review one adapted worksheet model
4. generate one asset image
5. generate one companion variant

Only after those pass should full evals run.

---

## 10. Operational Rollout

### Recommended rollout order

1. merge shared client + embedding unification
2. verify Vertex embeddings in live smoke tests
3. migrate text-generation paths
4. migrate image-generation paths
5. update docs
6. run full evals

### Rollback strategy

Keep migration commits phase-scoped.

If a phase fails:

- revert only the most recent migration phase
- preserve the shared client and completed lower-risk phases
- do not mix unrelated behavior changes into the same commit

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Vertex model availability differs from direct Gemini API | Medium | Probe model availability centrally and keep model constants configurable |
| ADC missing in local environments | High | Fail clearly, document setup, preserve deterministic fallbacks |
| Auto-detection behavior changes unexpectedly | High | Add explicit Gemini-availability helper and regression tests |
| Image generation behavior differs on Vertex | Medium | Isolate image paths in a dedicated phase and live-smoke them before evals |
| Over-coupling RAG and non-RAG client logic | Medium | Move shared code to a neutral module, not `rag/client.py` |
| Migration obscures existing sandbox DNS issues | Medium | Keep sandbox/network diagnosis separate from auth migration work |

---

## 12. Acceptance Criteria

The migration is complete when all of the following are true:

1. All Gemini-backed modules use the shared Vertex client path.
2. No production Gemini feature depends on `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
3. Embeddings, vision extraction, AI review, asset generation, and companion variant
   generation all work via Vertex AI.
4. OpenAI and Claude paths still work as before.
5. Deterministic OCR / no-op fallbacks still work when Google access is unavailable.
6. Docs reflect the new auth model accurately.
7. Full targeted regression suite passes.
8. Live evals complete successfully using the migrated Vertex-backed Google path.

---

## 13. Open Questions

1. Should the migration remove API-key Gemini support entirely, or keep a temporary
   local-only fallback behind an explicit flag?
2. Should `extract/adapter.py` auto-detection continue preferring OpenAI over Gemini
   after Gemini moves to Vertex, or should Gemini availability be treated differently?
3. Should `rag/client.py` remain as an embedding-model helper, or should it be fully
   folded into the new shared Google client module?
4. Which exact Gemini model IDs should be standardized for:
   - vision extraction
   - AI review
   - image generation
   - embeddings
5. Do we want one repo-wide Google availability helper to drive logs, CLI warnings,
   and tests consistently?

---

## Suggested First Implementation Slice

If this migration is picked up later, the safest first slice is:

1. add `google_ai/client.py`
2. move RAG embeddings onto that shared client
3. force one minimal Vertex embedding smoke test
4. only then start migrating non-RAG generative paths

That keeps the first step narrow, testable, and aligned with the existing partial
Vertex support already in the repo.
