"""
Reporter — step ③: generate a single-platform markdown report
from results/<platform>.json → results/<platform>_report.md.

Public API
----------
def report(platform_name: str) -> str
    Generate and persist the markdown report.
    Returns the absolute path to the generated report file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def report(platform_name: str) -> str:
    """
    Read results/<platform>.json and write results/<platform>_report.md.

    Parameters
    ----------
    platform_name : str
        Platform name (used as file name stem).

    Returns
    -------
    str
        Absolute path to the generated markdown report.
    """
    results_path = Path("results") / f"{platform_name}.json"
    if not results_path.exists():
        raise FileNotFoundError(
            f"Results file not found: {results_path} — run step ② first."
        )

    data = json.loads(results_path.read_text(encoding="utf-8"))
    lines: list[str] = []

    _render_header(lines, data)
    _render_summary(lines, data)
    _render_ok_models(lines, data)
    _render_fail_models(lines, data)
    _render_details(lines, data)

    report_path = Path("results") / f"{platform_name}_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return str(report_path.resolve())


# ------------------------------------------------------------------
# Report sections
# ------------------------------------------------------------------

def _render_header(lines: list[str], data: dict[str, Any]) -> None:
    platform = data.get("platform", "unknown")
    tested_at = data.get("tested_at", "N/A")
    lines.append(f"# Platform Report: {platform}")
    lines.append("")
    lines.append(f"Tested at: {tested_at}")
    lines.append("")


def _render_summary(lines: list[str], data: dict[str, Any]) -> None:
    total = data.get("total", 0)
    ok_count = data.get("ok_count", 0)
    fail_count = data.get("fail_count", 0)
    ok_list: list[str] = data.get("ok", [])
    fail_list: list[str] = data.get("fail", [])

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total tested | {total} |")
    lines.append(f"| ✅ OK | {ok_count} |")
    lines.append(f"| ❌ Fail | {fail_count} |")
    if total > 0:
        rate = ok_count / total * 100
        lines.append(f"| Success rate | {rate:.1f}% |")
    lines.append("")


def _render_ok_models(lines: list[str], data: dict[str, Any]) -> None:
    ok_list: list[str] = data.get("ok", [])
    lines.append("## ✅ OK Models")
    lines.append("")
    if ok_list:
        for model in ok_list:
            lines.append(f"- `{model}`")
    else:
        lines.append("*No models passed.*")
    lines.append("")


def _render_fail_models(lines: list[str], data: dict[str, Any]) -> None:
    fail_list: list[str] = data.get("fail", [])
    lines.append("## ❌ Failed Models")
    lines.append("")
    if fail_list:
        for model in fail_list:
            lines.append(f"- `{model}`")
    else:
        lines.append("*All models passed.*")
    lines.append("")


def _render_details(lines: list[str], data: dict[str, Any]) -> None:
    all_results: list[dict] = data.get("all_results", [])
    if not all_results:
        return

    lines.append("## Detailed Results")
    lines.append("")
    lines.append(
        "| Model | Status | HTTP Code | Protocol | Elapsed (s) | Content |"
    )
    lines.append(
        "|-------|--------|-----------|----------|-------------|---------|"
    )

    for entry in all_results:
        model = entry.get("model", "?")
        status = entry.get("status", "?")
        http_code = entry.get("http_code", 0)
        protocol = entry.get("protocol") or "—"
        elapsed = entry.get("elapsed", 0.0)
        content = entry.get("content")
        content_str = (content[:80] + "…") if content and len(content) > 80 else (content or "—")

        # Escape pipe characters in content
        content_str = content_str.replace("|", "\\|")

        lines.append(
            f"| `{model}` | {status} | {http_code} | {protocol} "
            f"| {elapsed:.3f} | {content_str} |"
        )

    lines.append("")
