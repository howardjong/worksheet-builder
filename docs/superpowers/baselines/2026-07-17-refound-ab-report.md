# Refound A/B: image_gen baseline vs hybrid_shell

## Baseline
| run | overall_score | severe_defects | total_page_attempts | pages |
|---|---|---|---|---|
| lesson74_acceptance | 0.79 | 1 | 0 | 0 |
| lesson100_uat_r4 | 0.72 | 1 | 0 | 0 |
| lesson101_uat_confirm | 0.62 | 1 | 3 | 3 |

## Candidate (hybrid_shell)
| run | overall_score | severe_defects | total_page_attempts | pages |
|---|---|---|---|---|
| lesson74_hybrid | None | 0 | 0 | 0 |
| lesson100_hybrid | None | 0 | 0 | 0 |
| lesson101_hybrid | None | 0 | 0 | 0 |

hybrid_shell render-stage AI calls are 0 by construction (composed_manifest.json render_api_calls).

## Scope and honesty notes (H2 verification only)

**This is NOT a content-parity comparison.** The candidate `*_hybrid` runs were
generated offline (`OPENAI_API_KEY=`/`GEMINI_API_KEY=`/`GOOGLE_API_KEY=` empty,
`WORKSHEET_LLM_ADAPT=0`, `WORKSHEET_SKIP_ASSET_GEN=1`), so they ran the
deterministic adaptation engine with **no LLM planner and no judge**. That is why
every candidate `overall_score` is `None` (no `judge_verdict.json` written —
judge unavailable, shipped as deterministic-with-warning per D40) and every
candidate `severe_defects` is `0` (no judge ran, not "judge found nothing").
Baseline scores/defects come from full online runs with planner + judge and are
not directly comparable to the offline candidates' content.

**What this report DOES verify — H2's scope, render-stage metrics:**

- **H2a — zero render-stage AI calls.** All three candidate runs logged
  `HTTP Request` count == 0, and all 9 per-worksheet
  `composed_manifest_*.json` files carry `"render_api_calls": 0`. The
  `--render-mode hybrid_shell` flag survived offline (log: "Render mode
  hybrid_shell complete") — no silent `pdf_classic` degradation (E12).
- **H2b — render attempts == pages by construction.** hybrid_shell composes one
  deterministic PDF per worksheet with no retry loop, so page attempts equal
  page count (1 attempt/page). The `total_page_attempts` column reads 0 for
  candidates because hybrid_shell writes no `page_attempt_*.png` retry artifacts
  — attempts are not image-gen retries here. The baseline `lesson101_uat_confirm`
  shows 3 page_attempts across 3 pages (image_gen's per-page attempt PNGs);
  baselines 74/100 predate/skip that artifact and read 0. The decoration-slot
  budget cap (≤ 15% page area) is enforced fail-closed at compose time and
  test-covered in `tests/test_composed_checks.py`.

Owner visual review of the hybrid PDFs vs image_gen pages (Task 11) decides
whether hybrid_shell becomes default. This plan does not flip D29's default
renderer.
