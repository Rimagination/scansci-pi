from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .workspace import load_workspace_summary


AGENT_NAME = "scansci-evidence-agent"
AGENT_MODE = "deterministic"
DEFAULT_LIBRARY_DIR = Path("html-papers")


def build_agent_status(
    db_path: str | Path,
    *,
    acceptance_dir: str | Path,
    workspace_path: str | Path = "workspace.sqlite",
    annotation_layers_path: str | Path = "annotation_layers.sqlite",
) -> dict[str, Any]:
    db = Path(db_path)
    acceptance = Path(acceptance_dir)
    workspace = Path(workspace_path)
    annotation_layers = Path(annotation_layers_path)

    evidence_store = _summarize_evidence_store(db)
    acceptance_workbench = _summarize_acceptance_workbench(acceptance)
    workspace_summary = _summarize_workspace(workspace)
    annotation_summary = _summarize_annotation_layers(annotation_layers)
    status = _overall_status(evidence_store, acceptance_workbench)
    next_actions = _build_next_actions(
        status,
        db_path=db,
        acceptance_dir=acceptance,
        evidence_store=evidence_store,
        acceptance_workbench=acceptance_workbench,
    )

    return {
        "agent": AGENT_NAME,
        "mode": AGENT_MODE,
        "status": status,
        "inputs": {
            "db_path": str(db),
            "acceptance_dir": str(acceptance),
            "workspace_path": str(workspace),
            "annotation_layers_path": str(annotation_layers),
        },
        "capabilities": ["status", "next", "plan"],
        "evidence_store": evidence_store,
        "acceptance_workbench": acceptance_workbench,
        "workspace": workspace_summary,
        "annotation_layers": annotation_summary,
        "next_actions": next_actions,
    }


def build_agent_next(
    db_path: str | Path,
    *,
    acceptance_dir: str | Path,
    workspace_path: str | Path = "workspace.sqlite",
    annotation_layers_path: str | Path = "annotation_layers.sqlite",
    limit: int = 5,
) -> dict[str, Any]:
    status = build_agent_status(
        db_path,
        acceptance_dir=acceptance_dir,
        workspace_path=workspace_path,
        annotation_layers_path=annotation_layers_path,
    )
    actions = list(status.get("next_actions", []) or [])[: max(0, int(limit))]
    return {
        "agent": AGENT_NAME,
        "mode": AGENT_MODE,
        "status": status.get("status", ""),
        "actions": actions,
        "status_report": status,
    }


def build_agent_plan(
    db_path: str | Path,
    *,
    acceptance_dir: str | Path,
    workspace_path: str | Path = "workspace.sqlite",
    annotation_layers_path: str | Path = "annotation_layers.sqlite",
    limit: int = 10,
) -> dict[str, Any]:
    status_report = build_agent_status(
        db_path,
        acceptance_dir=acceptance_dir,
        workspace_path=workspace_path,
        annotation_layers_path=annotation_layers_path,
    )
    stages = _build_plan_stages(status_report)
    actions: list[dict[str, Any]] = []
    current_stage = "complete"
    for stage in stages:
        stage_actions = list(stage.get("actions", []) or [])
        if stage_actions and current_stage == "complete":
            current_stage = str(stage.get("id", ""))
        actions.extend(stage_actions)

    return {
        "agent": AGENT_NAME,
        "mode": AGENT_MODE,
        "status": status_report.get("status", ""),
        "current_stage": current_stage,
        "stages": stages,
        "actions": actions[: max(0, int(limit))],
        "status_report": status_report,
    }


def _summarize_evidence_store(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "path": str(db_path),
            "exists": False,
            "status": "missing",
            "documents": 0,
            "spans": 0,
            "missing_anchor_spans": 0,
            "section_kinds": {},
        }

    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            has_documents = _table_exists(connection, "source_documents")
            has_spans = _table_exists(connection, "evidence_spans")
            documents = _count_rows(connection, "source_documents") if has_documents else 0
            spans = _count_rows(connection, "evidence_spans") if has_spans else 0
            missing_anchor_spans = _missing_anchor_count(connection) if has_spans else 0
            section_kinds = _section_kind_counts(connection) if has_spans else {}
    except sqlite3.Error as error:
        return {
            "path": str(db_path),
            "exists": True,
            "status": "unreadable",
            "documents": 0,
            "spans": 0,
            "missing_anchor_spans": 0,
            "section_kinds": {},
            "error": str(error),
        }

    store_status = "ready" if documents > 0 and spans > 0 else "empty"
    if missing_anchor_spans:
        store_status = "needs_anchor_repair"
    return {
        "path": str(db_path),
        "exists": True,
        "status": store_status,
        "documents": documents,
        "spans": spans,
        "missing_anchor_spans": missing_anchor_spans,
        "section_kinds": section_kinds,
    }


