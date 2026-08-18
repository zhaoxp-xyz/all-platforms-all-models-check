"""
main.py — CLI entry point for all-platforms-all-models-check.

Orchestrates the 5-step pipeline:
  ① collect  →  ② test  →  ③ report  →  ④ aggregate  →  ⑤ diff

Usage
-----
  python -m src.main                       # all platforms, all models
  python -m src.main --platform agnes      # single platform
  python -m src.main --platform agnes --model gpt-4  # single platform + model
  python -m src.main --model gpt-4        # cross-platform lookup
  python -m src.main --no-diff            # skip step 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from src.config_loader import load_platforms
from src.generic_adapter import create_adapter, load_adapters
from src.collector import collect
from src.scheduler import Scheduler
from src.reporter import report as report_platform
from src.aggregator import aggregate
from src.diff import diff

log = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="All-platforms-all-models-check — test LLM API endpoints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--platform",
        action="append",
        metavar="X",
        help="Run only platform X (can be specified multiple times)",
    )
    parser.add_argument(
        "--model",
        metavar="Y",
        help="Test only model Y (cross-platform lookup if used alone; "
             "must pair with --platform if used with --platform)",
    )
    parser.add_argument(
        "--no-diff",
        action="store_true",
        help="Skip step 5 (diff vs baseline)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def _resolve_platforms(args: argparse.Namespace) -> list[str] | None:
    """Return list of platform names to run, or None for all."""
    if args.platform:
        return args.platform
    return None


def _run_pipeline(
    platform_names: list[str] | None,
    model_id: str | None,
    skip_diff: bool,
) -> int:
    """
    Execute the 5-step pipeline.

    Returns 0 on success, 1 on error.
    """
    # ------------------------------------------------------------------
    # Build adapter list (filtered by --platform if specified)
    # ------------------------------------------------------------------
    all_adapters = load_adapters()

    if platform_names is not None:
        # Filter to requested platforms
        allowed = set(platform_names)
        adapters = [a for a in all_adapters if a.name in allowed]
        missing = allowed - {a.name for a in adapters}
        if missing:
            print(f"[warn] unknown platform(s): {missing}", file=sys.stderr)
    else:
        adapters = all_adapters

    if not adapters:
        print("[error] no enabled adapters found.", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Step ① — Collect models
    # ------------------------------------------------------------------
    print("=" * 60)
    print("Step ①: Collecting models")
    print("=" * 60)
    collected = Scheduler(adapters).run_collect()

    # ------------------------------------------------------------------
    # Handle --model cross-platform lookup
    # ------------------------------------------------------------------
    if model_id is not None and platform_names is None:
        # Find which platform(s) have this model
        matching = [
            name for name, models in collected.items() if model_id in models
        ]
        if not matching:
            print(
                f"[error] model '{model_id}' not found in any platform.",
                file=sys.stderr,
            )
            return 1
        print(f"[info] model '{model_id}' found in: {matching}")
        # Re-filter adapters to matching platforms
        adapters = [a for a in adapters if a.name in matching]
        # Also update collected to only those platforms
        collected = {k: v for k, v in collected.items() if k in matching}

    # ------------------------------------------------------------------
    # Step ② — Test models (parallel across platforms)
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step ②: Testing models")
    print("=" * 60)
    results = Scheduler(adapters).run_parallel()

    # ------------------------------------------------------------------
    # Step ③ — Generate per-platform reports
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step ③: Generating reports")
    print("=" * 60)
    for ad in adapters:
        try:
            path = report_platform(ad.name)
            print(f"  [{ad.name}] → {path}")
        except FileNotFoundError:
            print(f"  [{ad.name}] no results to report")

    # ------------------------------------------------------------------
    # Step ④ — Aggregate into summary.json
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step ④: Aggregating summary")
    print("=" * 60)
    summary = aggregate()
    print(f"  → results/summary.json  "
          f"({summary['global']['total_models_tested']} models, "
          f"{summary['global']['total_platforms']} platforms)")

    # ------------------------------------------------------------------
    # Step ⑤ — Diff vs baseline
    # ------------------------------------------------------------------
    if not skip_diff:
        print()
        print("=" * 60)
        print("Step ⑤: Diff vs baseline")
        print("=" * 60)
        report = diff()
        if report is None:
            print("  [diff] First run — baseline created.")
        else:
            _print_diff(report)
    else:
        print()
        print("Step ⑤: Skipped (--no-diff)")

    print()
    print("Done.")
    return 0


def _print_diff(report: dict[str, Any]) -> None:
    """Print a human-readable diff report to stdout."""
    global_d = report.get("global", {})
    if not global_d.get("ok_to_fail") and not global_d.get("fail_to_ok"):
        print("  No changes vs baseline.")
        return

    if global_d.get("ok_to_fail"):
        print("  ⚠️  OK→FAIL:")
        for m in global_d["ok_to_fail"]:
            print(f"    - {m}")
    if global_d.get("fail_to_ok"):
        print("  ✅  FAIL→OK:")
        for m in global_d["fail_to_ok"]:
            print(f"    + {m}")
    if global_d.get("new_ok"):
        print("  🆕 New OK:")
        for m in global_d["new_ok"]:
            print(f"    + {m}")
    if global_d.get("new_fail"):
        print("  🆕 New FAIL:")
        for m in global_d["new_fail"]:
            print(f"    - {m}")

    for p in report.get("platforms", []):
        changes = (
            p.get("ok_to_fail") or p.get("fail_to_ok")
            or p.get("new_ok") or p.get("new_fail")
        )
        if not changes:
            continue
        print(f"\n  [{p['platform']}]:")
        for m in p.get("ok_to_fail", []):
            print(f"    ⚠️  {m}  OK→FAIL")
        for m in p.get("fail_to_ok", []):
            print(f"    ✅  {m}  FAIL→OK")
        for m in p.get("new_ok", []):
            print(f"    🆕  {m}")
        for m in p.get("new_fail", []):
            print(f"    ❌  {m}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    platform_names = _resolve_platforms(args)
    return _run_pipeline(
        platform_names=platform_names,
        model_id=args.model,
        skip_diff=args.no_diff,
    )


if __name__ == "__main__":
    sys.exit(main())
