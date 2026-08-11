#!/usr/bin/env python
"""A/B comparison runner for ScanSci Pi gold tasks.

Runs the same set of gold scenario tasks under two configurations and
reports completion rate, tool-call counts, latency, and evidence recall.

Usage::

    python scripts/compare_runs.py <workspace> [--tasks <path>] [--baseline <config>] [--candidate <config>]

Example::

    python scripts/compare_runs.py F:/AI/scansci-pi \\
        --baseline '{"provider":"openai","model":"gpt-4o"}' \\
        --candidate '{"provider":"openai","model":"deepseek-v4-pro"}'
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any


def load_gold_tasks(tasks_path: Path) -> list[dict[str, Any]]:
    if not tasks_path.is_file():
        # Default: use the bundled gold scenarios
        tasks_path = Path(__file__).resolve().parent.parent / "tests" / "gold_tasks" / "gold_scenarios.jsonl"
    tasks: list[dict[str, Any]] = []
    with tasks_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tasks


def run_gold_task(
    workspace: Path,
    task: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run one gold task and collect metrics. Placeholder for actual Pi invocation."""
    task_id = str(task.get("id", "unknown"))
    prompt = str(task.get("prompt", ""))
    expected_tools = list(task.get("expected_tools", []) or [])

    started = time.monotonic()
    # ── Placeholder ──────────────────────────────────────────
    # In production this would invoke PiAgentClient.stream_chat()
    # with the config's provider/model settings and record the
    # actual tool calls, evidence URIs, and answer text.
    time.sleep(0.1)  # simulate work
    # ──────────────────────────────────────────────────────────
    elapsed_ms = round((time.monotonic() - started) * 1000)

    return {
        "task_id": task_id,
        "type": task.get("type", ""),
        "prompt": prompt[:120],
        "config": {k: v for k, v in config.items() if k in ("provider", "model")},
        "elapsed_ms": elapsed_ms,
        "tool_calls_expected": len(expected_tools),
        "tool_calls_actual": 0,  # placeholder
        "tools_hit": [],  # placeholder
        "evidence_recall": 0.0,  # placeholder
        "completed": True,  # placeholder
        "answer_length": 0,  # placeholder
    }


def compare_runs(
    workspace: Path,
    tasks: list[dict[str, Any]],
    baseline_config: dict[str, Any],
    candidate_config: dict[str, Any],
) -> dict[str, Any]:
    baseline_results: list[dict[str, Any]] = []
    candidate_results: list[dict[str, Any]] = []

    for i, task in enumerate(tasks):
        task_id = str(task.get("id", f"task_{i}"))
        print(f"[{i + 1}/{len(tasks)}] {task_id}: {str(task.get('prompt', ''))[:80]}...")

        b_result = run_gold_task(workspace, task, baseline_config)
        baseline_results.append(b_result)

        c_result = run_gold_task(workspace, task, candidate_config)
        candidate_results.append(c_result)

    # Aggregate metrics
    def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(results)
        completed = sum(1 for r in results if r.get("completed"))
        total_ms = sum(int(r.get("elapsed_ms", 0)) for r in results)
        total_tools = sum(int(r.get("tool_calls_actual", 0)) for r in results)
        avg_recall = sum(float(r.get("evidence_recall", 0)) for r in results) / max(total, 1)
        return {
            "task_count": total,
            "completed": completed,
            "completion_rate": round(completed / max(total, 1), 3),
            "total_elapsed_ms": total_ms,
            "avg_elapsed_ms": round(total_ms / max(total, 1)),
            "total_tool_calls": total_tools,
            "avg_tool_calls": round(total_tools / max(total, 1), 1),
            "avg_evidence_recall": round(avg_recall, 3),
        }

    baseline_agg = aggregate(baseline_results)
    candidate_agg = aggregate(candidate_results)
    comparison: dict[str, Any] = {
        "baseline": baseline_agg,
        "candidate": candidate_agg,
        "delta": {
            "completion_rate": round(candidate_agg["completion_rate"] - baseline_agg["completion_rate"], 3),
            "avg_elapsed_ms": candidate_agg["avg_elapsed_ms"] - baseline_agg["avg_elapsed_ms"],
            "avg_tool_calls": round(candidate_agg["avg_tool_calls"] - baseline_agg["avg_tool_calls"], 1),
            "avg_evidence_recall": round(candidate_agg["avg_evidence_recall"] - baseline_agg["avg_evidence_recall"], 3),
        },
        "per_task": [
            {"task_id": t.get("id"), "type": t.get("type"),
             "baseline_completed": b.get("completed"), "candidate_completed": c.get("completed"),
             "baseline_ms": b.get("elapsed_ms"), "candidate_ms": c.get("elapsed_ms")}
            for t, b, c in zip(tasks, baseline_results, candidate_results)
        ],
    }
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B comparison runner for ScanSci Pi gold tasks")
    parser.add_argument("workspace", type=Path, help="Workspace root directory")
    parser.add_argument("--tasks", type=Path, default=None, help="Path to gold_scenarios.jsonl")
    parser.add_argument("--baseline", type=str, default='{"provider":"openai","model":"gpt-4o"}',
                        help="Baseline config JSON")
    parser.add_argument("--candidate", type=str, default='{"provider":"openai","model":"deepseek-v4-pro"}',
                        help="Candidate config JSON")
    parser.add_argument("--output", type=Path, default=None, help="Save comparison JSON to file")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    tasks = load_gold_tasks(args.tasks or (workspace / "tests" / "gold_tasks" / "gold_scenarios.jsonl"))
    if not tasks:
        print("No gold tasks found.", file=sys.stderr)
        sys.exit(1)

    baseline_config = json.loads(args.baseline)
    candidate_config = json.loads(args.candidate)

    print(f"Running {len(tasks)} gold tasks...")
    print(f"  Baseline:  {baseline_config.get('provider', '?')}/{baseline_config.get('model', '?')}")
    print(f"  Candidate: {candidate_config.get('provider', '?')}/{candidate_config.get('model', '?')}")
    print()

    comparison = compare_runs(workspace, tasks, baseline_config, candidate_config)

    print(f"\n=== A/B Comparison ===")
    print(f"Baseline  completion: {comparison['baseline']['completion_rate']:.1%}  "
          f"avg {comparison['baseline']['avg_elapsed_ms']}ms  "
          f"tool_calls: {comparison['baseline']['avg_tool_calls']}  "
          f"recall: {comparison['baseline']['avg_evidence_recall']:.3f}")
    print(f"Candidate completion: {comparison['candidate']['completion_rate']:.1%}  "
          f"avg {comparison['candidate']['avg_elapsed_ms']}ms  "
          f"tool_calls: {comparison['candidate']['avg_tool_calls']}  "
          f"recall: {comparison['candidate']['avg_evidence_recall']:.3f}")
    delta = comparison["delta"]
    sign = lambda v: f"+{v}" if v > 0 else str(v)
    print(f"Delta: completion {sign(delta['completion_rate']):>6s}  "
          f"latency {sign(delta['avg_elapsed_ms']):>5d}ms  "
          f"tools {sign(delta['avg_tool_calls']):>5s}  "
          f"recall {sign(delta['avg_evidence_recall']):>6s}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved comparison to {args.output}")


if __name__ == "__main__":
    main()
