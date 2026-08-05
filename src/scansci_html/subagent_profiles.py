"""Reusable subagent profiles with explicit write-path isolation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


PROFILE_SCHEMA = "scansci.subagent-profile.v1"


def _strings(value: Any, limit: int = 64) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = []
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))[:limit]


@dataclass(frozen=True)
class SubagentProfile:
    name: str
    prompt: str = ""
    description: str = ""
    tools: tuple[str, ...] = ()
    model: str = ""
    effort: str = "medium"
    write_paths: tuple[str, ...] = ()
    max_concurrency: int = 1
    extra: Mapping[str, Any] = None  # type: ignore[assignment]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SubagentProfile":
        raw = dict(payload)
        known = {"schema_version", "name", "prompt", "description", "tools", "model", "effort", "write_paths", "max_concurrency"}
        return cls(
            name=str(raw.get("name") or "").strip(),
            prompt=str(raw.get("prompt") or ""),
            description=str(raw.get("description") or ""),
            tools=_strings(raw.get("tools")),
            model=str(raw.get("model") or "").strip(),
            effort=str(raw.get("effort") or "medium").strip(),
            write_paths=_strings(raw.get("write_paths")),
            max_concurrency=max(1, min(32, int(raw.get("max_concurrency", 1) or 1))),
            extra={key: value for key, value in raw.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.extra or {})
        payload.update({
            "schema_version": PROFILE_SCHEMA,
            "name": self.name,
            "prompt": self.prompt,
            "description": self.description,
            "tools": list(self.tools),
            "model": self.model,
            "effort": self.effort,
            "write_paths": list(self.write_paths),
            "max_concurrency": self.max_concurrency,
        })
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def load_profiles(root: str | Path) -> list[SubagentProfile]:
    directory = Path(root).resolve() / ".scansci" / "subagents"
    profiles: list[SubagentProfile] = []
    if not directory.is_dir():
        return profiles
    for path in sorted(directory.glob("*.json")):
        try:
            profile = SubagentProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if profile.name:
            profiles.append(profile)
    return profiles


def _normalise_path(path: str, root: Path) -> str:
    raw = Path(str(path).strip())
    resolved = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return "../outside-workspace"


def _overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")


def validate_parallel_write_isolation(
    profiles: Iterable[SubagentProfile],
    *,
    root: str | Path,
) -> list[str]:
    root_path = Path(root).resolve()
    records: list[tuple[str, str]] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    for profile in profiles:
        if not profile.name:
            errors.append("profile name is empty")
        if profile.name in seen_names:
            errors.append(f"duplicate profile name: {profile.name}")
        seen_names.add(profile.name)
        paths = [_normalise_path(path, root_path) for path in profile.write_paths]
        if "../outside-workspace" in paths:
            errors.append(f"profile {profile.name} declares a path outside the workspace")
        for path in paths:
            records.append((profile.name, path))
    for index, (left_name, left_path) in enumerate(records):
        for right_name, right_path in records[index + 1:]:
            if left_name != right_name and _overlap(left_path, right_path):
                errors.append(f"parallel write overlap: {left_name}:{left_path} <-> {right_name}:{right_path}")
    return list(dict.fromkeys(errors))


def plan_parallel_batches(
    tasks: Iterable[Mapping[str, Any]],
    profiles: Iterable[SubagentProfile],
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Greedily schedule non-overlapping tasks into deterministic batches."""

    profile_map = {profile.name: profile for profile in profiles}
    errors = validate_parallel_write_isolation(profile_map.values(), root=root)
    batches: list[list[dict[str, Any]]] = []
    for raw_task in tasks:
        task = dict(raw_task)
        task_id = str(task.get("id") or task.get("task_id") or f"task-{len(batches)}")
        profile = profile_map.get(str(task.get("profile") or ""))
        if profile is None:
            errors.append(f"unknown profile for task {task_id}")
            continue
        task_paths = tuple(_normalise_path(path, Path(root).resolve()) for path in (task.get("write_paths") or profile.write_paths))
        task["id"] = task_id
        task["profile"] = profile.name
        task["write_paths"] = list(task_paths)
        placed = False
        for batch in batches:
            occupied = {path for item in batch for path in item.get("write_paths", [])}
            concurrency = sum(1 for item in batch if item.get("profile") == profile.name)
            if concurrency >= profile.max_concurrency or any(_overlap(path, other) for path in task_paths for other in occupied):
                continue
            batch.append(task)
            placed = True
            break
        if not placed:
            batches.append([task])
    return {"schema_version": "scansci.subagent-plan.v1", "valid": not errors, "errors": list(dict.fromkeys(errors)), "batches": batches}


__all__ = [
    "PROFILE_SCHEMA",
    "SubagentProfile",
    "load_profiles",
    "plan_parallel_batches",
    "validate_parallel_write_isolation",
]
