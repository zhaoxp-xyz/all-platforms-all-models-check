"""
Tester — step ②: test each model on every enabled platform.

For every enabled platform:
  1. Load its model list from results/<platform>_models.json  (collected in step ①).
  2. For each model, call adapter.test_model(model_id) (per-model protocol fallback
     is handled inside AbstractBaseAdapter.test_model).
  3. Accumulate results and persist to results/<platform>.json
     {all_results, ok, fail}.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.config_loader import load_platforms
from src.generic_adapter import create_adapter


def _test_one(adapter_name: str, model_id: str, adapter) -> dict:
    """Run test_model for a single model and return the result dict."""
    return adapter.test_model(model_id)


def test(
    platform_name: str | None = None,
    model_id: str | None = None,
) -> None:
    """
    Test models for enabled platforms.

    Parameters
    ----------
    platform_name : str | None
        If given, test only this platform.
    model_id : str | None
        If given together with platform_name, test only this single model.
    """
    platforms = load_platforms()

    for cfg in platforms:
        name = cfg["name"]

        # Filter by --platform if specified
        if platform_name is not None and name != platform_name:
            continue

        adapter = create_adapter(cfg)
        models_path = Path("results") / f"{name}_models.json"

        # Load collected models; empty list means collect step was skipped
        if models_path.exists():
            try:
                models_data = json.loads(
                    models_path.read_text(encoding="utf-8")
                )
                models = models_data.get("models", [])
            except (json.JSONDecodeError, OSError):
                models = []
        else:
            models = []

        # Filter by --model if specified
        if model_id is not None:
            models = [m for m in models if m == model_id]

        if not models:
            print(f"[{name}] no models to test (skip)")
            continue

        print(f"[{name}] testing {len(models)} model(s)")

        all_results: list[dict] = []
        ok_list: list[str] = []
        fail_list: list[str] = []

        # Run tests concurrently within this platform
        with ThreadPoolExecutor(max_workers=adapter.concurrency) as pool:
            futures = {
                pool.submit(_test_one, name, mid, adapter): mid
                for mid in models
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    model_id_cur = futures[future]
                    result = {
                        "model": model_id_cur,
                        "status": "fail",
                        "http_code": 0,
                        "response": None,
                        "elapsed": 0.0,
                        "protocol": None,
                        "content": None,
                        "error": {"code": "exception", "message": str(exc)},
                    }
                all_results.append(result)
                if result["status"] == "ok":
                    ok_list.append(result["model"])
                else:
                    fail_list.append(result["model"])

        # Persist per-platform results
        results_path = Path("results") / f"{name}.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "platform": name,
            "tested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "all_results": all_results,
            "ok": ok_list,
            "fail": fail_list,
            "total": len(all_results),
            "ok_count": len(ok_list),
            "fail_count": len(fail_list),
        }
        results_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(
            f"[{name}] done: {len(ok_list)}/{len(all_results)} ok, "
            f"{len(fail_list)} fail"
        )
