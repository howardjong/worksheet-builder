"""Content-driven scene planning — analyzes chunk content to generate scene descriptions."""

from __future__ import annotations

from adapt.schema import ActivityChunk, AdaptedActivityModel


def plan_scenes(adapted: AdaptedActivityModel) -> list[ScenePlan]:
    """Analyze worksheet content and plan character scenes for each chunk.

    Returns a ScenePlan per chunk with scene descriptions driven by actual
    worksheet content (words, activity type).
    """
    plans: list[ScenePlan] = []
    for chunk in adapted.chunks:
        scene = _plan_chunk_scene(chunk, adapted)
        plans.append(scene)
    return plans


class ScenePlan:
    """Plan for a single character scene illustration."""

    def __init__(
        self,
        chunk_id: int,
        scene_prompt: str,
        pose: str,
        activity_context: str,
    ) -> None:
        self.chunk_id = chunk_id
        self.scene_prompt = scene_prompt
        self.pose = pose
        self.activity_context = activity_context


# Map response formats to character poses/activities
_FORMAT_TO_POSE: dict[str, tuple[str, str]] = {
    "match": ("pointing", "pointing at word signs on a wall"),
    "trace": ("writing", "carefully tracing letters with a pencil"),
    "circle": ("thinking", "looking at words and thinking carefully"),
    "fill_blank": ("building", "fitting puzzle pieces together"),
    "write": ("writing", "writing on a clipboard"),
    "read_aloud": ("reading", "reading a large storybook"),
}


def _plan_chunk_scene(
    chunk: ActivityChunk,
    adapted: AdaptedActivityModel,
) -> ScenePlan:
    """Generate a scene plan for a single chunk."""
    format_key = chunk.response_format
    pose, activity_desc = _FORMAT_TO_POSE.get(format_key, ("standing", "learning"))

    # Extract key words from chunk content for context
    content_words = []
    for item in chunk.items[:3]:
        if len(item.content) < 20:
            content_words.append(item.content)

    word_context = ", ".join(content_words) if content_words else adapted.specific_skill

    scene_prompt = (
        f"A friendly cartoon character {activity_desc}. "
        f"The scene relates to the words: {word_context}. "
        f"Child-friendly, bright colors, simple background, no text or letters in the image."
    )

    return ScenePlan(
        chunk_id=chunk.chunk_id,
        scene_prompt=scene_prompt,
        pose=pose,
        activity_context=word_context,
    )


def plan_word_pictures(adapted: AdaptedActivityModel) -> dict[str, str]:
    """Generate picture prompts for word-picture matching items.

    Returns dict of word -> picture prompt for items with response_format="match".
    """
    prompts: dict[str, str] = {}
    for chunk in adapted.chunks:
        for item in chunk.items:
            if item.response_format == "match" and item.picture_prompt:
                prompts[item.content] = (
                    f"A simple cartoon illustration of {item.picture_prompt}. "
                    f"No text, no words, no letters. Clean white background, "
                    f"bright colors, child-friendly style. Small square icon format."
                )
    return prompts
