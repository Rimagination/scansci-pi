"""Local Skill package installation and skills.sh marketplace access.

The manager intentionally keeps a canonical copy inside the current ScanSci
workspace.  It accepts only declarative Skill folders (``SKILL.md`` plus their
supporting files); it never executes a package during installation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import zipfile
from uuid import uuid4

from .app_settings import load_settings, save_settings
from .builtin_skills import builtin_skill_asset_path
from .skill_security import scan_skill_packages


_LIBRARY_NAME = ".scansci-skills"
_SKILL_FILE = "SKILL.md"
_MAX_ARCHIVE_FILES = 2_000
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_MARKETPLACE_BYTES = 12 * 1024 * 1024
_SKILL_ID = re.compile(r"[^a-z0-9._-]+")
_MARKETPLACE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*){1,2}$", re.IGNORECASE)
_SCAN_ID = re.compile(r"^[0-9a-f]{32}$")
_QUARANTINE_NAME = ".scansci-skill-quarantine"
_SCAN_TTL = timedelta(minutes=30)
_IGNORED_PACKAGE_NAMES = (".git", ".venv", "venv", "node_modules", "__pycache__", ".DS_Store")
_GITHUB_TREE_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:tree|blob)/(?P<branch>[^/]+)(?:/(?P<path>.*))?/?$",
    re.IGNORECASE,
)


class SkillInstallError(ValueError):
    """Raised when a Skill source is malformed or cannot be copied safely."""


_MARKETPLACE_FALLBACK: list[dict[str, Any]] = [
    {
        "id": "vercel-labs/agent-skills/web-design-guidelines",
        "slug": "web-design-guidelines",
        "name": "web-design-guidelines",
        "source": "vercel-labs/agent-skills",
        "installs": 0,
        "sourceType": "github",
        "installUrl": "https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines",
        "url": "https://skills.sh/vercel-labs/agent-skills/web-design-guidelines",
        "fallbackGitUrl": "https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines",
    },
    {
        "id": "vercel-labs/agent-skills/react-best-practices",
        "slug": "react-best-practices",
        "name": "react-best-practices",
        "source": "vercel-labs/agent-skills",
        "installs": 0,
        "sourceType": "github",
        "installUrl": "https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices",
        "url": "https://skills.sh/vercel-labs/agent-skills/react-best-practices",
        "fallbackGitUrl": "https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices",
    },
]


def skill_library_path(workspace: str | Path) -> Path:
    """Return the workspace-scoped canonical Skill library path."""

    return Path(workspace).resolve().parent / _LIBRARY_NAME


def installed_skills(workspace: str | Path) -> list[dict[str, Any]]:
    """Return configured Skills annotated with package availability."""

    rows: list[dict[str, Any]] = []
    for raw in load_settings(workspace).get("skills", []):
        item = dict(raw)
        if item.get("uninstalled"):
            continue
        path = str(item.get("path", "") or "")
        item["builtin"] = path.startswith("builtin:")
        if item["builtin"]:
            asset_path = builtin_skill_asset_path(path.removeprefix("builtin:"))
            if (asset_path / _SKILL_FILE).is_file():
                item["package_path"] = str(asset_path)
                item["skill_file"] = str(asset_path / _SKILL_FILE)
            item["available"] = (asset_path / _SKILL_FILE).is_file()
        else:
            package_path = Path(path)
            skill_file = package_path / _SKILL_FILE
            if skill_file.is_file():
                item["package_path"] = str(package_path)
                item["skill_file"] = str(skill_file)
            item["available"] = skill_file.is_file()
        rows.append(item)
    return rows


def marketplace_skills(*, query: str = "", view: str = "trending", limit: int = 36) -> dict[str, Any]:
    """Read a compact skills.sh listing, with a useful offline fallback."""

    clean_query = str(query or "").strip()
    safe_limit = max(1, min(int(limit or 36), 100))
    try:
        if len(clean_query) >= 2:
            endpoint = "https://skills.sh/api/search?" + urlencode({"q": clean_query, "limit": safe_limit})
            payload = _fetch_json(endpoint)
            source_rows = payload.get("skills", []) if isinstance(payload, dict) else []
        else:
            safe_view = view if view in {"all-time", "trending", "hot"} else "trending"
            source_rows = _fetch_marketplace_leaderboard(safe_view, limit=safe_limit)
        items = [_marketplace_item(item) for item in source_rows if isinstance(item, dict)]
        if not items:
            raise SkillInstallError("skills.sh returned no Skill records")
        return {"items": items, "offline": False, "provider": "skills.sh"}
    except (SkillInstallError, ValueError, OSError):
        lowered = clean_query.lower()
        items = [
            deepcopy(item)
            for item in _MARKETPLACE_FALLBACK
            if not lowered or lowered in " ".join(str(item.get(key, "")) for key in ("name", "source", "slug")).lower()
        ]
        return {"items": items, "offline": True, "provider": "skills.sh"}


def scan_skill_source(workspace: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a source into quarantine and statically scan the exact snapshot."""

    source_type = str(payload.get("source_type", "") or "").strip().lower()
    source = str(payload.get("source", "") or "").strip()
    if source_type not in {"local", "git", "archive", "marketplace"}:
        raise SkillInstallError("source_type must be local, git, archive, or marketplace")
    if not source:
        raise SkillInstallError("请选择或输入 Skill 来源")

    temporary: Path | None = None
    recorded_source = source
    scan_id = uuid4().hex
    quarantine = _skill_quarantine_path(workspace)
    _cleanup_skill_quarantine(quarantine)
    scan_root = quarantine / scan_id
    try:
        if source_type == "local":
            root = _local_source_root(source)
            recorded_source = str(root)
            roots = _find_skill_roots(root)
        elif source_type == "archive":
            recorded_source = str(Path(source).expanduser().resolve())
            temporary = _extract_archive(source)
            roots = _find_skill_roots(temporary)
        elif source_type == "git":
            temporary, root = _clone_git_source(source)
            roots = _find_skill_roots(root)
        else:
            temporary, root = _clone_git_source(_marketplace_git_fallback(source))
            roots = [_marketplace_skill_root(root, source)]
        _validate_skill_source_size(roots)
        packages_root = scan_root / "packages"
        packages_root.mkdir(parents=True, exist_ok=False)
        snapshots: list[Path] = []
        for index, skill_root in enumerate(roots, start=1):
            package_name = f"{index:02d}-{_slug(skill_root.name)}"
            destination = packages_root / package_name
            shutil.copytree(skill_root, destination, ignore=shutil.ignore_patterns(*_IGNORED_PACKAGE_NAMES))
            snapshots.append(destination)
        report = scan_skill_packages(snapshots, source_type=source_type, source=recorded_source)
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + _SCAN_TTL
        manifest = {
            "scan_id": scan_id,
            "source_type": source_type,
            "source": recorded_source,
            "created_at": created_at.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "packages": [item.name for item in snapshots],
            "report": report,
        }
        (scan_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "scan_id": scan_id,
            "scan": report,
            "requires_confirmation": report["verdict"] != "BLOCKED",
            "expires_at": manifest["expires_at"],
        }
    except Exception:
        shutil.rmtree(scan_root, ignore_errors=True)
        raise
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def install_skill(workspace: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Install a previously scanned quarantine snapshot after user confirmation."""

    scan_id = str(payload.get("scan_id", "") or "").strip().lower()
    if not _SCAN_ID.fullmatch(scan_id):
        raise SkillInstallError("安装前必须先完成 Skill 安全检查")
    if str(payload.get("decision", "") or "").strip().lower() != "install":
        raise SkillInstallError("需要明确确认后才能安装 Skill")

    scan_root, manifest = _load_scan_manifest(workspace, scan_id)
    report = dict(manifest.get("report", {}) or {})
    verdict = str(report.get("verdict", "BLOCKED") or "BLOCKED").upper()
    if verdict == "BLOCKED":
        raise SkillInstallError("安全检查已阻止安装该 Skill")
    if verdict == "REVIEW" and payload.get("acknowledge_risk") is not True:
        raise SkillInstallError("请先阅读风险并明确勾选确认")

    packages_root = (scan_root / "packages").resolve()
    roots: list[Path] = []
    for name in manifest.get("packages", []):
        candidate = (packages_root / str(name)).resolve()
        try:
            candidate.relative_to(packages_root)
        except ValueError as error:
            raise SkillInstallError("Skill 隔离快照路径无效") from error
        if not candidate.is_dir():
            raise SkillInstallError("Skill 隔离快照已失效，请重新检查")
        roots.append(candidate)
    if not roots:
        raise SkillInstallError("Skill 隔离快照中没有可安装内容")

    current_report = scan_skill_packages(
        roots,
        source_type=str(manifest.get("source_type", "")),
        source=str(manifest.get("source", "")),
    )
    if current_report.get("fingerprint") != report.get("fingerprint") or current_report.get("verdict") != verdict:
        raise SkillInstallError("Skill 隔离快照在确认前发生变化，请重新检查")

    installed = _copy_into_library(
        workspace,
        roots=roots,
        source_type=str(manifest.get("source_type", "")),
        source=str(manifest.get("source", "")),
        security_scan=_security_scan_summary(current_report),
    )
    shutil.rmtree(scan_root, ignore_errors=True)
    settings = load_settings(workspace)
    return {
        "installed": installed,
        "skills": installed_skills(workspace),
        "settings": settings,
        "scan": current_report,
    }


def check_skill_updates(workspace: str | Path) -> dict[str, Any]:
    """Check tracked external Skills without changing the installed library.

    A Skill is only eligible for automatic update when its provenance is a
    public HTTPS Git or marketplace source.  Local folders and archives are
    intentionally reported as manual sources because ScanSci cannot infer a
    trustworthy remote version for them.  Every remote snapshot is scanned by
    the same static security gate used during installation.
    """

    results: list[dict[str, Any]] = []
    for record in installed_skills(workspace):
        base = {
            "id": str(record.get("id", "")),
            "name": str(record.get("name", "") or record.get("id", "")),
            "source_type": str(record.get("source_type", "") or ""),
            "source": str(record.get("source", "") or ""),
            "available": False,
        }
        if record.get("builtin"):
            results.append({**base, "state": "bundled", "message": "随 ScanSci 应用更新"})
            continue
        source_type = str(record.get("source_type", "") or "").strip().lower()
        if source_type not in {"git", "marketplace"}:
            results.append({**base, "state": "manual", "message": "本地来源没有可自动检查的远程版本"})
            continue
        try:
            current_root = _installed_skill_root(record)
            current_report = scan_skill_packages(
                [current_root],
                source_type=source_type,
                source=str(record.get("source", "")),
            )
            temporary, repository_root = _acquire_skill_update_source(record)
            try:
                remote_roots = _find_skill_roots(repository_root)
                remote_root = _select_skill_root(remote_roots, record)
                _validate_skill_source_size([remote_root])
                remote_report = scan_skill_packages(
                    [remote_root],
                    source_type=source_type,
                    source=str(record.get("source", "")),
                )
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
            remote_verdict = str(remote_report.get("verdict", "BLOCKED") or "BLOCKED").upper()
            fingerprint_changed = current_report.get("fingerprint") != remote_report.get("fingerprint")
            if remote_verdict == "BLOCKED":
                results.append({
                    **base,
                    "state": "blocked",
                    "message": "远程版本未通过安全检查，已阻止更新",
                    "current_fingerprint": current_report.get("fingerprint", ""),
                    "latest_fingerprint": remote_report.get("fingerprint", ""),
                    "latest_scan": _security_scan_summary(remote_report),
                })
                continue
            results.append({
                **base,
                "state": "available" if fingerprint_changed else "current",
                "available": fingerprint_changed,
                "message": "发现可更新版本" if fingerprint_changed else "当前已是最新内容",
                "current_fingerprint": current_report.get("fingerprint", ""),
                "latest_fingerprint": remote_report.get("fingerprint", ""),
                "latest_scan": _security_scan_summary(remote_report),
            })
        except (OSError, ValueError, SkillInstallError) as error:
            results.append({**base, "state": "error", "message": "检查更新失败", "error": str(error)[:500]})
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skills": results,
        "available_count": sum(1 for item in results if item.get("available")),
        "error_count": sum(1 for item in results if item.get("state") == "error"),
    }


def scan_skill_update(workspace: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Acquire and scan one remote Skill update into a quarantine snapshot."""

    record = _find_external_skill(workspace, str(payload.get("record_id", "") or "").strip())
    source_type = str(record.get("source_type", "") or "").strip().lower()
    if source_type not in {"git", "marketplace"}:
        raise SkillInstallError("这个 Skill 没有可自动更新的远程来源")
    current_root = _installed_skill_root(record)
    current_report = scan_skill_packages([current_root], source_type=source_type, source=str(record.get("source", "")))
    temporary, repository_root = _acquire_skill_update_source(record)
    scan_id = uuid4().hex
    quarantine = _skill_quarantine_path(workspace)
    _cleanup_skill_quarantine(quarantine)
    scan_root = quarantine / scan_id
    try:
        remote_root = _select_skill_root(_find_skill_roots(repository_root), record)
        _validate_skill_source_size([remote_root])
        packages_root = scan_root / "packages"
        packages_root.mkdir(parents=True, exist_ok=False)
        destination = packages_root / f"01-{_slug(remote_root.name)}"
        shutil.copytree(remote_root, destination, ignore=shutil.ignore_patterns(*_IGNORED_PACKAGE_NAMES))
        report = scan_skill_packages([destination], source_type=source_type, source=str(record.get("source", "")))
        created_at = datetime.now(timezone.utc)
        manifest = {
            "scan_id": scan_id,
            "operation": "update",
            "record_id": str(record.get("id", "")),
            "target_path": str(Path(str(record.get("path", ""))).resolve()),
            "current_fingerprint": current_report.get("fingerprint", ""),
            "source_type": source_type,
            "source": str(record.get("source", "")),
            "created_at": created_at.isoformat(timespec="seconds"),
            "expires_at": (created_at + _SCAN_TTL).isoformat(timespec="seconds"),
            "packages": [destination.name],
            "report": report,
        }
        (scan_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "scan_id": scan_id,
            "record_id": str(record.get("id", "")),
            "scan": report,
            "current_fingerprint": current_report.get("fingerprint", ""),
            "requires_confirmation": report["verdict"] != "BLOCKED",
            "expires_at": manifest["expires_at"],
        }
    except Exception:
        shutil.rmtree(scan_root, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def update_skill(workspace: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Replace one external Skill atomically after a fresh security scan.

    The previous package is moved to a workspace-scoped backup before the new
    snapshot is promoted.  If either the filesystem swap or settings write
    fails, both are restored before the error is returned to the UI.
    """

    scan_id = str(payload.get("scan_id", "") or "").strip().lower()
    if not _SCAN_ID.fullmatch(scan_id):
        raise SkillInstallError("更新前必须先完成 Skill 安全检查")
    if str(payload.get("decision", "") or "").strip().lower() != "update":
        raise SkillInstallError("需要明确确认后才能更新 Skill")
    scan_root, manifest = _load_scan_manifest(workspace, scan_id)
    if str(manifest.get("operation", "")) != "update":
        raise SkillInstallError("这份安全快照不是 Skill 更新快照")
    record_id = str(manifest.get("record_id", "") or "")
    record = _find_external_skill(workspace, record_id)
    report = dict(manifest.get("report", {}) or {})
    verdict = str(report.get("verdict", "BLOCKED") or "BLOCKED").upper()
    if verdict == "BLOCKED":
        raise SkillInstallError("安全检查已阻止更新这个 Skill")
    if verdict == "REVIEW" and payload.get("acknowledge_risk") is not True:
        raise SkillInstallError("请先阅读风险并明确勾选确认")

    packages_root = (scan_root / "packages").resolve()
    roots: list[Path] = []
    for name in manifest.get("packages", []):
        candidate = (packages_root / str(name)).resolve()
        try:
            candidate.relative_to(packages_root)
        except ValueError as error:
            raise SkillInstallError("Skill 更新快照路径无效") from error
        if not candidate.is_dir():
            raise SkillInstallError("Skill 更新快照已失效，请重新检查")
        roots.append(candidate)
    if len(roots) != 1:
        raise SkillInstallError("一次只能更新一个 Skill")
    snapshot_report = scan_skill_packages(
        roots,
        source_type=str(manifest.get("source_type", "")),
        source=str(manifest.get("source", "")),
    )
    if snapshot_report.get("fingerprint") != report.get("fingerprint") or snapshot_report.get("verdict") != verdict:
        raise SkillInstallError("Skill 更新快照在确认前发生变化，请重新检查")

    library = skill_library_path(workspace).resolve()
    target = Path(str(record.get("path", ""))).resolve()
    if target.parent != library or target.name.startswith(".") or not target.is_dir():
        raise SkillInstallError("Skill 安装目录无效，已取消更新")
    if target != Path(str(manifest.get("target_path", ""))).resolve():
        raise SkillInstallError("Skill 安装位置已变化，请重新检查")
    current_report = scan_skill_packages(
        [target],
        source_type=str(manifest.get("source_type", "")),
        source=str(manifest.get("source", "")),
    )
    if current_report.get("fingerprint") != manifest.get("current_fingerprint"):
        raise SkillInstallError("当前 Skill 内容已变化，请重新检查后再更新")

    settings_before = load_settings(workspace)
    stage_parent = Path(tempfile.mkdtemp(prefix=".scansci-skill-update-", dir=library.parent))
    backup_parent = library.parent / ".scansci-skill-backups" / _slug(record_id)
    backup_parent.mkdir(parents=True, exist_ok=True)
    backup = backup_parent / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    staged = stage_parent / target.name
    promoted = False
    try:
        shutil.copytree(roots[0], staged, ignore=shutil.ignore_patterns(*_IGNORED_PACKAGE_NAMES))
        _ensure_no_symlinks(staged)
        target.replace(backup)
        staged.replace(target)
        promoted = True
        metadata = _skill_metadata(target / _SKILL_FILE, fallback=target.name)
        records = list(settings_before.get("skills", []) or [])
        updated_record: dict[str, Any] | None = None
        for index, item in enumerate(records):
            if str(item.get("id", "")) != record_id:
                continue
            replacement = {
                **item,
                "name": metadata["name"],
                "description": metadata["description"],
                "path": str(target),
                "source_type": str(manifest.get("source_type", "")),
                "source": str(manifest.get("source", "")),
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "security_scan": _security_scan_summary(snapshot_report),
            }
            records[index] = replacement
            updated_record = replacement
            break
        if updated_record is None:
            raise SkillInstallError("找不到待更新的 Skill 配置")
        settings_before["skills"] = records
        settings = save_settings(workspace, settings_before)
        installed_record = next((item for item in settings.get("skills", []) if str(item.get("id", "")) == record_id), updated_record)
        shutil.rmtree(scan_root, ignore_errors=True)
        return {
            "updated": installed_record,
            "backup_path": str(backup),
            "skills": installed_skills(workspace),
            "settings": settings,
            "scan": snapshot_report,
        }
    except Exception as error:
        rollback_error: Exception | None = None
        try:
            if promoted and target.exists():
                shutil.rmtree(target, ignore_errors=False)
            if backup.exists():
                backup.replace(target)
            save_settings(workspace, settings_before)
        except Exception as restore_error:  # pragma: no cover - catastrophic filesystem failure
            rollback_error = restore_error
        if rollback_error is not None:
            raise SkillInstallError(f"Skill 更新失败，自动回滚也失败：{rollback_error}") from error
        raise SkillInstallError(f"Skill 更新失败，已自动回滚：{error}") from error
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def _find_external_skill(workspace: str | Path, record_id: str) -> dict[str, Any]:
    if not record_id:
        raise SkillInstallError("缺少 Skill 标识")
    record = next((item for item in installed_skills(workspace) if str(item.get("id", "")) == record_id), None)
    if record is None:
        raise SkillInstallError("找不到要更新的 Skill")
    if record.get("builtin"):
        raise SkillInstallError("内置 Skill 会随 ScanSci 应用更新")
    return record


def _installed_skill_root(record: dict[str, Any]) -> Path:
    path = Path(str(record.get("path", ""))).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise SkillInstallError("本地 Skill 文件已不存在") from error
    if not resolved.is_dir() or not (resolved / _SKILL_FILE).is_file():
        raise SkillInstallError("本地 Skill 文件不完整")
    _ensure_no_symlinks(resolved)
    return resolved


def _acquire_skill_update_source(record: dict[str, Any]) -> tuple[Path, Path]:
    source_type = str(record.get("source_type", "") or "").strip().lower()
    source = str(record.get("source", "") or "").strip()
    if source_type == "marketplace":
        return _clone_git_source(_marketplace_git_fallback(source))
    if source_type == "git":
        return _clone_git_source(source)
    raise SkillInstallError("这个 Skill 来源不支持自动更新")


def _select_skill_root(roots: list[Path], record: dict[str, Any]) -> Path:
    if len(roots) == 1:
        return roots[0]
    expected = {
        _slug(record.get("name", "")),
        _slug(Path(str(record.get("path", ""))).name),
        _slug(record.get("id", "")),
    }
    matches = []
    for root in roots:
        metadata = _skill_metadata(root / _SKILL_FILE, fallback=root.name)
        candidates = {_slug(root.name), _slug(metadata["id"]), _slug(metadata["name"])}
        if expected & candidates:
            matches.append(root)
    if len(matches) == 1:
        return matches[0]
    raise SkillInstallError("远程来源包含多个 Skill，无法安全判断更新目标")


def cancel_skill_scan(workspace: str | Path, scan_id: str) -> dict[str, Any]:
    """Discard one pending quarantine snapshot without touching installed Skills."""

    normalized = str(scan_id or "").strip().lower()
    if not _SCAN_ID.fullmatch(normalized):
        return {"ok": False}
    target = _skill_quarantine_path(workspace) / normalized
    existed = target.is_dir()
    shutil.rmtree(target, ignore_errors=True)
    return {"ok": existed}


def _skill_quarantine_path(workspace: str | Path) -> Path:
    return Path(workspace).resolve().parent / _QUARANTINE_NAME


def _cleanup_skill_quarantine(quarantine: Path) -> None:
    quarantine.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - _SCAN_TTL
    for candidate in quarantine.iterdir():
        if not candidate.is_dir():
            continue
        manifest_path = candidate / "manifest.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(str(payload.get("created_at", "")))
            stale = created_at < cutoff
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            try:
                modified_at = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
                stale = modified_at < cutoff
            except OSError:
                stale = True
        if stale:
            shutil.rmtree(candidate, ignore_errors=True)


def _load_scan_manifest(workspace: str | Path, scan_id: str) -> tuple[Path, dict[str, Any]]:
    scan_root = _skill_quarantine_path(workspace) / scan_id
    manifest_path = scan_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SkillInstallError("Skill 安全检查已失效，请重新检查") from error
    try:
        expires_at = datetime.fromisoformat(str(manifest.get("expires_at", "")))
    except ValueError as error:
        raise SkillInstallError("Skill 安全检查记录无效") from error
    if expires_at.tzinfo is None:
        raise SkillInstallError("Skill 安全检查记录无效")
    if expires_at <= datetime.now(timezone.utc):
        shutil.rmtree(scan_root, ignore_errors=True)
        raise SkillInstallError("Skill 安全检查已过期，请重新检查")
    return scan_root, manifest


def _security_scan_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": report.get("version"),
        "verdict": report.get("verdict"),
        "scanned_at": report.get("scanned_at"),
        "fingerprint": report.get("fingerprint"),
        "package_count": report.get("package_count"),
        "file_count": report.get("file_count"),
        "byte_count": report.get("byte_count"),
        "counts": dict(report.get("counts", {}) or {}),
        "scanners": list(report.get("scanners", []) or []),
        "findings": list(report.get("findings", []) or []),
        "recommendation": report.get("recommendation"),
    }


def _local_source_root(source: str) -> Path:
    path = Path(source).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise SkillInstallError(f"找不到本地来源：{path}") from error
    if resolved.is_file():
        if resolved.name.lower() != _SKILL_FILE.lower():
            raise SkillInstallError("本地文件必须是 SKILL.md")
        return resolved.parent
    if not resolved.is_dir():
        raise SkillInstallError("本地来源必须是 Skill 文件夹或 SKILL.md")
    return resolved


def _validate_skill_source_size(roots: list[Path]) -> None:
    file_count = 0
    byte_count = 0
    for root in roots:
        for item in root.rglob("*"):
            if item.is_symlink():
                raise SkillInstallError(f"Skill 不能包含符号链接：{item.name}")
            if not item.is_file() or any(part in set(_IGNORED_PACKAGE_NAMES) for part in item.parts):
                continue
            file_count += 1
            byte_count += item.stat().st_size
            if file_count > _MAX_ARCHIVE_FILES or byte_count > _MAX_ARCHIVE_BYTES:
                raise SkillInstallError("Skill 来源超过 ScanSci 的安全安装上限")


def _extract_archive(source: str) -> Path:
    archive = Path(source).expanduser()
    try:
        archive = archive.resolve(strict=True)
    except OSError as error:
        raise SkillInstallError(f"找不到压缩包：{archive}") from error
    if archive.suffix.lower() not in {".zip", ".skill"}:
        raise SkillInstallError("仅支持 .zip 或 .skill Skill 压缩包")
    target = Path(tempfile.mkdtemp(prefix="scansci-skill-archive-"))
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            total_size = sum(entry.file_size for entry in entries)
            if len(entries) > _MAX_ARCHIVE_FILES or total_size > _MAX_ARCHIVE_BYTES:
                raise SkillInstallError("压缩包超过 ScanSci 的安全安装上限")
            for entry in entries:
                relative = PurePosixPath(entry.filename)
                if relative.is_absolute() or ".." in relative.parts or not entry.filename:
                    raise SkillInstallError("压缩包包含不安全的文件路径")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise SkillInstallError("压缩包不能包含符号链接")
                destination = target.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if entry.is_dir():
                    destination.mkdir(exist_ok=True)
                else:
                    with bundle.open(entry) as reader, destination.open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
        return target
    except (OSError, zipfile.BadZipFile) as error:
        shutil.rmtree(target, ignore_errors=True)
        raise SkillInstallError(f"无法读取 Skill 压缩包：{error}") from error
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _clone_git_source(source: str) -> tuple[Path, Path]:
    clone_url, branch, relative = _parse_git_source(source)
    if shutil.which("git") is None:
        raise SkillInstallError("未检测到 Git，无法从仓库安装 Skill")
    target = Path(tempfile.mkdtemp(prefix="scansci-skill-git-"))
    checkout = target / "checkout"
    command = ["git", "-c", f"core.hooksPath={target / 'disabled-hooks'}", "clone", "--depth", "1", "--filter=blob:none", "--no-tags"]
    if branch:
        command.extend(["--branch", branch])
    command.extend([clone_url, str(checkout)])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        shutil.rmtree(target, ignore_errors=True)
        raise SkillInstallError(f"无法下载 Git Skill 来源：{error}") from error
    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        message = (result.stderr or result.stdout or "git clone failed").strip().splitlines()[-1]
        raise SkillInstallError(f"无法下载 Git Skill 来源：{message[:300]}")
    root = (checkout / relative).resolve()
    try:
        root.relative_to(checkout.resolve())
    except ValueError as error:
        shutil.rmtree(target, ignore_errors=True)
        raise SkillInstallError("Git Skill 路径不在仓库内") from error
    if not root.is_dir():
        shutil.rmtree(target, ignore_errors=True)
        raise SkillInstallError("Git 地址中的 Skill 路径不存在")
    return target, root


def _parse_git_source(source: str) -> tuple[str, str | None, str]:
    value = source.strip()
    tree_match = _GITHUB_TREE_URL.fullmatch(value.rstrip("/"))
    if tree_match:
        owner = tree_match.group("owner")
        repo = tree_match.group("repo").removesuffix(".git")
        branch = tree_match.group("branch")
        relative = tree_match.group("path") or ""
        return f"https://github.com/{owner}/{repo}.git", branch, relative
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        return f"https://github.com/{value}.git", None, ""
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value, None, ""
    if parsed.scheme in {"http", "ssh", "git"} or value.startswith("git@"):
        raise SkillInstallError("远程 Skill 只允许通过 HTTPS 下载；私有仓库请先下载到本地再检查")
    raise SkillInstallError("Git 来源须为 HTTPS 仓库 URL、GitHub owner/repo 或 GitHub tree 地址")


def _marketplace_git_fallback(skill_id: str) -> str:
    """Return the canonical repository source for one public market Skill."""

    for item in _MARKETPLACE_FALLBACK:
        if item["id"] == skill_id and item.get("fallbackGitUrl"):
            return str(item["fallbackGitUrl"])
    parts = skill_id.split("/")
    if len(parts) == 3:
        return f"https://github.com/{parts[0]}/{parts[1]}.git"
    raise SkillInstallError("市场未提供该 Skill 的可安装文件或 Git 来源")


def _marketplace_skill_root(repository: Path, skill_id: str) -> Path:
    if not _MARKETPLACE_ID.fullmatch(skill_id):
        raise SkillInstallError("市场 Skill ID 格式无效")
    slug = skill_id.rsplit("/", 1)[-1].lower()
    direct_candidates = [repository / slug, repository / "skills" / slug]
    for candidate in direct_candidates:
        if (candidate / _SKILL_FILE).is_file():
            _ensure_no_symlinks(candidate)
            return candidate
    matches = [root for root in _find_skill_roots(repository) if root.name.lower() == slug]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SkillInstallError("市场来源包含同名 Skill；请改用包含子目录的 Git 地址")
    raise SkillInstallError("Git 来源中未找到市场所选的 Skill")


def _fetch_marketplace_leaderboard(view: str, *, limit: int) -> list[dict[str, Any]]:
    path = {"all-time": "", "trending": "trending", "hot": "hot"}[view]
    url = f"https://skills.sh/{path}" if path else "https://skills.sh/"
    request = Request(url, headers={"Accept": "text/html", "User-Agent": "ScanSci/0.1 SkillManager"})
    try:
        with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed HTTPS endpoint above
            raw = response.read(_MAX_MARKETPLACE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SkillInstallError(f"无法访问 skills.sh：{error}") from error
    if len(raw) > _MAX_MARKETPLACE_BYTES:
        raise SkillInstallError("skills.sh 响应超过安全上限")
    page = raw.decode("utf-8", errors="replace")
    pattern = re.compile(
        r'\{\\"source\\":\\"(?P<source>[^"\\]+)\\",\\"skillId\\":\\"(?P<skill>[^"\\]+)\\",\\"name\\":\\"(?P<name>[^"\\]*)\\",\\"installs\\":(?P<installs>\d+)',
    )
    rows = [
        {
            "id": f"{match.group('source')}/{match.group('skill')}",
            "source": match.group("source"),
            "skillId": match.group("skill"),
            "name": match.group("name"),
            "installs": int(match.group("installs")),
            "sourceType": "github",
        }
        for match in pattern.finditer(page)
    ]
    if not rows:
        raise SkillInstallError("无法解析 skills.sh 市场目录")
    return rows[:limit]


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ScanSci/0.1 SkillManager"})
    try:
        with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed HTTPS endpoint above
            raw = response.read(_MAX_MARKETPLACE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SkillInstallError(f"无法访问 skills.sh：{error}") from error
    if len(raw) > _MAX_MARKETPLACE_BYTES:
        raise SkillInstallError("skills.sh 响应超过安全上限")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SkillInstallError("skills.sh 返回了无效数据") from error
    if not isinstance(payload, dict):
        raise SkillInstallError("skills.sh 返回了无效数据")
    return payload


def _marketplace_item(value: dict[str, Any]) -> dict[str, Any]:
    source = str(value.get("source", "") or "")
    slug = str(value.get("slug", value.get("skillId", "")) or "")
    identifier = str(value.get("id", "") or (f"{source}/{slug}" if source and slug else ""))
    if not _MARKETPLACE_ID.fullmatch(identifier):
        raise SkillInstallError("skills.sh 返回了无效的 Skill ID")
    return {
        "id": identifier,
        "slug": (slug or identifier.rsplit("/", 1)[-1])[:120],
        "name": str(value.get("name", "") or slug or identifier.rsplit("/", 1)[-1])[:160],
        "source": source[:240],
        "installs": max(0, int(value.get("installs", 0) or 0)),
        "sourceType": str(value.get("sourceType", "") or "")[:60],
        "installUrl": str(value.get("installUrl", "") or f"https://github.com/{source}")[:500],
        "url": str(value.get("url", "") or f"https://skills.sh/{source}/{slug}")[:500],
        "isDuplicate": bool(value.get("isDuplicate", False)),
    }


def _find_skill_roots(root: Path) -> list[Path]:
    if (root / _SKILL_FILE).is_file():
        _ensure_no_symlinks(root)
        return [root]
    candidates: list[Path] = []
    for path in root.rglob(_SKILL_FILE):
        if any(part in set(_IGNORED_PACKAGE_NAMES) for part in path.parts):
            continue
        if path.is_file():
            candidates.append(path.parent)
        if len(candidates) > 64:
            raise SkillInstallError("该来源包含过多 Skill；请指定一个更小的文件夹")
    if not candidates:
        raise SkillInstallError("来源中未找到 SKILL.md")
    unique = sorted(set(candidates), key=lambda item: str(item).lower())
    for candidate in unique:
        _ensure_no_symlinks(candidate)
    return unique


def _ensure_no_symlinks(root: Path) -> None:
    for item in root.rglob("*"):
        if item.is_symlink():
            raise SkillInstallError(f"Skill 不能包含符号链接：{item.name}")


def _copy_into_library(
    workspace: str | Path,
    *,
    roots: list[Path],
    source_type: str,
    source: str,
    security_scan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    library = skill_library_path(workspace)
    library.mkdir(parents=True, exist_ok=True)
    settings = load_settings(workspace)
    existing = list(settings.get("skills", []) or [])
    staged = Path(tempfile.mkdtemp(prefix=".scansci-skill-stage-", dir=library.parent))
    copied: list[tuple[Path, dict[str, Any]]] = []
    try:
        reserved = {path.name.lower() for path in library.iterdir() if path.is_dir()}
        for root in roots:
            metadata = _skill_metadata(root / _SKILL_FILE, fallback=root.name)
            folder = _unique_folder_name(_slug(metadata["id"]), reserved)
            reserved.add(folder.lower())
            destination = staged / folder
            shutil.copytree(root, destination, ignore=shutil.ignore_patterns(*_IGNORED_PACKAGE_NAMES))
            copied.append((destination, {**metadata, "folder": folder}))
        installed: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        used_ids = {str(item.get("id", "")).lower() for item in existing}
        for staged_root, metadata in copied:
            destination = library / metadata["folder"]
            if destination.exists():
                raise SkillInstallError(f"Skill 已存在：{metadata['name']}")
            staged_root.replace(destination)
            identifier = _unique_record_id(_slug(metadata["id"]), used_ids)
            used_ids.add(identifier.lower())
            record = {
                "id": identifier,
                "name": metadata["name"],
                "description": metadata["description"],
                "path": str(destination),
                "enabled": True,
                "source_type": source_type,
                "source": source,
                "installed_at": now,
                **({"security_scan": dict(security_scan)} if security_scan else {}),
            }
            existing.append(record)
            installed.append(record)
        settings["skills"] = existing
        save_settings(workspace, settings)
        return installed
    except Exception:
        # Only the staging directory is removed here.  A copied library package
        # is preserved if saving settings fails so a user never loses files.
        raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def _skill_metadata(skill_file: Path, *, fallback: str) -> dict[str, str]:
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise SkillInstallError(f"无法读取 {skill_file.name}：{error}") from error
    frontmatter = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        match = re.match(r"^\s*(name|description)\s*:\s*(.*?)\s*$", line, flags=re.IGNORECASE)
        if match:
            values[match.group(1).lower()] = match.group(2).strip().strip("\"'")
    name = values.get("name") or fallback
    description = values.get("description") or _first_heading_or_line(text)
    return {"id": name, "name": name[:100], "description": description[:400]}


def _first_heading_or_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean and clean != "---" and ":" not in clean[:40]:
            return clean
    return "Imported Skill package"


def _slug(value: str) -> str:
    candidate = _SKILL_ID.sub("-", str(value or "").strip().lower()).strip(".-_")
    return candidate[:64] or "skill"


def _unique_folder_name(base: str, reserved: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate.lower() in reserved:
        candidate = f"{base[:58]}-{suffix}"
        suffix += 1
    return candidate


def _unique_record_id(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate.lower() in used:
        candidate = f"{base[:58]}-{suffix}"
        suffix += 1
    return candidate
