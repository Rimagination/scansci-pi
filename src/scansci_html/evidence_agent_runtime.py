from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib import request
from urllib.error import URLError

from .evidence_agent import AGENT_MODE, AGENT_NAME, build_agent_plan


ModelDecider = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class LocalModelConfig:
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    timeout_seconds: float = 30.0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)


def run_evidence_agent(
    db_path: str | Path,
    *,
    acceptance_dir: str | Path,
    workspace_path: str | Path = "workspace.sqlite",
    annotation_layers_path: str | Path = "annotation_layers.sqlite",
    dry_run: bool = True,
    max_steps: int = 3,
    run_output: str | Path | None = None,
    model_config: LocalModelConfig | None = None,
    model_decider: ModelDecider | None = None,
    control_plane: str = "codex",
    supervisor_note: str = "",
    autonomy_level: str = "",
) -> dict[str, Any]:
    decider = model_decider
    if decider is None and model_config is not None and model_config.enabled:
        decider = OpenAICompatibleActionDecider(model_config)
    normalized_control_plane = _normalize_control_plane(control_plane)
    normalized_autonomy = _autonomy_summary(
        autonomy_level=autonomy_level,
        dry_run=bool(dry_run),
    )
    worker_model = _worker_model_summary(model_config)

    manifest: dict[str, Any] = {
        "agent": AGENT_NAME,
        "mode": AGENT_MODE,
        "status": "running",
        "dry_run": bool(dry_run),
        "control_plane": {
            "type": normalized_control_plane,
            "role": "supervisor",
            "supervisor_note": str(supervisor_note or ""),
        },
        "autonomy": normalized_autonomy,
        "worker_model": worker_model,
        "started_at": _utc_now(),
        "finished_at": "",
        "max_steps": max(0, int(max_steps)),
        "steps": [],
        "events": [],
        "inputs": {
            "db_path": str(Path(db_path)),
            "acceptance_dir": str(Path(acceptance_dir)),
            "workspace_path": str(Path(workspace_path)),
            "annotation_layers_path": str(Path(annotation_layers_path)),
        },
        "model": _model_summary(model_config),
    }

    for step_index in range(max(0, int(max_steps))):
        plan = build_agent_plan(
            db_path,
            acceptance_dir=acceptance_dir,
            workspace_path=workspace_path,
            annotation_layers_path=annotation_layers_path,
        )
        actions = list(plan.get("actions", []) or [])
        _append_event(
            manifest,
            "observe",
            step=step_index + 1,
            workspace=str(plan.get("current_stage", "")),
            payload={
                "status": plan.get("status", ""),
                "current_stage": plan.get("current_stage", ""),
                "allowed_action_ids": [str(action.get("id", "")) for action in actions],
            },
        )
        if not actions:
            manifest["status"] = "complete"
            manifest["final_plan"] = plan
            break

        context = build_action_context(plan)
        decision = select_agent_action(context, actions, model_decider=decider)
        action = dict(decision.get("action", {}) or {})
        _append_event(
            manifest,
            "decision",
            step=step_index + 1,
            workspace=str(action.get("workspace") or context.get("current_stage") or ""),
            payload={
                "source": decision.get("source", ""),
                "action_id": action.get("id", ""),
                "rationale": decision.get("rationale", ""),
            },
        )
        execution = _execute_or_stage_action(action, dry_run=dry_run)
        _append_event(
            manifest,
            "execution",
            step=step_index + 1,
            workspace=str(action.get("workspace") or context.get("current_stage") or ""),
            payload={
                "action_id": action.get("id", ""),
                "status": execution.get("status", ""),
                "executed": bool(execution.get("executed")),
            },
        )
        manifest["steps"].append(
            {
                "step": step_index + 1,
                "workspace": str(action.get("workspace") or context.get("current_stage") or ""),
                "plan_status": plan.get("status", ""),
                "current_stage": plan.get("current_stage", ""),
                "decision": {
                    "source": decision.get("source", ""),
                    "rationale": decision.get("rationale", ""),
                },
                "selected_action": action,
                "execution": execution,
            }
        )

        if execution["status"] == "dry_run":
            manifest["status"] = "dry_run"
            manifest["final_plan"] = plan
            break
        if execution["status"] == "blocked_human":
            manifest["status"] = "blocked_human"
            manifest["final_plan"] = plan
            break
        if execution["status"] != "succeeded":
            manifest["status"] = "failed"
            manifest["final_plan"] = plan
            break
    else:
        manifest["status"] = "max_steps_reached"
        manifest["final_plan"] = build_agent_plan(
            db_path,
            acceptance_dir=acceptance_dir,
            workspace_path=workspace_path,
            annotation_layers_path=annotation_layers_path,
        )

    manifest["finished_at"] = _utc_now()
    if run_output is not None:
        _write_json(Path(run_output), manifest)
    return manifest


def build_action_context(plan: dict[str, Any]) -> dict[str, Any]:
    actions = [
        {
            "id": str(action.get("id", "")),
            "title": str(action.get("title", "")),
            "workspace": str(action.get("workspace", "")),
            "priority": int(action.get("priority") or 0),
            "requires_human": bool(action.get("requires_human")),
            "reason": str(action.get("reason", "")),
        }
        for action in plan.get("actions", []) or []
    ]
    status_report = dict(plan.get("status_report", {}) or {})
    evidence = dict(status_report.get("evidence_store", {}) or {})
    acceptance = dict(status_report.get("acceptance_workbench", {}) or {})
    return {
        "agent": AGENT_NAME,
        "mode": AGENT_MODE,
        "status": str(plan.get("status", "")),
        "current_stage": str(plan.get("current_stage", "")),
        "allowed_actions": actions,
        "evidence_summary": {
            "status": str(evidence.get("status", "")),
            "documents": int(evidence.get("documents") or 0),
            "spans": int(evidence.get("spans") or 0),
            "missing_anchor_spans": int(evidence.get("missing_anchor_spans") or 0),
        },
        "acceptance_summary": {
            "status": str(acceptance.get("status", "")),
            "validation_passed": bool(acceptance.get("validation_passed")),
            "questions": int(acceptance.get("questions") or 0),
            "issue_count": int(acceptance.get("issue_count") or 0),
        },
    }