def _summarize_acceptance_workbench(acceptance_dir: Path) -> dict[str, Any]:
    manifest_path = acceptance_dir / "acceptance-workbench.manifest.json"
    if not manifest_path.exists():
        return {
            "path": str(acceptance_dir),
            "exists": False,
            "status": "missing",
            "manifest_path": str(manifest_path),
            "validation_passed": False,
            "questions": 0,
            "issue_count": 0,
            "artifacts": {},
            "next_commands": [],
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "path": str(acceptance_dir),
            "exists": True,
            "status": "unreadable",
            "manifest_path": str(manifest_path),
            "validation_passed": False,
            "questions": 0,
            "issue_count": 0,
            "artifacts": {},
            "next_commands": [],
            "error": str(error),
        }

    validation = dict(manifest.get("validation", {}) or {})
    issues = list(validation.get("issues", []) or [])
    artifacts = dict(manifest.get("artifacts", {}) or {})
    return {
        "path": str(acceptance_dir),
        "exists": True,
        "status": str(manifest.get("status", "") or "unknown"),
        "manifest_path": str(manifest_path),
        "validation_passed": bool(validation.get("passed")),
        "questions": int(validation.get("questions") or 0),
        "issue_count": len(issues),
        "artifacts": artifacts,
        "next_commands": [str(command) for command in manifest.get("next_commands", []) or []],
    }


def _summarize_workspace(workspace_path: Path) -> dict[str, Any]:
    try:
        summary = load_workspace_summary(workspace_path)
    except sqlite3.Error as error:
        return {
            "workspace_path": str(workspace_path),
            "exists": workspace_path.exists(),
            "status": "unreadable",
            "error": str(error),
            "counts": {"notebooks": 0, "sources": 0, "notes": 0, "layers": 0},
        }
    summary["exists"] = workspace_path.exists()
    summary["status"] = "ready" if summary.get("exists") else "missing"
    return summary


def _summarize_annotation_layers(annotation_layers_path: Path) -> dict[str, Any]:
    if not annotation_layers_path.exists():
        return {
            "path": str(annotation_layers_path),
            "exists": False,
            "status": "missing",
        }
    try:
        with sqlite3.connect(annotation_layers_path) as connection:
            table_names = _table_names(connection)
    except sqlite3.Error as error:
        return {
            "path": str(annotation_layers_path),
            "exists": True,
            "status": "unreadable",
            "error": str(error),
        }
    return {
        "path": str(annotation_layers_path),
        "exists": True,
        "status": "ready",
        "tables": table_names,
    }


def _overall_status(evidence_store: dict[str, Any], acceptance_workbench: dict[str, Any]) -> str:
    evidence_status = str(evidence_store.get("status", ""))
    acceptance_status = str(acceptance_workbench.get("status", ""))
    if evidence_status == "missing":
        return "missing_evidence_store"
    if evidence_status in {"empty", "unreadable"}:
        return "evidence_store_not_ready"
    if evidence_status == "needs_anchor_repair":
        return "needs_anchor_repair"
    if acceptance_status == "missing":
        return "needs_acceptance_workbench"
    if acceptance_status == "unreadable":
        return "acceptance_workbench_not_ready"
    if not bool(acceptance_workbench.get("validation_passed")) or acceptance_status != "ready_for_benchmark":
        return "needs_human_review"
    return "ready_for_benchmark"


