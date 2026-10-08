"""Small budgeted Decisions compatibility probes; never worksheet approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import in_stage, traced_pipeline


@traced_pipeline
@in_stage("decisions_shadow")
def probe(
    artifacts_dir: str,
    state_path: str,
    questions_path: str,
    model: str,
    *,
    image_paths: list[str] | None = None,
    live: bool = False,
) -> dict[str, object]:
    state = Path(state_path).read_text()
    questions = json.loads(Path(questions_path).read_text())
    if (
        not isinstance(questions, dict)
        or not 1 <= len(questions) <= 200
        or any(
            not isinstance(name, str) or not isinstance(question, str) or not question.strip()
            for name, question in questions.items()
        )
    ):
        raise ValueError("Questions must be a JSON object mapping 1-200 names to questions")
    paths = image_paths or []
    if paths and model.startswith("typesafe/"):
        raise ValueError("Jev accepts text only")
    report: dict[str, object] = {
        "model": model,
        "question_count": len(questions),
        "image_count": len(paths),
        "mode": "live_shadow" if live else "dry_run_no_inference",
        "can_approve_worksheet": False,
    }
    if not live:
        return report
    limits = current_limits()
    if (
        not openrouter.available()
        or limits is None
        or any(value is None for value in (limits.max_usd, limits.max_calls, limits.deadline_s))
        or model not in limits.call_ceilings
    ):
        raise ValueError("Live probe requires a vault key and verified USD/call/deadline limits")
    probabilities = openrouter.decide_yes_no(
        state,
        questions,
        model=model,
        images=[Path(path).read_bytes() for path in paths],
    )
    if probabilities is None:
        raise RuntimeError("Decisions probe failed its typed response contract")
    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "decisions_shadow.json"
    path.write_text(json.dumps({**report, "probabilities": probabilities}, indent=2))
    report["report_path"] = str(path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            probe(
                args.output,
                args.state,
                args.questions,
                args.model,
                image_paths=args.image,
                live=args.live,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
