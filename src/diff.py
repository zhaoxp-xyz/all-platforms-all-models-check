"""
Diff — step ⑤: compare current results against results/baseline.json.

First run (no baseline exists) → creates results/baseline.json from
current results, reports nothing to diff.

Subsequent runs → reports deltas (new ok/fail, ok→fail, fail→ok).

Public API
----------
def diff() -> dict | None
    Run diff against baseline.
    Returns a diff report dict, or None if this is the first run
    (baseline was just created).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def diff() -> dict[str, Any] | None:
    """
    Compare current per-platform results against results/baseline.json.

    Returns
    -------
    dict | None
        Diff report with deltas, or None if baseline did not exist
        (first run — baseline was created from current data).
    """
    results_dir = Path("results")
    baseline_path = results_dir / "baseline.json"

    # Load current summary (or build from platform files)
    summary_path = results_dir / "summary.json"
    if summary_path.exists():
        current = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        current = _build_summary_from_platforms(results_dir)

    if not baseline_path.exists():
        # First run: create baseline from current results
        baseline_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("[diff] No baseline found — created results/baseline.json from current results.")
        return None

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    report: dict[str, Any] = {
        "generated_at": current.get("generated_at", ""),
        "baseline_generated_at": baseline.get("generated_at", ""),
        "platforms": [],
        "global": {},
    }

    # Build lookup maps
    current_by_platform: dict[str, dict] = {
        p["platform"]: p for p in current.get("platforms", [])
    }
    baseline_by_platform: dict[str, dict] = {
        p["platform"]: p for p in baseline.get("platforms", [])
    }

    all_platform_names = set(current_by_platform) | set(baseline_by_platform)

    for pname in sorted(all_platform_names):
        cur = current_by_platform.get(pname, {})
        bas = baseline_by_platform.get(pname, {})

        cur_ok = set(cur.get("ok_models", []))
        cur_fail = set(cur.get("fail_models", []))
        bas_ok = set(bas.get("ok_models", []))
        bas_fail = set(bas.get("fail_models", []))

        new_ok = sorted(cur_ok - bas_ok - bas_fail)          # was not tested before, now ok
        new_fail = sorted(cur_fail - bas_fail - bas_ok)      # was not tested before, now fail
        ok_to_fail = sorted(cur_ok & bas_fail)               # was ok, now fail
        fail_to_ok = sorted(cur_fail & bas_ok)               # was fail, now ok
        still_ok = sorted(cur_ok & bas_ok)
        still_fail = sorted(cur_fail & bas_fail)

        platform_diff: dict[str, Any] = {
            "platform": pname,
            "new_ok": new_ok,
            "new_fail": new_fail,
            "ok_to_fail": ok_to_fail,
            "fail_to_ok": fail_to_ok,
            "still_ok": still_ok,
            "still_fail": still_fail,
        }
        report["platforms"].append(platform_diff)

    # Global deltas
    all_cur_ok: set[str] = set()
    all_cur_fail: set[str] = set()
    all_bas_ok: set[str] = set()
    all_bas_fail: set[str] = set()
    for p in current.get("platforms", []):
        all_cur_ok |= set(p.get("ok_models", []))
        all_cur_fail |= set(p.get("fail_models", []))
    for p in baseline.get("platforms", []):
        all_bas_ok |= set(p.get("ok_models", []))
        all_bas_fail |= set(p.get("fail_models", []))

    report["global"] = {
        "new_ok": sorted(all_cur_ok - all_bas_ok - all_bas_fail),
        "new_fail": sorted(all_cur_fail - all_bas_fail - all_bas_ok),
        "ok_to_fail": sorted(all_cur_ok & all_bas_fail),
        "fail_to_ok": sorted(all_cur_fail & all_bas_ok),
    }

    # Write updated baseline
    baseline_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return report


def _build_summary_from_platforms(results_dir: Path) -> dict[str, Any]:
    """Fallback: build a summary dict when summary.json is missing."""
    import time
    platform_files = sorted(
        f for f in results_dir.glob("*.json")
        if f.stem not in {"summary", "baseline"}
        and not f.stem.endswith("_models")
        and not f.stem.endswith("_report")
    )
    platforms = []
    for fpath in platform_files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        platforms.append({
            "platform": data.get("platform", fpath.stem),
            "total": data.get("total", 0),
            "ok_count": data.get("ok_count", 0),
            "fail_count": data.get("fail_count", 0),
            "ok_models": data.get("ok", []),
            "fail_models": data.get("fail", []),
        })
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platforms": platforms,
    }