def select_agent_action(
    context: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    model_decider: ModelDecider | None = None,
) -> dict[str, Any]:
    ordered_actions = sorted(actions, key=lambda action: int(action.get("priority") or 0))
    fallback = dict(ordered_actions[0]) if ordered_actions else {}
    if not ordered_actions:
        return {"source": "no_actions", "action": {}, "rationale": "No allowed action is available."}

    if model_decider is None:
        return {
            "source": "deterministic_policy",
            "action": fallback,
            "rationale": "Selected the lowest-priority allowed action.",
        }

    try:
        model_result = dict(model_decider(context) or {})
    except Exception as error:  # pragma: no cover - defensive around local model servers
        return {
            "source": "model_error_fallback",
            "action": fallback,
            "rationale": f"{type(error).__name__}: {error}",
        }

    requested_id = str(model_result.get("action_id", "")).strip()
    allowed = {str(action.get("id", "")): dict(action) for action in ordered_actions}
    if requested_id in allowed:
        return {
            "source": "local_model",
            "action": allowed[requested_id],
            "rationale": str(model_result.get("rationale", "")),
        }
    return {
        "source": "model_invalid_fallback",
        "action": fallback,
        "rationale": f"Model requested invalid action_id={requested_id!r}.",
    }


class OpenAICompatibleActionDecider:
    def __init__(self, config: LocalModelConfig):
        self.config = config

    def __call__(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = _decision_prompt(context)
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a local small-model scheduler. Choose exactly one action_id "
                        "from allowed_actions. Return compact JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        data = json.dumps(payload).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            api_key = os.environ.get(self.config.api_key_env, "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        req = request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"local model request failed: {error}") from error
        content = str(response_payload["choices"][0]["message"]["content"])
        return _parse_model_json(content)


def _execute_or_stage_action(action: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    if bool(action.get("requires_human")):
        return {
            "status": "blocked_human",
            "executed": False,
            "reason": "Action requires human review and cannot be executed automatically.",
        }
    if dry_run:
        return {
            "status": "dry_run",
            "executed": False,
            "reason": "Dry-run mode records the selected action without executing it.",
        }
    argv = [str(value) for value in action.get("argv", []) or []]
    if not argv:
        return {
            "status": "unsupported_command",
            "executed": False,
            "reason": "Action has no safe internal argv representation.",
        }
    return _run_scansci_argv(argv)


def _run_scansci_argv(argv: list[str]) -> dict[str, Any]:
    from . import cli

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = int(cli.main(argv) or 0)
    return {
        "status": "succeeded" if exit_code == 0 else "failed",
        "executed": True,
        "exit_code": exit_code,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
    }


def _decision_prompt(context: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Choose the next ScanSci Evidence Agent action.",
            "constraints": [
                "Choose one action_id from allowed_actions.",
                "Do not invent commands.",
                "If an action requires human review, you may choose it only to stop at the human gate.",
            ],
            "context": context,
            "response_schema": {"action_id": "string", "rationale": "short string"},
        },
        ensure_ascii=False,
    )


def _parse_model_json(content: str) -> dict[str, Any]:
    try:
        return dict(json.loads(content))
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return dict(json.loads(content[start : end + 1]))
        raise


def _model_summary(config: LocalModelConfig | None) -> dict[str, Any]:
    if config is None or not config.enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "provider": "openai-compatible",
        "base_url": config.base_url,
        "model": config.model,
        "api_key_env": config.api_key_env,
        "timeout_seconds": config.timeout_seconds,
    }


def _worker_model_summary(config: LocalModelConfig | None) -> dict[str, Any]:
    summary = _model_summary(config)
    summary["role"] = "action_decider"
    return summary


def _normalize_control_plane(value: str) -> str:
    normalized = str(value or "codex").strip().lower().replace("_", "-")
    allowed = {"codex", "human", "automation"}
    return normalized if normalized in allowed else "codex"


def _autonomy_summary(*, autonomy_level: str, dry_run: bool) -> dict[str, Any]:
    explicit = str(autonomy_level or "").strip().upper()
    level = explicit if explicit in {"L0", "L1", "L2", "L3", "L4"} else ("L1" if dry_run else "L2")
    effects_by_level = {
        "L0": ["advise_only"],
        "L1": ["dry_run_manifest"],
        "L2": ["safe_internal_actions", "human_gates_enforced"],
        "L3": ["safe_internal_actions", "approval_required_for_expensive_or_destructive_actions"],
        "L4": ["scheduled_unattended_actions_with_budget_and_human_gates"],
    }
    return {
        "level": level,
        "dry_run": bool(dry_run),
        "allowed_effects": effects_by_level[level],
        "human_gates": ["review_acceptance_gold"],
    }


def _append_event(
    manifest: dict[str, Any],
    event_type: str,
    *,
    step: int,
    workspace: str,
    payload: dict[str, Any],
) -> None:
    events = manifest.setdefault("events", [])
    events.append(
        {
            "event_id": f"evt-{len(events) + 1:04d}",
            "type": event_type,
            "step": step,
            "workspace": workspace,
            "timestamp": _utc_now(),
            "payload": payload,
        }
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