def _build_next_actions(
    status: str,
    *,
    db_path: Path,
    acceptance_dir: Path,
    evidence_store: dict[str, Any],
    acceptance_workbench: dict[str, Any],
) -> list[dict[str, Any]]:
    if status == "missing_evidence_store":
        return [
            _action(
                "build_evidence_store",
                "Build the evidence store from clean HTML.",
                workspace="evidence",
                priority=1,
                reason="The configured evidence SQLite database does not exist.",
                command=(
                    "scansci evidence index "
                    f"--library-dir {_ps_quote(DEFAULT_LIBRARY_DIR)} "
                    f"--db {_ps_quote(db_path)}"
                ),
                argv=["evidence", "index", "--library-dir", str(DEFAULT_LIBRARY_DIR), "--db", str(db_path)],
                paths={"db_path": str(db_path), "library_dir": str(DEFAULT_LIBRARY_DIR)},
            )
        ]

    if status == "evidence_store_not_ready":
        return [
            _action(
                "rebuild_evidence_store",
                "Rebuild the evidence store.",
                workspace="evidence",
                priority=1,
                reason=f"Evidence store status is {evidence_store.get('status')}.",
                command=(
                    "scansci evidence index "
                    f"--library-dir {_ps_quote(DEFAULT_LIBRARY_DIR)} "
                    f"--db {_ps_quote(db_path)}"
                ),
                argv=["evidence", "index", "--library-dir", str(DEFAULT_LIBRARY_DIR), "--db", str(db_path)],
                paths={"db_path": str(db_path), "library_dir": str(DEFAULT_LIBRARY_DIR)},
            )
        ]

    if status == "needs_anchor_repair":
        return [
            _action(
                "repair_evidence_anchors",
                "Run the evidence doctor before benchmarking.",
                workspace="evidence",
                priority=1,
                reason=f"{evidence_store.get('missing_anchor_spans', 0)} evidence spans are missing anchors.",
                command=f"scansci evidence doctor --db {_ps_quote(db_path)}",
                argv=["evidence", "doctor", "--db", str(db_path)],
                paths={"db_path": str(db_path)},
            )
        ]

    if status == "needs_acceptance_workbench":
        return [
            _action(
                "create_acceptance_workbench",
                "Create the local acceptance review workbench.",
                workspace="acceptance",
                priority=1,
                reason="The evidence store is ready, but no acceptance workbench manifest was found.",
                command=(
                    "scansci bench acceptance "
                    f"--db {_ps_quote(db_path)} "
                    f"--output-dir {_ps_quote(acceptance_dir)} "
                    "--questions-per-type 2"
                ),
                argv=[
                    "bench",
                    "acceptance",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(acceptance_dir),
                    "--questions-per-type",
                    "2",
                ],
                paths={"db_path": str(db_path), "acceptance_dir": str(acceptance_dir)},
            )
        ]

    if status == "acceptance_workbench_not_ready":
        return [
            _action(
                "recreate_acceptance_workbench",
                "Recreate the local acceptance review workbench.",
                workspace="acceptance",
                priority=1,
                reason="The acceptance workbench manifest exists but cannot be read.",
                command=(
                    "scansci bench acceptance "
                    f"--db {_ps_quote(db_path)} "
                    f"--output-dir {_ps_quote(acceptance_dir)} "
                    "--questions-per-type 2"
                ),
                argv=[
                    "bench",
                    "acceptance",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(acceptance_dir),
                    "--questions-per-type",
                    "2",
                ],
                paths={"db_path": str(db_path), "acceptance_dir": str(acceptance_dir)},
            )
        ]

    if status == "needs_human_review":
        artifacts = dict(acceptance_workbench.get("artifacts", {}) or {})
        commands = list(acceptance_workbench.get("next_commands", []) or [])
        return [
            _action(
                "review_acceptance_gold",
                "Review and validate the local gold questions.",
                workspace="acceptance",
                priority=1,
                reason="The acceptance workbench is present, but validation has not passed.",
                command=commands[0] if commands else _review_gold_command(acceptance_dir),
                requires_human=True,
                paths={
                    "template_jsonl": str(artifacts.get("template_jsonl", "")),
                    "local_gold_jsonl": str(artifacts.get("local_gold_jsonl", acceptance_dir / "gold_questions.local.jsonl")),
                    "validation_html": str(artifacts.get("validation_html", "")),
                },
            )
        ]

    if status == "ready_for_benchmark":
        commands = list(acceptance_workbench.get("next_commands", []) or [])
        benchmark_command = _first_command_starting_with(commands, "scansci bench run") or _benchmark_command(
            db_path,
            acceptance_dir,
        )
        return [
            _action(
                "run_local_benchmark",
                "Run the local evidence benchmark.",
                workspace="benchmark",
                priority=1,
                reason="Evidence and acceptance validation are ready.",
                command=benchmark_command,
                argv=_benchmark_argv(db_path, acceptance_dir) if not commands else [],
                paths={
                    "db_path": str(db_path),
                    "gold_jsonl": str(acceptance_dir / "gold_questions.local.jsonl"),
                },
            )
        ]

    return []


