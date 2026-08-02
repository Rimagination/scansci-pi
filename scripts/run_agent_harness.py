"""Validate or grade ScanSci's durable scientific-agent acceptance harness.

This runner deliberately consumes recorded durable runs.  It does not invoke a
provider, search the internet, or mutate a workspace, so it can run in a
release gate and gives the same answer locally and in CI.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from scansci_html.agent_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    grade_harness_records,
    load_harness_cases,
    summarize_harness_results,
)


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    if path.suffix.casefold() == ".jsonl":
        return [dict(json.loads(line)) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("runs", payload.get("records"))
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
        return [
            {"case_id": str(case_id), "run": run}
            for case_id, run in payload.items()
            if isinstance(run, dict)
        ]
    raise ValueError("Harness records must be JSON, JSONL, or a JSON object keyed by case id")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _markdown(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# ScanSci Agent Harness",
        "",
        f"- Passed: {summary['passed']} / {summary['total']} ({summary['pass_rate']:.0%})",
        f"- Failed: {summary['failed']}",
        "",
        "| Case | Category | Result |",
        "| --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.get('case_id', '')} | {result.get('category', '')} | "
            f"{'PASS' if result.get('passed') else 'FAIL'} |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or grade ScanSci agent harness records.")
    parser.add_argument("--cases", default="bench/agent_harness_tasks.json")
    parser.add_argument("--records", default="", help="Recorded durable runs as JSON or JSONL.")
    parser.add_argument("--output", default="", help="Write the machine-readable report here.")
    parser.add_argument("--markdown-output", default="", help="Optional human-readable report path.")
    parser.add_argument("--validate-only", action="store_true", help="Validate the declarative cases without grading runs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = load_harness_cases(args.cases)
        if args.validate_only:
            report = {
                "schema_version": BENCHMARK_SCHEMA_VERSION,
                "mode": "validate_only",
                "case_count": len(cases),
                "case_ids": [str(case["id"]) for case in cases],
                "passed": True,
            }
            if args.output:
                _write_json(Path(args.output), report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if not args.records:
            raise ValueError("--records is required unless --validate-only is used")
        results = grade_harness_records(cases, _load_records(Path(args.records)))
        summary = summarize_harness_results(results)
        report = {"schema_version": BENCHMARK_SCHEMA_VERSION, "mode": "grade", "summary": summary, "results": results}
        if args.output:
            _write_json(Path(args.output), report)
        if args.markdown_output:
            markdown_path = Path(args.markdown_output)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(_markdown(summary, results), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["failed"] == 0 else 1
    except Exception as error:  # noqa: BLE001 - CLI boundary
        print(f"[failed] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
