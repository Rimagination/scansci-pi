"""Local Skill package installation and skills.sh marketplace access.

The manager intentionally keeps a canonical copy inside the current ScanSci
workspace.  It accepts only declarative Skill folders (``SKILL.md`` plus their
supporting files); it never executes a package during installation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
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

from .app_settings import load_settings, save_settings
from .builtin_skills import builtin_skill_asset_path


_LIBRARY_NAME = ".scansci-skills"
_SKILL_FILE = "SKILL.md"
_MAX_ARCHIVE_FILES = 2_000
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_MARKETPLACE_BYTES = 12 * 1024 * 1024
_SKILL_ID = re.compile(r"[^a-z0-9._-]+")
_MARKETPLACE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*){1,2}$", re.IGNORECASE)
_GITHUB_TREE_URL = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:tree|blob)/(?P<branch>[^/]+)(?:/(?P<path>.*))?/?$",
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
            item["available"] = (Path(path) / _SKILL_FILE).is_file()
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


def install_skill(workspace: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Install one source into the local library and register all discovered Skills."""

    source_type = str(payload.get("source_type", "") or "").strip().lower()
    source = str(payload.get("source", "") or "").strip()
    if source_type not in {"local", "git", "archive", "marketplace"}:
        raise SkillInstallError("source_type must be local, git, archive, or marketplace")
    if not source:
        raise SkillInstallError("请选择或输入 Skill 来源")

    temporary: Path | None = None
    recorded_source = source
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
        installed = _copy_into_library(workspace, roots=roots, source_type=source_type, source=recorded_source)
        settings = load_settings(workspace)
        return {"installed": installed, "skills": installed_skills(workspace), "settings": settings}
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


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
    command = ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-tags"]
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
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
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
    if parsed.scheme in {"https", "http", "ssh", "git"} and parsed.netloc:
        return value, None, ""
    if value.startswith("git@") and ":" in value:
        return value, None, ""
    raise SkillInstallError("Git 来源须为仓库 URL、GitHub owner/repo 或 GitHub tree 地址")


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
        if any(part in {".git", "node_modules", ".venv", "__pycache__"} for part in path.parts):
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
            shutil.copytree(root, destination, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
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
