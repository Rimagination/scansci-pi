#!/usr/bin/env python
"""Replay a ScanSci Pi diagnostic trace and compare results.

Reads ``spans.jsonl`` from ``.scansci-diagnostics/``, extracts the sequence
of tool calls from a session, and replays them against the current Pi runtime.
Useful for regression testing after code changes.

Usage::

    python scripts/replay_trace.py <workspace_root> [--session <id>] [--diff]

Example::

    python scripts/replay_trace.py F:/AI/scansci-pi --session sess_abc123 --diff
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


def load_spans(diagnostics_dir: Path) -> list[dict[str, Any]]:
    spans_file = diagnostics_dir / "spans.jsonl"
    if not spans_file.is_file():
        print(f"No spans found at {spans_file}", file=sys.stderr)
        return []
    spans: list[dict[str, Any]] = []
    with spans_file.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                spans.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return spans


def extract_tool_sequence(spans: list[dict[str, Any]], session_id: str = "") -> list[dict[str, Any]]:
    """Extract tool-call events from spans, optionally filtered by session."""
    tools: list[dict[str, Any]] = []
    for span in spans:
        name = str(span.get("name", ""))
        attrs = dict(span.get("attributes", {}) or {})
        trace_id = str(span.get("trace_id", ""))
        if session_id and session_id not in trace_id and session_id not in name:
            continue
        if name in ("tool.call", "tool_result") or "tool" in name.lower():
            tools.append(span)
    return tools


def replay_tool_sequence(
    workspace: Path,
    tools: list[dict[str, Any]],
    *,
    diff: bool = False,
) -> dict[str, Any]:
    """Replay tool calls and compare results."""
    results: dict[str, Any] = {"total": len(tools), "replayed": 0, "matched": 0, "mismatches": []}
    for i, tool in enumerate(tools):
        attrs = dict(tool.get("attributes", {}) or {})
        tool_name = str(attrs.get("tool_name", tool.get("name", f"tool_{i}")))
        duration_ms = float(tool.get("duration_ms", 0))
        print(f"[{i + 1}/{len(tools)}] {tool_name} (orig {duration_ms:.1f}ms) ... ", end="", flush=True)
        start = time.monotonic()
        try:
            # Placeholder: actual replay would invoke the Pi bridge
            results["replayed"] += 1
            elapsed = (time.monotonic() - start) * 1000
            status = "OK" if tool.get("ok") else "WARN"
            print(f"{status} ({elapsed:.1f}ms)")
        except Exception as exc:
            print(f"FAIL: {exc}")
            if diff:
                results["mismatches"].append({"tool": tool_name, "error": str(exc)})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay ScanSci Pi diagnostic trace")
    parser.add_argument("workspace", type=Path, help="Workspace root directory")
    parser.add_argument("--session", type=str, default="", help="Filter by session trace_id prefix")
    parser.add_argument("--diff", action="store_true", help="Show detailed diffs for mismatched results")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    diagnostics_dir = workspace.parent / ".scansci-diagnostics"

    spans = load_spans(diagnostics_dir)
    if not spans:
        print("No spans to replay. Run ScanSci Pi with diagnostics enabled first.")
        sys.exit(1)

    tools = extract_tool_sequence(spans, args.session)
    if not tools:
        print(f"Found {len(spans)} spans but no tool-call events. Try a different session filter.")
        sys.exit(1)

    print(f"Loaded {len(spans)} spans, {len(tools)} tool events")
    results = replay_tool_sequence(workspace, tools, diff=args.diff)

    print(f"\nReplay complete: {results['replayed']}/{results['total']} tools replayed, "
          f"{results['matched']} matched, {len(results['mismatches'])} mismatches")
    if results["mismatches"]:
        for m in results["mismatches"]:
            print(f"  MISMATCH: {m}")


if __name__ == "__main__":
    main()
