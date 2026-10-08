"""Freeze photo transcription for human review before paid planning or artwork."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import traced_pipeline
from capture.preprocess import preprocess_page
from skill.extractor import extract_skill


@traced_pipeline
def intake(artifacts_dir: str, input_path: str, *, live: bool = False) -> dict[str, object]:
    photo = Path(input_path)
    if not photo.is_file():
        raise ValueError("Phone photo does not exist")
    report: dict[str, object] = {
        "mode": "live_extraction_only" if live else "dry_run_no_inference",
        "original_photo_sha256": hashlib.sha256(photo.read_bytes()).hexdigest(),
        "plans_or_renders": False,
        "human_source_review_required": True,
    }
    if not live:
        return report
    limits = current_limits()
    models = openrouter.stage_models("extraction", role="vision")
    if (
        not openrouter.available()
        or not os.environ.get("WORKSHEET_EXTRACTION_CACHE")
        or (
            limits is None
            or any(
                value is None
                for value in (
                    limits.max_usd,
                    limits.max_calls,
                    limits.deadline_s,
                )
            )
            or not models
            or any(model not in limits.call_ceilings for model in models)
        )
    ):
        raise ValueError(
            "Live intake requires a vault key, private extraction cache and verified run limits"
        )
    from transform import _source_model_with_cache

    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    preprocessed = directory / "preprocessed.png"
    preprocess_page(str(photo), str(preprocessed))
    image_hash = hashlib.sha256(preprocessed.read_bytes()).hexdigest()
    source = _source_model_with_cache(str(photo), str(preprocessed), image_hash)
    skill = extract_skill(source)
    (directory / "source_model.json").write_text(source.model_dump_json(indent=2))
    (directory / "skill_model.json").write_text(skill.model_dump_json(indent=2))
    report.update(
        low_confidence_flags=source.low_confidence_flags,
        specific_skill=skill.specific_skill,
        region_count=len(source.regions),
    )
    (directory / "intake_summary.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(json.dumps(intake(args.output, args.input, live=args.live), indent=2))


if __name__ == "__main__":
    main()