def _build_plan_stages(status_report: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(status_report.get("status", ""))
    inputs = dict(status_report.get("inputs", {}) or {})
    db_path = Path(str(inputs.get("db_path", "html-papers/evidence.sqlite")))
    acceptance_dir = Path(str(inputs.get("acceptance_dir", "bench/local-acceptance-workbench")))
    evidence_store = dict(status_report.get("evidence_store", {}) or {})
    acceptance_workbench = dict(status_report.get("acceptance_workbench", {}) or {})
    next_actions = list(status_report.get("next_actions", []) or [])

    evidence_actions = next_actions if status in {
        "missing_evidence_store",
        "evidence_store_not_ready",
        "needs_anchor_repair",
    } else []
    evidence_stage = _stage(
        "evidence_store",
        "Evidence store",
        "needs_action" if evidence_actions else "ready",
        reason=_evidence_stage_reason(evidence_store),
        actions=evidence_actions,
        summary={
            "status": str(evidence_store.get("status", "")),
            "documents": int(evidence_store.get("documents") or 0),
            "spans": int(evidence_store.get("spans") or 0),
            "missing_anchor_spans": int(evidence_store.get("missing_anchor_spans") or 0),
        },
    )

    if evidence_actions:
        acceptance_stage = _stage(
            "acceptance_workbench",
            "Acceptance workbench",
            "blocked",
            reason="The evidence store must be ready before local gold review can start.",
            actions=[],
            summary={"status": str(acceptance_workbench.get("status", ""))},
        )
        benchmark_stage = _blocked_benchmark_stage()
        return [evidence_stage, acceptance_stage, benchmark_stage]

    if status in {"needs_acceptance_workbench", "acceptance_workbench_not_ready"}:
        acceptance_actions = next_actions
        acceptance_state = "needs_action"
    elif status == "needs_human_review":
        acceptance_actions = _acceptance_review_actions(db_path, acceptance_dir, acceptance_workbench)
        acceptance_state = "needs_human_review"
    else:
        acceptance_actions = []
        acceptance_state = "ready"

    acceptance_stage = _stage(
        "acceptance_workbench",
        "Acceptance workbench",
        acceptance_state,
        reason=_acceptance_stage_reason(status, acceptance_workbench),
        actions=acceptance_actions,
        summary={
            "status": str(acceptance_workbench.get("status", "")),
            "validation_passed": bool(acceptance_workbench.get("validation_passed")),
            "questions": int(acceptance_workbench.get("questions") or 0),
            "issue_count": int(acceptance_workbench.get("issue_count") or 0),
        },
    )

    if acceptance_actions:
        benchmark_stage = _blocked_benchmark_stage()
    else:
        benchmark_stage = _stage(
            "benchmark",
            "Local benchmark",
            "ready_to_run" if status == "ready_for_benchmark" else "blocked",
            reason=(
                "Evidence and acceptance validation are ready."
                if status == "ready_for_benchmark"
                else "Acceptance validation must pass before benchmark execution."
            ),
            actions=next_actions if status == "ready_for_benchmark" else [],
            summary={"target": "local_gold_evidence_answer"},
        )
    return [evidence_stage, acceptance_stage, benchmark_stage]


def _acceptance_review_actions(
    db_path: Path,
    acceptance_dir: Path,
    acceptance_workbench: dict[str, Any],
) -> list[dict[str, Any]]:
    artifacts = dict(acceptance_workbench.get("artifacts", {}) or {})
    commands = [str(command) for command in acceptance_workbench.get("next_commands", []) or []]
    review_command = commands[0] if commands else _review_gold_command(acceptance_dir)
    validate_command = _first_command_starting_with(commands, "scansci bench validate") or _validate_gold_command(
        db_path,
        acceptance_dir,
    )
    return [
        _action(
            "review_acceptance_gold",
            "Review the local gold question file.",
            workspace="acceptance",
            priority=1,
            reason="The generated local gold rows still require human review.",
            command=review_command,
            requires_human=True,
            paths={
                "template_jsonl": str(artifacts.get("template_jsonl", "")),
                "local_gold_jsonl": str(artifacts.get("local_gold_jsonl", acceptance_dir / "gold_questions.local.jsonl")),
            },
        ),
        _action(
            "validate_local_gold",
            "Validate the reviewed local gold questions.",
            workspace="acceptance",
            priority=2,
            reason="The reviewed local gold file must pass schema and evidence-id validation before benchmarking.",
            command=validate_command,
            argv=_validate_gold_argv(db_path, acceptance_dir) if not _first_command_starting_with(commands, "scansci bench validate") else [],
            paths={
                "db_path": str(db_path),
                "local_gold_jsonl": str(artifacts.get("local_gold_jsonl", acceptance_dir / "gold_questions.local.jsonl")),
                "validation_html": str(artifacts.get("validation_html", acceptance_dir / "gold-validation.local.html")),
            },
        ),
    ]


def _stage(
    stage_id: str,
    title: str,
    state: str,
    *,
    reason: str,
    actions: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "title": title,
        "state": state,
        "reason": reason,
        "actions": actions,
        "summary": summary,
    }


def _blocked_benchmark_stage() -> dict[str, Any]:
    return _stage(
        "benchmark",
        "Local benchmark",
        "blocked",
        reason="Evidence store and acceptance validation must be ready before benchmark execution.",
        actions=[],
        summary={"target": "local_gold_evidence_answer"},
    )


def _evidence_stage_reason(evidence_store: dict[str, Any]) -> str:
    status = str(evidence_store.get("status", ""))
    if status == "ready":
        return "The evidence store has documents and spans."
    if status == "needs_anchor_repair":
        return "Some evidence spans are missing source anchors."
    if status == "missing":
        return "The evidence store has not been built yet."
    return f"Evidence store status is {status or 'unknown'}."


def _acceptance_stage_reason(status: str, acceptance_workbench: dict[str, Any]) -> str:
    if status == "needs_acceptance_workbench":
        return "No local acceptance workbench manifest was found."
    if status == "acceptance_workbench_not_ready":
        return "The local acceptance workbench manifest could not be read."
    if status == "needs_human_review":
        return "Local gold questions still need human review and validation."
    if str(acceptance_workbench.get("status", "")) == "ready_for_benchmark":
        return "Local gold validation has passed."
    return "Acceptance workbench is waiting for evidence readiness."


def _action(
    action_id: str,
    title: str,
    *,
    workspace: str,
    priority: int,
    reason: str,
    command: str,
    paths: dict[str, str],
    argv: list[str] | None = None,
    requires_human: bool = False,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "title": title,
        "workspace": workspace,
        "priority": priority,
        "reason": reason,
        "command": command,
        "paths": paths,
        "argv": list(argv or []),
        "requires_human": bool(requires_human),
    }


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type in ('table', 'view') and name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type in ('table', 'view') order by name"
        ).fetchall()
    ]


