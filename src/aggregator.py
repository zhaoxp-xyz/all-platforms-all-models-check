"""
Aggregator — step ④: build a full-platform summary → results/summary.json.

Reads every results/<platform>.json and produces a single summary JSON
containing per-platform stats and a global overview.

Public API
----------
def aggregate() -> dict
    Build and persist the summary. Returns the summary dict.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def aggregate() -> dict[str, Any]:
    """
    Aggregate all per-platform result files into results/summary.json.

    Returns
    -------
    dict
        The summary dict (also written to results/summary.json).
    """
    results_dir = Path("results")
    platform_files = sorted(results_dir.glob("*.json"))

    # Exclude known non-platform files
    exclude_stems = {"summary", "baseline"}
    platform_files = [
        f for f in platform_files
        if f.stem not in exclude_stems and not f.stem.endswith("_models")
        and not f.stem.endswith("_report")
    ]

    platforms: list[dict[str, Any]] = []
    global_ok: list[str] = []
    global_fail: list[str] = []

    for fpath in platform_files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        platform_name = data.get("platform", fpath.stem)
        ok_list: list[str] = data.get("ok", [])
        fail_list: list[str] = data.get("fail", [])
        total = data.get("total", len(ok_list) + len(fail_list))

        entry: dict[str, Any] = {
            "platform": platform_name,
            "total": total,
            "ok_count": len(ok_list),
            "fail_count": len(fail_list),
            "ok_models": ok_list,
            "fail_models": fail_list,
        }
        if total > 0:
            entry["success_rate"] = round(len(ok_list) / total * 100, 1)
        else:
            entry["success_rate"] = 0.0

        platforms.append(entry)
        global_ok.extend(ok_list)
        global_fail.extend(fail_list)

    global_total = len(global_ok) + len(global_fail)
    summary: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platforms": platforms,
        "global": {
            "total_platforms": len(platforms),
            "total_models_tested": global_total,
            "total_ok": len(global_ok),
            "total_fail": len(global_fail),
            "success_rate": round(len(global_ok) / global_total * 100, 1) if global_total else 0.0,
        },
    }

    summary_path = results_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
