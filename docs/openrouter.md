# OpenRouter configuration

All LLM text, vision, research, and audio evaluation calls use the shared
`ai/openrouter.py` transport. Worksheet and asset image generation, including
the historical `render.fal_eval` evaluation CLI, also use OpenRouter.
Configure `OPENROUTER_API_KEY` through local secret settings or an ignored `.env`.
The key must never be committed. Direct OpenAI, Gemini, Anthropic, Perplexity,
and fal credentials cannot enable or receive inference calls. There is no
fallback to a vendor SDK when the router fails or its key is missing.

Without the router credential, AI assist uses its deterministic baseline,
photo extraction can use OCR, and the default image renderer reports a simpler
PDF fallback. An explicitly skipped quality review is recorded as skipped;
a failed review request with a configured key is not treated as approval.

| Task | Ordered default models |
| --- | --- |
| Worksheet and asset images | `openai/gpt-image-2.5-sunburst`, `google/gemini-3-pro-image`, `bytedance-seed/seedream-5-0-pro`, `google/gemini-3.1-flash-image` |
| Text | `openai/gpt-5.5`, `anthropic/claude-sonnet-4.6`, `google/gemini-3.1-pro-preview` |
| Vision | `openai/gpt-5.5`, `google/gemini-3.1-pro-preview`, `anthropic/claude-sonnet-4.6` |
| Web research | `perplexity/sonar-pro`, `perplexity/sonar` |
| Audio judging | `google/gemini-3-flash-preview`, `google/gemini-2.5-flash` |

These slugs and image reference/portrait capabilities were checked against the
public catalogs on 2026-09-30; [the snapshot](openrouter-models-2026-09-30.json)
records the relevant capabilities. Catalog presence establishes API support,
not comparative worksheet quality. A live visual comparison is still needed
before deciding whether another model should become primary.

Override any ordered chain with comma-separated
`WORKSHEET_OPENROUTER_IMAGE_MODELS`, `WORKSHEET_OPENROUTER_TEXT_MODELS`,
`WORKSHEET_OPENROUTER_VISION_MODELS`, `WORKSHEET_OPENROUTER_RESEARCH_MODELS`,
or `WORKSHEET_OPENROUTER_AUDIO_MODELS`.
Duplicate entries are removed while preserving order. Empty chains disable that
role. `OPENROUTER_BASE_URL` defaults to `https://openrouter.ai/api/v1`.

Images use the [dedicated Image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation),
`POST /images`, with `input_references`. The same profile reference is sent to
every fallback model. Default page aspect ratio is `3:4`; asset and buddy requests
use suitable square/landscape ratios. Responses are decoded and validated as
actual raster images, then normalized to PNG. Missing, malformed, or corrupt
images cannot enter the cache. Text and vision use `POST /chat/completions`.

OpenRouter hosting-provider failover is enabled for each explicit model. Local
transport retries once on timeouts, 408, 429, and selected 5xx responses, honoring
numeric `Retry-After` up to five seconds. Other failures advance to the next
model. Authentication/credit failures stop the chain rather than repeating it.
Requests time out after `WORKSHEET_OPENROUTER_TIMEOUT` seconds (default 180).
Logs omit credentials, private request contents, and provider error bodies.

Every worksheet image still passes exact-text, character-reference, matching,
and substantial learning-scene gates. `WORKSHEET_IMAGE_MAX_ATTEMPTS` controls
quality attempts per model (default three): the default chain can make up to
12 generation attempts per page, plus bounded transport retries and vision
judging calls. Costs depend on the chosen models and number of failures.
Changing the image chain invalidates full-page caches; identity reference packs
remain reusable. Rejected attempt images and gate reports remain in artifacts.

After all image options fail, the builder emits a simpler `pdf_classic` worksheet
and `image_gen_fallback.json` with the reason, plus a warning. The result identifies
the renderer actually used. `WORKSHEET_ALLOW_PDF_FALLBACK=0` instead stops the run.
`WORKSHEET_SKIP_ASSET_GEN=1` explicitly requests offline deterministic rendering.

The legacy adapter import names and `WORKSHEET_IMAGE_PROVIDERS=openai,gemini`
remain compatibility aliases for models hosted through OpenRouter. They all
require `OPENROUTER_API_KEY`; `WORKSHEET_AI_PROVIDER=direct` cannot bypass the
gateway. Configure text-model ordering using the role-specific settings above;
the former direct-provider planner and text-model settings are obsolete.

Audio judging sends the actual MP3/WAV waveform as base64 `input_audio` through
[chat completions](https://openrouter.ai/docs/guides/overview/multimodal/audio).
Missing or empty audio fails instead of becoming a transcript-only judgment.
An explicit audio `--judge-model` selects an OpenRouter model; without it the
audio role chain applies. RAG embeddings retain their Gemini/Vertex backend and
existing vector dimensions. ElevenLabs and Google Cloud speech synthesis are
separate services and retain their current implementations.

For live acceptance, configure the OpenRouter credential, run a committed lesson
with the actual learner profile, inspect all PDF pages and attempt gate reports,
and exercise the fallback chain with the primary image model disabled. Offline
tests cover API protocol, transient failures, malformed outputs, reference
conditioning, gate failures, cache invalidation, and deterministic PDF fallback. Repository tests clear inherited inference
credentials and block unmocked HTTP inference; no live LLM call is needed to run them.
