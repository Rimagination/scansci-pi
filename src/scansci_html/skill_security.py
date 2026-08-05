"""Built-in, cross-platform security scanner for external Skill packages.

The scanner is intentionally static: it never imports a Skill, runs its
scripts, or follows instructions from ``SKILL.md``.  It produces a compact,
serialisable report that the installer can use as a SAFE / REVIEW / BLOCKED
gate before any package is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable


SKILL_SECURITY_VERSION = "scansci-skill-vetter/1.0"

_MAX_FILES = 2_000
_MAX_TOTAL_BYTES = 100 * 1024 * 1024
_MAX_TEXT_BYTES = 2 * 1024 * 1024
_MAX_FINDINGS = 80
_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
_TEXT_SUFFIXES = {
    "", ".bat", ".c", ".cfg", ".cmd", ".conf", ".cpp", ".css", ".csv",
    ".go", ".h", ".html", ".ini", ".java", ".js", ".json", ".jsx", ".md",
    ".mjs", ".ps1", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts",
    ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
_SCRIPT_SUFFIXES = {".bat", ".cmd", ".js", ".mjs", ".ps1", ".py", ".rb", ".sh", ".ts"}
_BINARY_EXECUTABLE_SUFFIXES = {
    ".appx", ".com", ".dll", ".dylib", ".exe", ".jar", ".msi", ".msix",
    ".node", ".pyc", ".pyo", ".scr", ".so", ".sys", ".wasm",
}
_NESTED_ARCHIVE_SUFFIXES = {".7z", ".egg", ".gz", ".rar", ".tar", ".tgz", ".whl", ".xz", ".zip"}
_SECRET_FILE_NAMES = {".env", ".env.local", "id_dsa", "id_ed25519", "id_rsa"}
_SECRET_SUFFIXES = {".key", ".p12", ".pfx"}
_PLACEHOLDER_WORDS = {
    "changeme", "dummy", "example", "fake", "placeholder", "replace-me", "sample",
    "test", "your-api-key", "your-key", "your-token",
}


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    severity: str
    title: str
    detail: str
    pattern: re.Pattern[str]


_PROMPT_RULES = (
    _Rule(
        "prompt-ignore-authority",
        "HIGH",
        "尝试覆盖上级指令",
        "Skill 指令要求忽略 system、developer 或先前指令。",
        re.compile(r"(?:\bignore\s+(?:all\s+|any\s+|the\s+)?(?:(?:previous|prior)(?:\s+(?:system|developer))?|system|developer)\s+(?:instructions?|messages?|prompts?)\b|忽略(?:所有|任何|之前|先前|系统|开发者)[^。\n]{0,24}(?:指令|消息|提示))", re.I),
    ),
    _Rule(
        "prompt-secret-exfiltration",
        "HIGH",
        "尝试获取或外传敏感信息",
        "Skill 指令要求显示、读取、发送或上传提示词、凭据或令牌。",
        re.compile(r"(?:\b(?:reveal|print|read|collect|exfiltrate|send|upload)\b.{0,60}\b(?:system prompt|developer message|api[_ -]?key|credentials?|secrets?|tokens?)\b|(?:显示|读取|收集|发送|上传|外传)[^。\n]{0,40}(?:系统提示|开发者消息|API[ _-]?Key|密钥|凭据|令牌))", re.I),
    ),
    _Rule(
        "prompt-hidden-behaviour",
        "HIGH",
        "要求向用户隐藏行为",
        "Skill 指令要求不要告知用户其真实操作。",
        re.compile(r"(?:\b(?:do not|don't|never)\s+(?:tell|inform|show|warn)\s+(?:the\s+)?user\b|(?:不要|不得|绝不)(?:告诉|告知|展示|警告)用户)", re.I),
    ),
    _Rule(
        "prompt-disable-safety",
        "HIGH",
        "尝试禁用安全控制",
        "Skill 指令要求绕过或关闭安全、审批、沙箱或扫描器。",
        re.compile(r"(?:\b(?:disable|bypass|evade|turn off)\b.{0,45}\b(?:security|safety|approval|sandbox|scanner|antivirus|guardrail)\b|(?:关闭|禁用|绕过|逃避)[^。\n]{0,30}(?:安全|审批|沙箱|扫描器|杀毒|护栏))", re.I),
    ),
)

_CODE_RULES = (
    _Rule(
        "code-download-pipe-shell",
        "HIGH",
        "下载内容后直接执行",
        "脚本把网络下载结果直接传给 shell 或 PowerShell。",
        re.compile(r"(?:curl|wget|irm|invoke-webrequest)[^\n|]{0,240}\|\s*(?:bash|sh|zsh|powershell|pwsh|iex|invoke-expression)\b", re.I),
    ),
    _Rule(
        "code-powershell-obfuscation",
        "HIGH",
        "PowerShell 混淆执行",
        "脚本使用 EncodedCommand 或 Invoke-Expression 执行动态内容。",
        re.compile(r"(?:-e(?:ncodedcommand)?\s+[A-Za-z0-9+/=]{20,}|\b(?:iex|invoke-expression)\s*(?:\(|\s))", re.I),
    ),
    _Rule(
        "code-destructive-root",
        "CRITICAL",
        "可能破坏系统或用户目录",
        "脚本包含面向根目录、主目录或系统盘的递归删除/格式化命令。",
        re.compile(r"(?:rm\s+-[a-z]*r[a-z]*f[a-z]*\s+(?:/|~|\$HOME)(?:\s|$)|remove-item\b[^\n]{0,180}-(?:recurse|r)\b[^\n]{0,120}(?:[A-Za-z]:\\|\$env:home|\$home)(?:\s|$)|(?m:^\s*(?:format(?:\.com)?|diskpart)\b))", re.I),
    ),
    _Rule(
        "code-persistence",
        "HIGH",
        "尝试建立系统持久化",
        "脚本修改启动项、计划任务、服务或登录配置。",
        re.compile(r"\b(?:schtasks\s+/create|new-scheduledtask|sc\.exe\s+create|systemctl\s+enable|crontab\s+-|currentversion\\run|launchagents?)\b", re.I),
    ),
    _Rule(
        "code-credential-access",
        "HIGH",
        "尝试读取本机凭据",
        "脚本访问浏览器、SSH、云凭据或系统凭据存储。",
        re.compile(r"(?:\.ssh[/\\](?:id_rsa|id_ed25519)|\.aws[/\\]credentials|login data|keychain|credential manager|security\s+find-generic-password)", re.I),
    ),
    _Rule(
        "code-shell-true",
        "MEDIUM",
        "使用不受约束的 shell 执行",
        "脚本通过 shell=True 执行命令，需要人工确认命令边界。",
        re.compile(r"\b(?:subprocess\.(?:run|popen|call|check_call|check_output)|popen)\s*\([^\n]{0,500}\bshell\s*=\s*true", re.I),
    ),
    _Rule(
        "code-dynamic-eval",
        "MEDIUM",
        "动态执行代码",
        "脚本使用 eval、exec 或动态子进程执行，需要人工检查输入来源。",
        re.compile(r"(?:\b(?:eval|exec)\s*\(|\bos\.system\s*\(|\bchild_process\.(?:exec|execSync)\s*\()", re.I),
    ),
    _Rule(
        "code-process-launch",
        "MEDIUM",
        "启动外部进程",
        "脚本会启动本机命令或子进程，需要确认参数和可执行文件边界。",
        re.compile(r"(?:\bsubprocess\.(?:run|popen|call|check_call|check_output)\s*\(|\bchild_process\.(?:spawn|spawnSync)\s*\(|\bstart-process\b)", re.I),
    ),
    _Rule(
        "code-network-access",
        "LOW",
        "包含网络访问代码",
        "Skill 脚本包含网络请求能力；运行时仍应遵守 ScanSci 的联网权限。",
        re.compile(r"(?:\brequests\.(?:get|post|put|patch|delete)\s*\(|\burlopen\s*\(|\bfetch\s*\(|\binvoke-webrequest\b|\bcurl\s+https?://|\bwget\s+https?://)", re.I),
    ),
)

_SECRET_RULES = (
    _Rule(
        "secret-private-key",
        "CRITICAL",
        "包含私钥材料",
        "文件包含 PEM 私钥头。",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    _Rule(
        "secret-openai-key",
        "HIGH",
        "疑似 OpenAI API Key",
        "检测到类似 OpenAI API Key 的长令牌。",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ),
    _Rule(
        "secret-github-token",
        "HIGH",
        "疑似 GitHub Token",
        "检测到类似 GitHub 访问令牌的值。",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ),
    _Rule(
        "secret-aws-key",
        "HIGH",
        "疑似 AWS Access Key",
        "检测到类似 AWS Access Key ID 的值。",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    _Rule(
        "secret-google-key",
        "HIGH",
        "疑似 Google API Key",
        "检测到类似 Google API Key 的值。",
        re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    ),
    _Rule(
        "secret-slack-token",
        "HIGH",
        "疑似 Slack Token",
        "检测到类似 Slack 访问令牌的值。",
        re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    ),
)

_GENERIC_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*['\"]([^'\"\r\n]{16,})['\"]"
)
_LONG_BASE64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{240,}={0,2}(?![A-Za-z0-9+/])")


def scan_skill_packages(
    packages: Iterable[Path],
    *,
    source_type: str,
    source: str,
) -> dict[str, Any]:
    """Scan exact package snapshots and return a serialisable verdict report."""

    roots = [Path(item).resolve() for item in packages]
    findings: list[dict[str, Any]] = []
    package_rows: list[dict[str, Any]] = []
    fingerprint = hashlib.sha256()
    all_files: list[tuple[Path, Path]] = []
    total_bytes = 0

    if re.match(r"^(?:http|git)://", str(source or "").strip(), flags=re.I):
        _add_finding(findings, "structure-check", "source-insecure-transport", "MEDIUM", "来源传输未加密", "HTTP 或 git:// 来源缺少传输加密，无法确认下载过程未被篡改。", "")

    for package_index, root in enumerate(roots, start=1):
        if not root.is_dir():
            _add_finding(findings, "structure-check", "structure-missing-root", "HIGH", "Skill 目录不存在", "隔离快照中的 Skill 目录缺失。", f"package-{package_index}")
            continue
        skill_file = root / "SKILL.md"
        if not skill_file.is_file():
            _add_finding(findings, "structure-check", "structure-missing-skill", "HIGH", "缺少 SKILL.md", "Skill 包必须包含 SKILL.md。", root.name)
        else:
            _scan_skill_manifest(skill_file, f"{root.name}/SKILL.md", findings)
        files = sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix().lower())
        package_bytes = 0
        for path in files:
            relative = path.relative_to(root)
            display_path = f"{root.name}/{relative.as_posix()}"
            if path.is_symlink():
                _add_finding(findings, "structure-check", "structure-symlink", "HIGH", "包含符号链接", "Skill 包不能包含可跳出目录边界的符号链接。", display_path)
                continue
            size = path.stat().st_size
            package_bytes += size
            total_bytes += size
            all_files.append((root, path))
            fingerprint.update(f"{package_index}:{relative.as_posix()}:{size}\0".encode("utf-8"))
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    fingerprint.update(chunk)
            _scan_structure_file(path, display_path, findings)
        package_rows.append({"name": root.name, "file_count": len(files), "byte_count": package_bytes})

    if len(all_files) > _MAX_FILES:
        _add_finding(findings, "structure-check", "structure-too-many-files", "HIGH", "文件数量超过安全上限", f"Skill 包包含 {len(all_files)} 个文件，安全上限为 {_MAX_FILES}。", "")
    if total_bytes > _MAX_TOTAL_BYTES:
        _add_finding(findings, "structure-check", "structure-too-large", "HIGH", "Skill 包体积超过安全上限", f"Skill 包总大小超过 {_MAX_TOTAL_BYTES // (1024 * 1024)} MB。", "")

    for root, path in all_files:
        if len(findings) >= _MAX_FINDINGS:
            break
        relative = f"{root.name}/{path.relative_to(root).as_posix()}"
        text = _read_text(path)
        if text is None:
            continue
        _scan_secrets(text, relative, findings)
        if path.name.upper() == "SKILL.MD" or path.suffix.lower() in {".md", ".txt"}:
            _scan_prompt_instructions(text, relative, findings)
        if path.name.upper() == "SKILL.MD" or path.suffix.lower() in _SCRIPT_SUFFIXES:
            _scan_code(text, relative, findings)
        _scan_obfuscation(text, relative, findings)

    findings.sort(key=lambda item: (-_SEVERITY_RANK[item["severity"]], item["path"], item.get("line", 0), item["rule_id"]))
    findings = findings[:_MAX_FINDINGS]
    highest = max((_SEVERITY_RANK[item["severity"]] for item in findings), default=0)
    verdict = "BLOCKED" if highest >= _SEVERITY_RANK["HIGH"] else "REVIEW" if highest >= _SEVERITY_RANK["MEDIUM"] else "SAFE"
    counts = {severity.lower(): sum(1 for item in findings if item["severity"] == severity) for severity in _SEVERITY_RANK}
    scanners = [_scanner_row(scanner, findings) for scanner in ("structure-check", "prompt-safety", "code-safety", "secrets-scan")]
    recommendation = {
        "SAFE": "未发现阻断项。确认来源与能力范围后可以安装。",
        "REVIEW": "发现需要人工判断的风险。请阅读全部发现并明确确认后再安装。",
        "BLOCKED": "发现高风险或严重问题，ScanSci 已阻止安装。",
    }[verdict]
    return {
        "version": SKILL_SECURITY_VERSION,
        "verdict": verdict,
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_type": str(source_type),
        "source_label": _safe_source_label(source),
        "fingerprint": f"sha256:{fingerprint.hexdigest()}",
        "package_count": len(package_rows),
        "file_count": len(all_files),
        "byte_count": total_bytes,
        "packages": package_rows,
        "counts": counts,
        "scanners": scanners,
        "findings": findings,
        "install_allowed": verdict != "BLOCKED",
        "requires_risk_acknowledgement": verdict == "REVIEW",
        "recommendation": recommendation,
    }


def _scan_structure_file(path: Path, display_path: str, findings: list[dict[str, Any]]) -> None:
    suffix = path.suffix.lower()
    lowered_name = path.name.lower()
    if path.stat().st_size > _MAX_TEXT_BYTES and (suffix in _SCRIPT_SUFFIXES or path.name.upper() == "SKILL.MD"):
        _add_finding(findings, "code-safety", "code-unscannable-large-file", "MEDIUM", "脚本文件过大，无法完整静态检查", "超过单文件静态分析上限的脚本需要人工审查。", display_path)
    if suffix in _BINARY_EXECUTABLE_SUFFIXES:
        _add_finding(findings, "structure-check", "structure-executable", "HIGH", "包含可执行二进制文件", "外部 Skill 不应携带预编译可执行文件或动态库。", display_path)
    if suffix in _NESTED_ARCHIVE_SUFFIXES:
        _add_finding(findings, "structure-check", "structure-nested-archive", "MEDIUM", "包含嵌套压缩包", "嵌套压缩包无法作为普通文本进行完整审查。", display_path)
    if lowered_name in _SECRET_FILE_NAMES or suffix in _SECRET_SUFFIXES:
        _add_finding(findings, "secrets-scan", "secret-sensitive-file", "HIGH", "包含敏感凭据文件", "Skill 包包含常见密钥或环境变量文件。", display_path)


def _scan_skill_manifest(path: Path, display_path: str, findings: list[dict[str, Any]]) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _add_finding(findings, "structure-check", "structure-unreadable-skill", "HIGH", "无法读取 SKILL.md", "Skill 主说明文件不可读。", display_path)
        return
    if not text.startswith("---"):
        _add_finding(findings, "structure-check", "structure-missing-frontmatter", "MEDIUM", "SKILL.md 缺少元数据区", "缺少 YAML frontmatter，无法可靠确认 Skill 名称与用途。", display_path, 1)
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        _add_finding(findings, "structure-check", "structure-malformed-frontmatter", "MEDIUM", "SKILL.md 元数据区未闭合", "YAML frontmatter 缺少结束分隔符。", display_path, 1)
        return
    frontmatter = parts[1]
    name_match = re.search(r"(?mi)^\s*name\s*:\s*(.+?)\s*$", frontmatter)
    if not name_match or not name_match.group(1).strip(" '\""):
        _add_finding(findings, "structure-check", "structure-missing-name", "MEDIUM", "SKILL.md 缺少名称", "YAML frontmatter 必须包含非空 name。", display_path, 1)


def _scan_prompt_instructions(text: str, path: str, findings: list[dict[str, Any]]) -> None:
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        documentary = _is_security_documentation(line)
        for rule in _PROMPT_RULES:
            match = rule.pattern.search(line)
            if match:
                if documentary:
                    _add_finding(
                        findings,
                        "prompt-safety",
                        rule.rule_id,
                        "MEDIUM",
                        f"文档中出现高风险指令模式：{rule.title}",
                        "该文本看起来像安全说明或示例，但仍需要人工确认它不会成为 Agent 指令。",
                        path,
                        line_number,
                        match.group(0),
                    )
                else:
                    _add_rule_finding(findings, "prompt-safety", rule, path, line_number, match.group(0))


def _scan_code(text: str, path: str, findings: list[dict[str, Any]]) -> None:
    for rule in _CODE_RULES:
        match = rule.pattern.search(text)
        if match:
            line_number = text.count("\n", 0, match.start()) + 1
            _add_rule_finding(findings, "code-safety", rule, path, line_number, match.group(0))


def _scan_secrets(text: str, path: str, findings: list[dict[str, Any]]) -> None:
    for rule in _SECRET_RULES:
        match = rule.pattern.search(text)
        if match and not _looks_like_placeholder(match.group(0)):
            line_number = text.count("\n", 0, match.start()) + 1
            _add_finding(findings, "secrets-scan", rule.rule_id, rule.severity, rule.title, rule.detail, path, line_number, "[REDACTED]")
    for match in _GENERIC_SECRET.finditer(text):
        value = match.group(1)
        if _looks_like_placeholder(value):
            continue
        line_number = text.count("\n", 0, match.start()) + 1
        _add_finding(findings, "secrets-scan", "secret-generic-assignment", "HIGH", "疑似硬编码凭据", "检测到直接写入文件的长凭据值。", path, line_number, "[REDACTED]")


def _scan_obfuscation(text: str, path: str, findings: list[dict[str, Any]]) -> None:
    match = _LONG_BASE64.search(text)
    if match:
        line_number = text.count("\n", 0, match.start()) + 1
        _add_finding(findings, "code-safety", "code-long-base64", "MEDIUM", "包含长 Base64 数据", "长编码数据可能隐藏脚本、提示注入或二进制内容，需要人工检查。", path, line_number, "[ENCODED DATA REDACTED]")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if len(line) > 8_000:
            _add_finding(findings, "code-safety", "code-oversized-line", "MEDIUM", "包含异常超长文本行", "异常超长行可能用于隐藏或混淆内容。", path, line_number)
            break


def _read_text(path: Path) -> str | None:
    if path.stat().st_size > _MAX_TEXT_BYTES:
        return None
    if path.suffix.lower() not in _TEXT_SUFFIXES and path.name.upper() != "SKILL.MD":
        return None
    raw = path.read_bytes()
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def _is_security_documentation(line: str) -> bool:
    lowered = line.lower()
    documentary = ("detect", "flag", "malicious", "example", "pattern", "检测", "扫描", "恶意", "示例", "规则")
    return any(word in lowered for word in documentary)


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return any(word in lowered for word in _PLACEHOLDER_WORDS) or set(lowered) <= {"x", "-", "_", "*"}


def _safe_source_label(source: str) -> str:
    value = str(source or "").strip()
    if len(value) <= 240:
        return value
    return value[:117] + "…" + value[-117:]


def _scanner_row(scanner: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in findings if item["scanner"] == scanner]
    highest = max((_SEVERITY_RANK[item["severity"]] for item in rows), default=0)
    status = "FAIL" if highest >= _SEVERITY_RANK["HIGH"] else "WARN" if highest >= _SEVERITY_RANK["MEDIUM"] else "PASS"
    labels = {
        "structure-check": "结构与文件边界",
        "prompt-safety": "提示注入与越权指令",
        "code-safety": "危险代码与混淆",
        "secrets-scan": "密钥与敏感信息",
    }
    return {"id": scanner, "name": labels[scanner], "status": status, "finding_count": len(rows)}


def _add_rule_finding(
    findings: list[dict[str, Any]],
    scanner: str,
    rule: _Rule,
    path: str,
    line: int,
    evidence: str,
) -> None:
    _add_finding(findings, scanner, rule.rule_id, rule.severity, rule.title, rule.detail, path, line, evidence)


def _add_finding(
    findings: list[dict[str, Any]],
    scanner: str,
    rule_id: str,
    severity: str,
    title: str,
    detail: str,
    path: str,
    line: int | None = None,
    evidence: str = "",
) -> None:
    if len(findings) >= _MAX_FINDINGS:
        return
    key = (scanner, rule_id, path, line or 0)
    if any((item["scanner"], item["rule_id"], item["path"], item.get("line", 0)) == key for item in findings):
        return
    clean_evidence = re.sub(r"\s+", " ", evidence).strip()
    findings.append(
        {
            "id": f"finding-{len(findings) + 1}",
            "scanner": scanner,
            "rule_id": rule_id,
            "severity": severity,
            "title": title,
            "detail": detail,
            "path": path,
            **({"line": int(line)} if line else {}),
            **({"evidence": clean_evidence[:180]} if clean_evidence else {}),
        }
    )