def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
    return int(connection.execute(f"select count(*) from {table_name}").fetchone()[0])


def _missing_anchor_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        select count(*)
        from evidence_spans
        where coalesce(html_path, '') = '' or coalesce(html_anchor, '') = ''
        """
    ).fetchone()
    return int(row[0])


def _section_kind_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        select coalesce(nullif(section_kind, ''), 'unknown') as section_kind, count(*) as span_count
        from evidence_spans
        group by coalesce(nullif(section_kind, ''), 'unknown')
        order by span_count desc, section_kind
        """
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _review_gold_command(acceptance_dir: Path) -> str:
    template = acceptance_dir / "gold_questions.template.jsonl"
    reviewed = acceptance_dir / "gold_questions.local.jsonl"
    return f"Copy-Item -LiteralPath {_ps_quote(template)} -Destination {_ps_quote(reviewed)}"


def _validate_gold_command(db_path: Path, acceptance_dir: Path) -> str:
    return " ".join(
        [
            "scansci bench validate",
            "--gold",
            _ps_quote(acceptance_dir / "gold_questions.local.jsonl"),
            "--db",
            _ps_quote(db_path),
            "--html-output",
            _ps_quote(acceptance_dir / "gold-validation.local.html"),
        ]
    )


def _validate_gold_argv(db_path: Path, acceptance_dir: Path) -> list[str]:
    return [
        "bench",
        "validate",
        "--gold",
        str(acceptance_dir / "gold_questions.local.jsonl"),
        "--db",
        str(db_path),
        "--html-output",
        str(acceptance_dir / "gold-validation.local.html"),
    ]


def _benchmark_command(db_path: Path, acceptance_dir: Path) -> str:
    return " ".join(
        [
            "scansci bench run",
            "--db",
            _ps_quote(db_path),
            "--gold",
            _ps_quote(acceptance_dir / "gold_questions.local.jsonl"),
            "--details-output",
            _ps_quote(acceptance_dir / "local-benchmark-details.json"),
            "--details-html-output",
            _ps_quote(acceptance_dir / "local-benchmark-details.html"),
        ]
    )


def _benchmark_argv(db_path: Path, acceptance_dir: Path) -> list[str]:
    return [
        "bench",
        "run",
        "--db",
        str(db_path),
        "--gold",
        str(acceptance_dir / "gold_questions.local.jsonl"),
        "--details-output",
        str(acceptance_dir / "local-benchmark-details.json"),
        "--details-html-output",
        str(acceptance_dir / "local-benchmark-details.html"),
    ]


def _first_command_starting_with(commands: list[str], prefix: str) -> str:
    for command in commands:
        if command.strip().startswith(prefix):
            return command
    return ""


def _ps_quote(value: str | Path) -> str:
    text = str(value)
    return '"' + text.replace('"', '`"') + '"'
