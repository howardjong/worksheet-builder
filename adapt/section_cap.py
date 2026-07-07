"""Hard cap on sections per mini-worksheet — splits over-cap worksheets.

Content-preserving by construction: every chunk survives, redistributed into
more mini-worksheets. Idempotent on compliant input. Applied to BOTH the LLM
and deterministic adaptation outputs (the single choke point is
adapt/engine.py:adapt_lesson()).
"""

from __future__ import annotations

import logging

from adapt.rules import BRAIN_BREAK_PROMPTS, TARGET_MAX_WORKSHEETS_PER_LESSON, AccommodationRules
from adapt.schema import AdaptedActivityModel

logger = logging.getLogger(__name__)


def enforce_section_cap(
    worksheets: list[AdaptedActivityModel],
    rules: AccommodationRules,
) -> list[AdaptedActivityModel]:
    """Split any worksheet whose chunk count exceeds the grade cap."""
    cap = rules.max_sections_per_worksheet
    parts: list[AdaptedActivityModel] = []

    for ws in worksheets:
        if len(ws.chunks) <= cap:
            parts.append(ws)
            continue
        groups = [ws.chunks[i : i + cap] for i in range(0, len(ws.chunks), cap)]
        for g_idx, group in enumerate(groups):
            renumbered = [
                chunk.model_copy(update={"chunk_id": c_idx + 1})
                for c_idx, chunk in enumerate(group)
            ]
            is_last_part = g_idx == len(groups) - 1
            title = ws.worksheet_title
            if title:
                title = f"{title} (Part {g_idx + 1})"
            parts.append(
                ws.model_copy(
                    update={
                        "chunks": renumbered,
                        "worksheet_title": title,
                        "self_assessment": ws.self_assessment if is_last_part else None,
                        "break_prompt": ws.break_prompt if is_last_part else None,
                    }
                )
            )

    # Renumber the package and refresh brain breaks between worksheets.
    total = len(parts)
    final: list[AdaptedActivityModel] = []
    for idx, ws in enumerate(parts):
        is_last = idx == total - 1
        break_prompt = ws.break_prompt
        if is_last:
            break_prompt = None
        elif break_prompt is None:
            break_prompt = BRAIN_BREAK_PROMPTS[idx % len(BRAIN_BREAK_PROMPTS)]
        final.append(
            ws.model_copy(
                update={
                    "worksheet_number": idx + 1,
                    "worksheet_count": total,
                    "break_prompt": break_prompt,
                }
            )
        )
    if total > TARGET_MAX_WORKSHEETS_PER_LESSON:
        logger.warning(
            "Lesson package has %s mini-worksheets, above the %s-worksheet target "
            "(AGENTS.md). Content was split, not dropped — this usually means the "
            "source content volume exceeded what the grade's chunk/section limits "
            "expect. Consider a different adapt path (e.g. WORKSHEET_PLANNER_V2) "
            "if this recurs.",
            total,
            TARGET_MAX_WORKSHEETS_PER_LESSON,
        )
    return final
