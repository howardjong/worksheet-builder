"""Run fal.ai worksheet image-model evals.

Usage:
    python eval_fal_image_models.py
    python eval_fal_image_models.py --models gpt-image-2 recraft-v4 qwen-image-2512
"""

from __future__ import annotations

from render.fal_eval import main

if __name__ == "__main__":
    raise SystemExit(main())
