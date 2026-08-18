"""
Collector — step ①: fetch model lists for each enabled platform.

For every enabled platform in platforms.yaml:
  1. Build a GenericPlatformAdapter from its config.
  2. Call adapter.collect_models() (hits the platform's /v1/models endpoint).
  3. Write results/<platform>_models.json  {platform, models, collected_at}.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.generic_adapter import load_adapters


def collect() -> dict[str, list[str]]:
    """
    Run collection across all enabled platforms.

    Returns
    -------
    dict[str, list[str]]
        Mapping from platform name → list of model IDs collected.
    """
    adapters = load_adapters()
    summary: dict[str, list[str]] = {}

    for adapter in adapters:
        models = adapter.collect_models()
        summary[adapter.name] = models

        # Write the per-platform models index
        path = Path("results") / f"{adapter.name}_models.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "platform": adapter.name,
            "models": models,
            "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return summary
