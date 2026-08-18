"""
Scheduler — step ①+② orchestrator: thread pool runs multiple platforms
concurrently, each platform adapter tests models at its own concurrency.

One platform crash does not affect others.

Public API
----------
class Scheduler
    __init__(adapters: list[AbstractBaseAdapter])
    run_parallel() -> dict[str, list[dict]]   # platform → list of result dicts
    run_collect() -> dict[str, list[str]]     # platform → list of model IDs
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.base_adapter import AbstractBaseAdapter

log = logging.getLogger(__name__)


class Scheduler:
    """
    Run multiple platform adapters in parallel via a thread pool.

    Each adapter runs its own inner ThreadPoolExecutor (at adapter.concurrency)
    for per-model testing, so outer and inner parallelism are independent.
    A crash in one platform is caught and recorded — other platforms keep running.
    """

    def __init__(self, adapters: list[AbstractBaseAdapter]) -> None:
        self.adapters = adapters

    # ------------------------------------------------------------------
    # Step ① — collect models for all platforms in parallel
    # ------------------------------------------------------------------

    def run_collect(self) -> dict[str, list[str]]:
        """
        Collect models from every enabled platform concurrently.

        Returns
        -------
        dict[str, list[str]]
            Mapping platform name → list of collected model IDs.
        """
        results: dict[str, list[str]] = {}
        n = len(self.adapters)
        if n == 0:
            return results

        def _collect_one(adapter: AbstractBaseAdapter) -> tuple[str, list[str]]:
            t0 = time.monotonic()
            try:
                models = adapter.collect_models()
                elapsed = time.monotonic() - t0
                log.info(
                    "[%s] collected %d models in %.2fs",
                    adapter.name, len(models), elapsed,
                )
                return adapter.name, models
            except Exception as exc:
                elapsed = time.monotonic() - t0
                log.error(
                    "[%s] collection failed after %.2fs: %s",
                    adapter.name, elapsed, exc,
                )
                return adapter.name, []

        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="collect") as pool:
            futures = {pool.submit(_collect_one, ad): ad.name for ad in self.adapters}
            for future in as_completed(futures):
                name, models = future.result()
                results[name] = models

        return results

    # ------------------------------------------------------------------
    # Step ② — test models for all platforms in parallel
    # ------------------------------------------------------------------

    def run_parallel(self) -> dict[str, list[dict]]:
        """
        Test every platform's models concurrently (outer pool = platforms,
        inner pool = per-model workers at adapter.concurrency).

        One platform crash is isolated — other platforms continue running.

        Returns
        -------
        dict[str, list[dict]]
            Mapping platform name → list of per-model result dicts.
        """
        results: dict[str, list[dict]] = {}
        n = len(self.adapters)
        if n == 0:
            return results

        def _run_platform(adapter: AbstractBaseAdapter) -> tuple[str, list[dict]]:
            """Run collect + test for a single platform, isolated from others."""
            platform_name = adapter.name
            try:
                # Load collected models
                models_path = Path("results") / f"{platform_name}_models.json"
                if models_path.exists():
                    try:
                        import json
                        models_data = json.loads(
                            models_path.read_text(encoding="utf-8")
                        )
                        models = models_data.get("models", [])
                    except (json.JSONDecodeError, OSError):
                        models = []
                else:
                    models = []

                if not models:
                    log.warning("[%s] no models to test", platform_name)
                    return platform_name, []

                log.info(
                    "[%s] testing %d model(s) with concurrency=%d",
                    platform_name, len(models), adapter.concurrency,
                )

                all_results: list[dict] = []
                ok_list: list[str] = []
                fail_list: list[str] = []

                def _test_one(model_id: str) -> dict:
                    return adapter.test_model(model_id)

                with ThreadPoolExecutor(
                    max_workers=adapter.concurrency,
                    thread_name_prefix=f"test_{platform_name}",
                ) as inner_pool:
                    futures = {
                        inner_pool.submit(_test_one, mid): mid for mid in models
                    }
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                        except Exception as exc:
                            cur_model = futures[future]
                            result = {
                                "model": cur_model,
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
                results_path = Path("results") / f"{platform_name}.json"
                results_path.parent.mkdir(parents=True, exist_ok=True)
                import json
                payload: dict[str, Any] = {
                    "platform": platform_name,
                    "tested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "all_results": all_results,
                    "ok": ok_list,
                    "fail": fail_list,
                    "total": len(all_results),
                    "ok_count": len(ok_list),
                    "fail_count": len(fail_list),
                }
                results_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                log.info(
                    "[%s] done: %d/%d ok, %d fail",
                    platform_name, len(ok_list), len(all_results), len(fail_list),
                )
                return platform_name, all_results

            except Exception as exc:
                log.error(
                    "[%s] FATAL: platform test crashed — other platforms unaffected: %s",
                    platform_name, exc,
                )
                # Return empty so the outer pool continues for other platforms
                return platform_name, []

        with ThreadPoolExecutor(
            max_workers=n, thread_name_prefix="platform"
        ) as pool:
            futures = {pool.submit(_run_platform, ad): ad.name for ad in self.adapters}
            for future in as_completed(futures):
                name, results_list = future.result()
                results[name] = results_list

        return results
