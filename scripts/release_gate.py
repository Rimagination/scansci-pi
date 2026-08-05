"""Run ScanSci's staged source and Windows release acceptance gates.

The gate deliberately separates automated evidence from desktop visual evidence.
It never reads or prints provider secrets, never reuses an anonymous ``dist``
directory, and can resume an already-built release without rebuilding it.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import socket
import subprocess
import sys
from threading import Thread
import time
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_RUNTIME_FORBIDDEN_SEGMENTS = frozenset({"torch", "transformers", "sentence_transformers", "tensorflow", "models--"})


class GateFailure(RuntimeError):
    """A mandatory acceptance gate failed."""


class GatePending(RuntimeError):
    """Automated gates passed but human desktop evidence is still missing."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _emit_console(
    value: object = "",
    *,
    end: str = "\n",
    file: Any | None = None,
    encoding: str | None = None,
) -> None:
    """Write diagnostic output without letting a Windows console codepage abort a gate.

    Subprocess output and release titles may contain Unicode outside a legacy
    GBK console. The complete UTF-8 log remains the source of truth; the
    console receives an escaped representation for characters it cannot show.
    """

    stream = file or sys.stdout
    target_encoding = encoding or getattr(stream, "encoding", None) or "utf-8"
    text = str(value)
    try:
        safe_text = text.encode(target_encoding, errors="backslashreplace").decode(target_encoding, errors="replace")
    except LookupError:
        safe_text = text
    print(safe_text, end=end, file=stream)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprint() -> str:
    """Hash release-relevant source without build outputs or user data."""

    files: set[Path] = set()
    # The desktop client and its managed Worker are released as one service
    # contract. A gateway change must invalidate an otherwise reusable
    # desktop release candidate.
    for directory in ("src", "scripts", "tests", "config", "installer", "services"):
        root = PROJECT_ROOT / directory
        if root.is_dir():
            files.update(path for path in root.rglob("*") if path.is_file())
    for name in ("pyproject.toml", "requirements.txt", "package.json", "package-lock.json"):
        path = PROJECT_ROOT / name
        if path.is_file():
            files.add(path)
    digest = hashlib.sha256()
    for path in sorted(
        (path for path in files if "__pycache__" not in path.parts and path.suffix != ".pyc"),
        key=lambda item: item.relative_to(PROJECT_ROOT).as_posix(),
    ):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _resolve_from_root(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def validate_release_inputs(contract: dict[str, Any], scope: dict[str, Any]) -> None:
    if int(contract.get("schema_version", 0)) != 1:
        raise GateFailure("release-gate.json schema_version must be 1")
    if not str(contract.get("version", "")).strip():
        raise GateFailure("release-gate.json must define version")
    if int(scope.get("schema_version", 0)) != 1:
        raise GateFailure("release-scope.json schema_version must be 1")
    if not str(scope.get("p0_objective", "")).strip():
        raise GateFailure("release-scope.json must contain exactly one non-empty p0_objective")
    acceptance = list(scope.get("acceptance", []) or [])
    non_goals = list(scope.get("non_goals", []) or [])
    if not acceptance or not non_goals:
        raise GateFailure("release-scope.json requires non-empty acceptance and non_goals")
    acceptance_ids = [str(item.get("id", "")).strip() for item in acceptance]
    if any(not item for item in acceptance_ids) or len(set(acceptance_ids)) != len(acceptance_ids):
        raise GateFailure("release-scope.json acceptance ids must be non-empty and unique")
    command_ids: list[str] = []
    for group in ("targeted_commands", "full_commands", "real_verifications"):
        for item in list(contract.get(group, []) or []):
            step_id = str(item.get("id", "")).strip()
            command = list(item.get("command", []) or [])
            if not step_id or not command or not all(isinstance(part, str) and part for part in command):
                raise GateFailure(f"{group} entries require a non-empty id and command array")
            retry = item.get("retry", {})
            if retry is not None and not isinstance(retry, dict):
                raise GateFailure(f"{group} retry configuration must be an object")
            if isinstance(retry, dict) and retry:
                try:
                    max_attempts = int(retry.get("max_attempts", 1))
                    delay_seconds = float(retry.get("delay_seconds", 0))
                except (TypeError, ValueError) as error:
                    raise GateFailure(f"{group} retry configuration must use numeric limits") from error
                if not 1 <= max_attempts <= 3:
                    raise GateFailure(f"{group} retry max_attempts must be between 1 and 3")
                if not 0 <= delay_seconds <= 120:
                    raise GateFailure(f"{group} retry delay_seconds must be between 0 and 120")
                if not str(retry.get("failure_reason", "")).strip():
                    raise GateFailure(f"{group} retry configuration must name one failure_reason")
            timeout_seconds = item.get("timeout_seconds")
            if timeout_seconds is not None:
                try:
                    timeout_value = float(timeout_seconds)
                except (TypeError, ValueError) as error:
                    raise GateFailure(f"{group} timeout_seconds must be numeric") from error
                if not 15 <= timeout_value <= 1_800:
                    raise GateFailure(f"{group} timeout_seconds must be between 15 and 1800")
            command_ids.append(step_id)
    if len(set(command_ids)) != len(command_ids):
        raise GateFailure("release gate command ids must be unique")
    visual = dict(contract.get("visual_acceptance", {}) or {})
    if not list(visual.get("required_checks", []) or []) or not list(visual.get("required_screenshots", []) or []):
        raise GateFailure("visual_acceptance must define required checks and screenshots")
    package = dict(contract.get("package", {}) or {})
    if "signature_required" in package and not isinstance(package["signature_required"], bool):
        raise GateFailure("package signature_required must be a boolean")
    runtime_manifest_url = str(package.get("runtime_manifest_url", "")).strip()
    if runtime_manifest_url and urlparse(runtime_manifest_url).scheme.lower() != "https":
        raise GateFailure("package runtime_manifest_url must use HTTPS")
    update_manifest_url = str(package.get("update_manifest_url", "")).strip()
    if update_manifest_url and urlparse(update_manifest_url).scheme.lower() != "https":
        raise GateFailure("package update_manifest_url must use HTTPS")


def _template_command(parts: list[str], variables: dict[str, str]) -> list[str]:
    rendered: list[str] = []
    for part in parts:
        value = part
        for key, replacement in variables.items():
            value = value.replace("{" + key + "}", replacement)
        rendered.append(value)
    return rendered


def _find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _find_sign_tool() -> Path | None:
    """Find the Windows SDK signer without recording machine-specific paths."""

    direct = shutil.which("signtool.exe") or shutil.which("signtool")
    if direct:
        candidate = Path(direct)
        if candidate.is_file():
            return candidate
    kit_roots = [
        Path(value) / "Windows Kits" / "10" / "bin"
        for value in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"))
        if value
    ]
    for kit_root in kit_roots:
        if not kit_root.is_dir():
            continue
        try:
            versions = sorted((path for path in kit_root.iterdir() if path.is_dir()), reverse=True)
        except OSError:
            continue
        for version in versions:
            candidate = version / "x64" / "signtool.exe"
            if candidate.is_file():
                return candidate
    return None


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class ReleaseGate:
    def __init__(
        self,
        *,
        contract_path: Path,
        scope_path: Path,
        profile: str,
        knowledge_source: Path,
        output_root: Path,
        build_id: str,
        resume_report: Path | None = None,
        promote_report: Path | None = None,
        visual_evidence_dir: Path | None = None,
    ) -> None:
        self.contract_path = contract_path
        self.scope_path = scope_path
        self.contract = _read_json(contract_path)
        self.scope = _read_json(scope_path)
        validate_release_inputs(self.contract, self.scope)
        self.profile = profile
        self.knowledge_source = knowledge_source
        self.contract_sha256 = _sha256(contract_path)
        self.scope_sha256 = _sha256(scope_path)
        self.source_sha256 = _source_fingerprint()
        self.resumed = resume_report is not None

        if resume_report is not None:
            self.report_path = resume_report.resolve()
            self.report = _read_json(self.report_path)
            if str(self.report.get("contract_sha256")) != self.contract_sha256:
                raise GateFailure("The release contract changed; start a new build instead of resuming stale evidence")
            if str(self.report.get("scope_sha256")) != self.scope_sha256:
                raise GateFailure("The P0 scope changed; start a new build instead of resuming stale evidence")
            if str(self.report.get("source_sha256")) != self.source_sha256:
                raise GateFailure("Release-relevant source changed; start a new gate instead of resuming stale evidence")
            if str(self.report.get("profile")) != profile:
                raise GateFailure("A report can only be resumed with its original profile")
            self.build_id = str(self.report["build_id"])
            self.release_dir = Path(str(self.report["release_dir"])).resolve()
            self.diagnostics_dir = self.release_dir / "diagnostics"
        else:
            self.build_id = build_id
            version = str(self.contract["version"])
            self.release_dir = (output_root / f"{version}+{build_id}").resolve()
            self.report_path = self.release_dir / "release-report.json"
            if self.report_path.exists():
                raise GateFailure(f"Release report already exists; use --resume-report: {self.report_path}")
            self.diagnostics_dir = self.release_dir / "diagnostics"
            self.report = {
                "schema_version": 1,
                "product": str(self.contract.get("product", "ScanSci")),
                "version": version,
                "build_id": build_id,
                "profile": profile,
                "status": "running",
                "started_at": _utc_now(),
                "finished_at": None,
                "repo_root": str(PROJECT_ROOT),
                "release_dir": str(self.release_dir),
                "contract_file": str(contract_path),
                "contract_sha256": self.contract_sha256,
                "scope_file": str(scope_path),
                "scope_sha256": self.scope_sha256,
                "source_sha256": self.source_sha256,
                "knowledge_source": str(knowledge_source),
                "steps": [],
                "artifacts": {},
            }
        self.visual_evidence_dir = (visual_evidence_dir or self.release_dir / "visual-evidence").resolve()
        self.release_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        if promote_report is not None:
            self._promote_from(promote_report.resolve())
        self._persist()

    def _promote_from(self, source_report_path: Path) -> None:
        source = _read_json(source_report_path)
        source_profile = str(source.get("profile", ""))
        rank = {"targeted": 0, "source": 1, "beta": 2, "release": 3}
        if str(source.get("status")) != "passed":
            raise GateFailure("Only a passed report can be promoted")
        if source_profile not in rank or rank[source_profile] >= rank[self.profile]:
            raise GateFailure("Promotion requires a passed lower-profile report")
        for field, expected in (
            ("contract_sha256", self.contract_sha256),
            ("scope_sha256", self.scope_sha256),
            ("source_sha256", self.source_sha256),
        ):
            if str(source.get(field, "")) != expected:
                raise GateFailure(f"Cannot promote because {field} changed")
        allowed = {"scope-contract"}
        allowed.update(str(item["id"]) for item in list(self.contract.get("targeted_commands", []) or []))
        if source_profile in {"source", "beta", "release"}:
            for group in ("full_commands", "real_verifications"):
                allowed.update(str(item["id"]) for item in list(self.contract.get(group, []) or []))
        imported = [
            dict(step)
            for step in list(source.get("steps", []) or [])
            if step.get("id") in allowed and step.get("status") == "passed"
        ]
        source_diagnostics = Path(str(source.get("release_dir", source_report_path.parent))).resolve() / "diagnostics"
        if source_diagnostics.is_dir():
            for source_file in source_diagnostics.rglob("*"):
                if not source_file.is_file():
                    continue
                target = self.diagnostics_dir / source_file.relative_to(source_diagnostics)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target)
        self.report["steps"] = imported
        self.report["promoted_from"] = {
            "report": str(source_report_path),
            "profile": source_profile,
            "step_ids": [str(step["id"]) for step in imported],
        }

    def _persist(self) -> None:
        _write_json(self.report_path, self.report)

    def _previous(self, step_id: str) -> dict[str, Any] | None:
        for item in reversed(list(self.report.get("steps", []) or [])):
            if item.get("id") == step_id:
                return item
        return None

    def _record(self, step: dict[str, Any]) -> None:
        steps = [item for item in list(self.report.get("steps", []) or []) if item.get("id") != step["id"]]
        steps.append(step)
        self.report["steps"] = steps
        self._persist()

    def internal_step(self, step_id: str, title: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        previous = self._previous(step_id)
        if previous and previous.get("status") == "passed":
            _emit_console(f"[reuse] {title}")
            return previous
        _emit_console(f"[gate] {title}")
        started = time.monotonic()
        step = {"id": step_id, "title": title, "status": "running", "started_at": _utc_now()}
        self._record(step)
        try:
            details = action()
        except GatePending:
            step.update(status="pending", finished_at=_utc_now(), duration_seconds=round(time.monotonic() - started, 2))
            self._record(step)
            raise
        except Exception as error:
            step.update(
                status="failed",
                finished_at=_utc_now(),
                duration_seconds=round(time.monotonic() - started, 2),
                error=str(error),
            )
            self._record(step)
            raise GateFailure(f"{title}: {error}") from error
        step.update(
            status="passed",
            finished_at=_utc_now(),
            duration_seconds=round(time.monotonic() - started, 2),
            details=details,
        )
        self._record(step)
        return step

    def command_step(
        self,
        *,
        step_id: str,
        title: str,
        command: list[str],
        required_result: Path | None = None,
        echo_output: bool = True,
        retry: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        previous = self._previous(step_id)
        if previous and previous.get("status") == "passed" and (required_result is None or required_result.is_file()):
            _emit_console(f"[reuse] {title}")
            return previous
        log_path = self.diagnostics_dir / f"{step_id}.log"
        _emit_console(f"[run] {title}")
        _emit_console("      " + subprocess.list2cmdline(command))
        started = time.monotonic()
        step = {
            "id": step_id,
            "title": title,
            "status": "running",
            "started_at": _utc_now(),
            "command": command,
            "log": str(log_path),
        }
        self._record(step)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        retry = dict(retry or {})
        max_attempts = max(1, int(retry.get("max_attempts", 1) or 1))
        retry_delay_seconds = max(0.0, float(retry.get("delay_seconds", 0) or 0))
        retry_failure_reason = str(retry.get("failure_reason", "")).strip()
        command_timeout = float(timeout_seconds) if timeout_seconds is not None else None
        attempts: list[dict[str, Any]] = []
        exit_code = 1
        try:
            with log_path.open("w", encoding="utf-8") as log:
                for attempt_number in range(1, max_attempts + 1):
                    attempt_started = time.monotonic()
                    if attempt_number > 1:
                        log.write(f"\n[retry] attempt {attempt_number}/{max_attempts}\n")
                    process = subprocess.Popen(
                        command,
                        cwd=PROJECT_ROOT,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    assert process.stdout is not None
                    output_queue: Queue[str] = Queue()

                    def drain_output() -> None:
                        for line in process.stdout:
                            output_queue.put(line)

                    output_thread = Thread(target=drain_output, daemon=True)
                    output_thread.start()
                    timed_out = False
                    deadline = (
                        time.monotonic() + command_timeout
                        if command_timeout is not None
                        else None
                    )
                    while process.poll() is None:
                        try:
                            line = output_queue.get(timeout=0.1)
                        except Empty:
                            if deadline is not None and time.monotonic() >= deadline:
                                timed_out = True
                                process.kill()
                                break
                            continue
                        if echo_output:
                            _emit_console(line, end="")
                        log.write(line)
                    exit_code = process.wait()
                    output_thread.join(timeout=1.0)
                    while not output_queue.empty():
                        line = output_queue.get_nowait()
                        if echo_output:
                            _emit_console(line, end="")
                        log.write(line)
                    if timed_out:
                        exit_code = 124
                        timeout_message = (
                            f"[timeout] {title}: exceeded {command_timeout:g}s; "
                            "terminated the verification process\n"
                        )
                        _emit_console(timeout_message, end="")
                        log.write(timeout_message)
                    failure_reason = ""
                    if timed_out:
                        failure_reason = "command_timeout"
                    elif required_result is not None and required_result.is_file():
                        try:
                            result_text = required_result.read_text(encoding="utf-8-sig")
                            if retry_failure_reason and retry_failure_reason in result_text:
                                failure_reason = retry_failure_reason
                        except OSError:
                            pass
                    attempts.append(
                        {
                            "attempt": attempt_number,
                            "exit_code": exit_code,
                            "duration_seconds": round(time.monotonic() - attempt_started, 2),
                            **({"timeout_seconds": command_timeout} if command_timeout is not None else {}),
                            **({"failure_reason": failure_reason} if failure_reason else {}),
                        }
                    )
                    if exit_code == 0:
                        break
                    if (
                        attempt_number < max_attempts
                        and retry_failure_reason
                        and failure_reason == retry_failure_reason
                    ):
                        message = (
                            f"[retry] {title}: {retry_failure_reason}; "
                            f"waiting {retry_delay_seconds:g}s before retry {attempt_number + 1}/{max_attempts}\n"
                        )
                        _emit_console(message, end="")
                        log.write(message)
                        time.sleep(retry_delay_seconds)
                        continue
                    break
        except Exception as error:
            step.update(status="failed", finished_at=_utc_now(), error=str(error))
            self._record(step)
            raise GateFailure(f"{title}: {error}") from error
        step.update(
            status="passed" if exit_code == 0 else "failed",
            exit_code=exit_code,
            finished_at=_utc_now(),
            duration_seconds=round(time.monotonic() - started, 2),
            attempts=attempts,
        )
        if exit_code != 0:
            # Keep the final report useful without making a reviewer inspect
            # every nested attempt record.  The detailed attempt list remains
            # the source of timing and retry evidence.
            final_failure_reason = next(
                (
                    str(attempt.get("failure_reason", "")).strip()
                    for attempt in reversed(attempts)
                    if str(attempt.get("failure_reason", "")).strip()
                ),
                "",
            )
            if final_failure_reason:
                step["failure_reason"] = final_failure_reason
        if required_result is not None:
            step["result_file"] = str(required_result)
            if exit_code == 0 and not required_result.is_file():
                step["status"] = "failed"
                step["error"] = "Command returned success but its required result file is missing"
        self._record(step)
        if step["status"] != "passed":
            raise GateFailure(f"{title} failed; see {log_path}")
        if not echo_output:
            _emit_console(f"[ok] {title} ({step['duration_seconds']}s; log: {log_path})")
        return step

    def _variables(self) -> dict[str, str]:
        return {
            "python": sys.executable,
            "project_root": str(PROJECT_ROOT),
            "diagnostics": str(self.diagnostics_dir),
            "knowledge_source": str(self.knowledge_source),
        }

    def run_configured_commands(self, group: str) -> None:
        variables = self._variables()
        for item in list(self.contract.get(group, []) or []):
            required_result = None
            if item.get("result_file"):
                required_result = self.diagnostics_dir / str(item["result_file"])
            self.command_step(
                step_id=str(item["id"]),
                title=str(item["title"]),
                command=_template_command(list(item["command"]), variables),
                required_result=required_result,
                echo_output=str(item.get("console", "stream")) != "log",
                retry=dict(item.get("retry", {}) or {}),
                timeout_seconds=(float(item["timeout_seconds"]) if item.get("timeout_seconds") is not None else None),
            )

    @property
    def package_staging_root(self) -> Path:
        """Return a short, deterministic staging root for Windows onedir builds.

        PyInstaller preserves package-internal paths.  A delivery directory such
        as ``internal-beta-releases/<version>+<build-id>/ScanSci`` can therefore
        push otherwise valid LiteLLM resources beyond Windows' traditional
        MAX_PATH limit during ``COLLECT``.  The onedir tree is only an input to
        installer creation and runtime verification, so stage it below a short
        project-local build path while keeping the installer and release report
        in the auditable release directory.
        """

        material = f"{self.release_dir.resolve()}\0{self.build_id}"
        token = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        return PROJECT_ROOT / "build" / "p" / token

    @property
    def package_dir(self) -> Path:
        return self.package_staging_root / str(self.contract["package"]["name"])

    @property
    def executable(self) -> Path:
        return self.package_dir / f"{self.contract['package']['name']}.exe"

    @property
    def installer_dir(self) -> Path:
        return self.release_dir / "installer"

    @property
    def installer_manifest(self) -> Path:
        return self.installer_dir / "installer-manifest.json"

    @property
    def is_packaged_profile(self) -> bool:
        """Whether this gate must create and exercise a Windows delivery package."""

        return self.profile in {"beta", "release"}

    @property
    def signature_required(self) -> bool:
        """Keep the formal signing rule separate from an explicitly unsigned beta."""

        return self.profile == "release" and bool(self.contract["package"].get("signature_required", False))

    def build_desktop(self) -> None:
        previous = self._previous("build-desktop")
        if self.package_dir.exists() and not (previous and previous.get("status") == "passed"):
            raise GateFailure(
                f"Untrusted package directory already exists: {self.package_dir}. "
                "Use a new build id; the gate will not delete or overwrite it."
            )
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            raise GateFailure("PowerShell is required to build the Windows desktop package")
        package = dict(self.contract["package"])
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "build_desktop.ps1"),
            "-Mode",
            str(package.get("mode", "onedir")),
            "-PackageProfile",
            str(package.get("profile", "core")),
            "-OutputDir",
            str(self.package_staging_root),
            "-Name",
            str(package["name"]),
            "-Version",
            str(self.contract["version"]),
            "-BuildId",
            self.build_id,
            "-ReleaseSourceSha256",
            self.source_sha256,
            "-Clean",
        ]
        runtime_manifest_url = str(package.get("runtime_manifest_url", "")).strip()
        if runtime_manifest_url:
            command.extend(["-RuntimeManifestUrl", runtime_manifest_url])
        # PyInstaller's full profile emits a long analysis log. Keep it in the
        # release artifact instead of streaming it through a caller-owned
        # console pipe: desktop automation and CI runners may detach that pipe
        # while the build is still healthy, which used to turn a valid build
        # into a spurious ``Invalid argument`` gate failure.
        self.command_step(
            step_id="build-desktop",
            title="唯一目录中的正式 Windows 构建",
            command=command,
            echo_output=False,
        )

    def verify_package(self) -> dict[str, Any]:
        if not self.executable.is_file() or self.executable.stat().st_size <= 0:
            raise GateFailure(f"Packaged executable is missing or empty: {self.executable}")
        internal = self.package_dir / "_internal"
        missing = [
            relative
            for relative in list(self.contract["package"].get("required_resources", []) or [])
            if not (internal / str(relative)).is_file()
        ]
        if missing:
            raise GateFailure("Packaged resources are missing: " + ", ".join(missing))
        build_info_path = internal / "scansci_html" / "build-info.json"
        build_info = _read_json(build_info_path)
        if str(build_info.get("build_id")) != self.build_id:
            raise GateFailure("Packaged build-info.json does not match the release build id")
        expected_profile = str(self.contract["package"].get("profile", "core"))
        if str(build_info.get("package_profile", "")) != expected_profile:
            raise GateFailure("Packaged build-info.json does not match the package profile")
        expected_runtime_manifest = str(self.contract["package"].get("runtime_manifest_url", "")).strip()
        if expected_runtime_manifest and str(build_info.get("runtime_manifest_url", "")).strip() != expected_runtime_manifest:
            raise GateFailure("Packaged build-info.json does not match the runtime component manifest")
        if str(build_info.get("release_source_sha256", "")).casefold() != self.source_sha256.casefold():
            raise GateFailure("Packaged build-info.json is not bound to the source fingerprint that passed this gate")
        package_bytes = sum(path.stat().st_size for path in self.package_dir.rglob("*") if path.is_file())
        maximum_bytes = int(self.contract["package"].get("max_package_bytes", 0) or 0)
        if maximum_bytes and package_bytes > maximum_bytes:
            raise GateFailure(f"Package is too large: {package_bytes} bytes exceeds {maximum_bytes}")
        forbidden = [
            name
            for name in list(self.contract["package"].get("forbidden_top_level_resources", []) or [])
            if (internal / str(name)).exists()
        ]
        if expected_profile == "core":
            bundled_runtime = sorted(
                {
                    path.relative_to(internal).as_posix()
                    for path in internal.rglob("*")
                    if any(segment.casefold() in CORE_RUNTIME_FORBIDDEN_SEGMENTS for segment in path.relative_to(internal).parts)
                }
            )
            forbidden.extend(bundled_runtime)
        if forbidden:
            raise GateFailure("Core package contains optional runtime resources: " + ", ".join(forbidden))
        executable_sha256 = _sha256(self.executable)
        details = {
            "package_staging_dir": str(self.package_staging_root),
            "executable_path": str(self.executable),
            "executable_sha256": executable_sha256,
            "executable_bytes": self.executable.stat().st_size,
            "package_file_count": sum(1 for path in self.package_dir.rglob("*") if path.is_file()),
            "package_bytes": package_bytes,
            "package_profile": expected_profile,
            "build_info": build_info,
        }
        self.report["artifacts"].update(details)
        self._persist()
        return details

    def build_installer(self) -> None:
        """Produce a per-user Windows installer tied to the verified onedir package."""

        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            raise GateFailure("PowerShell is required to build the Windows installer")
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "build_windows_installer.ps1"),
            "-BuildDir",
            str(self.package_dir),
            "-Version",
            str(self.contract["version"]),
            "-BuildId",
            self.build_id,
            "-OutputDir",
            str(self.installer_dir),
        ]
        update_manifest_url = str(self.contract["package"].get("update_manifest_url", "")).strip()
        if update_manifest_url:
            command.extend(["-UpdateManifestUrl", update_manifest_url])
        if self.signature_required:
            command.append("-RequireSignature")
        self.command_step(
            step_id="build-installer",
            title="正式 Windows 安装包构建",
            command=command,
            required_result=self.installer_manifest,
            echo_output=False,
        )

    def signing_environment(self) -> dict[str, Any]:
        """Fail formal builds before expensive gates when signing is unavailable.

        The actual certificate/private-key validation remains inside the build
        script on the release machine. This early check deliberately records
        capability only, never a certificate thumbprint or timestamp endpoint.
        """

        if not self.signature_required:
            return {"signature_required": False}
        thumbprint = os.environ.get("SCANSCI_SIGNING_CERT_THUMBPRINT", "").replace(" ", "").strip()
        timestamp_url = os.environ.get("SCANSCI_TIMESTAMP_URL", "").strip()
        if not re.fullmatch(r"[A-Fa-f0-9]{40}", thumbprint):
            raise GateFailure(
                "Formal release signing is not configured: set SCANSCI_SIGNING_CERT_THUMBPRINT "
                "for the release certificate in CurrentUser\\My."
            )
        parsed_timestamp = urlparse(timestamp_url)
        if parsed_timestamp.scheme != "https" or not parsed_timestamp.netloc:
            raise GateFailure(
                "Formal release signing is not configured: SCANSCI_TIMESTAMP_URL must be an absolute HTTPS RFC 3161 endpoint."
            )
        if _find_sign_tool() is None:
            raise GateFailure(
                "Formal release signing is not configured: SignTool.exe from the Windows SDK or Visual Studio is unavailable."
            )
        return {
            "signature_required": True,
            "certificate_reference_present": True,
            "timestamp_endpoint_present": True,
            "sign_tool_available": True,
            "private_key_validation": "deferred_to_build_script",
        }

    def verify_installer_manifest(self) -> dict[str, Any]:
        if not self.installer_manifest.is_file():
            raise GateFailure(f"Installer manifest is missing: {self.installer_manifest}")
        manifest = _read_json(self.installer_manifest)
        installer = Path(str(manifest.get("installer_path", ""))).resolve()
        if not installer.is_file() or installer.stat().st_size <= 0:
            raise GateFailure("Installer executable is missing or empty")
        if str(manifest.get("version", "")) != str(self.contract["version"]):
            raise GateFailure("Installer manifest does not match the release version")
        if str(manifest.get("build_id", "")) != self.build_id:
            raise GateFailure("Installer manifest does not match the release build id")
        expected_executable_sha256 = str(self.report.get("artifacts", {}).get("executable_sha256", ""))
        if str(manifest.get("source_executable_sha256", "")).casefold() != expected_executable_sha256.casefold():
            raise GateFailure("Installer is not bound to the verified packaged executable")
        actual_installer_sha256 = _sha256(installer)
        if str(manifest.get("installer_sha256", "")).casefold() != actual_installer_sha256.casefold():
            raise GateFailure("Installer SHA256 does not match its manifest")
        signature_required = self.signature_required
        signature_status = str(manifest.get("authenticode_status", "Unknown"))
        source_signature_status = str(manifest.get("source_executable_authenticode_status", "Unknown"))
        if signature_required and (
            not bool(manifest.get("signature_required"))
            or signature_status.casefold() != "valid"
            or source_signature_status.casefold() != "valid"
        ):
            raise GateFailure(
                "Formal release requires valid Authenticode signatures for both the installer and ScanSci.exe; "
                f"installer={signature_status}, executable={source_signature_status}"
            )
        details = {
            "installer_path": str(installer),
            "installer_sha256": actual_installer_sha256,
            "installer_bytes": installer.stat().st_size,
            "installer_authenticode_status": signature_status,
            "source_executable_authenticode_status": source_signature_status,
            "installer_signature_required": signature_required,
            "installer_manifest": str(self.installer_manifest),
        }
        self.report["artifacts"].update(details)
        self._persist()
        return details

    def verify_installer_installation(self) -> None:
        installer = Path(str(self.report.get("artifacts", {}).get("installer_path", ""))).resolve()
        output = self.diagnostics_dir / "installer-installation.json"
        signature_required = self.signature_required
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "verify_windows_installer.py"),
            "--installer",
            str(installer),
            "--expected-build-id",
            self.build_id,
            "--output",
            str(output),
        ]
        if signature_required:
            command.append("--require-signature")
        self.command_step(
            step_id="installer-installation",
            title="正式安装包安装、运行与卸载验收",
            command=command,
            required_result=output,
            echo_output=False,
        )
        result = _read_json(output)
        if not bool(result.get("ok")):
            raise GateFailure("Installer verification reported ok=false")

    def prepare_beta_delivery(self) -> dict[str, Any]:
        """Write the exact hand-off materials for an invited, unsigned beta.

        The beta profile intentionally never looks like a formal public
        release: it records the unsigned state, binds every tester-facing
        value to the exercised installer, and provides a safe feedback
        template that does not invite users to paste secrets or documents.
        """

        if self.profile != "beta":
            raise GateFailure("Beta delivery material can only be written by the beta profile")
        installer = Path(str(self.report.get("artifacts", {}).get("installer_path", ""))).resolve()
        if not installer.is_file():
            raise GateFailure("Cannot prepare beta delivery material without a verified installer")
        installer_sha256 = str(self.report.get("artifacts", {}).get("installer_sha256", "")).casefold()
        if not re.fullmatch(r"[a-f0-9]{64}", installer_sha256):
            raise GateFailure("Cannot prepare beta delivery material without an installer SHA256")
        executable_sha256 = str(self.report.get("artifacts", {}).get("executable_sha256", "")).casefold()
        if not re.fullmatch(r"[a-f0-9]{64}", executable_sha256):
            raise GateFailure("Cannot prepare beta delivery material without an executable SHA256")

        installer_status = str(self.report.get("artifacts", {}).get("installer_authenticode_status", "Unknown"))
        executable_status = str(self.report.get("artifacts", {}).get("source_executable_authenticode_status", "Unknown"))
        if installer_status.casefold() == "valid" or executable_status.casefold() == "valid":
            raise GateFailure("The unsigned beta profile must not mix signed and unsigned delivery artifacts")

        delivery_dir = self.release_dir / "beta-delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        checksum_path = delivery_dir / "SHA256SUMS.txt"
        readme_path = delivery_dir / "BETA-README.zh-CN.md"
        feedback_path = delivery_dir / "BETA-FEEDBACK-TEMPLATE.md"
        manifest_path = delivery_dir / "beta-distribution.json"
        checksum_path.write_text(
            f"{installer_sha256}  {installer.name}\n",
            encoding="utf-8",
        )
        readme_path.write_text(
            "\n".join(
                [
                    f"# ScanSci {self.contract['version']} 受邀内测",
                    "",
                    f"构建编号：`{self.build_id}`",
                    "",
                    "这是受邀内测包，不是公开正式版。此安装包尚未使用公开信任的代码签名证书签名；Windows 可能显示“未知发布者”或 SmartScreen 提示。仅在你从 ScanSci 官方内测渠道收到本文件时继续安装。",
                    "",
                    "## 安装前核验",
                    "",
                    f"安装包：`{installer.name}`",
                    f"SHA-256：`{installer_sha256}`",
                    "",
                    "在 PowerShell 中运行：",
                    "",
                    "```powershell",
                    f"Get-FileHash .\\{installer.name} -Algorithm SHA256",
                    "```",
                    "",
                    "输出必须与上面的 SHA-256 完全一致。若不一致，请勿安装，并从提供内测包的渠道重新获取。",
                    "",
                    "## 反馈范围",
                    "",
                    "请优先反馈：安装或启动失败、资料库绑定/索引、证据引用、联网学术搜索、长任务恢复和界面异常。请使用同目录的 `BETA-FEEDBACK-TEMPLATE.md`。",
                    "",
                    "请不要在反馈中粘贴 API 密钥、Access Token、私有文档全文、未脱敏的个人资料或聊天记录。",
                    "",
                    "## 卸载与回退",
                    "",
                    "Windows 设置 → 应用 → 已安装的应用 → ScanSci → 卸载。卸载 ScanSci 不会删除你原始资料文件；若要保留问题现场，请先导出日志后再卸载。",
                    "",
                    "## 已知边界",
                    "",
                    "- 本包未签名，仅供受邀测试者使用，不应公开转发。",
                    "- 联网模型、学术搜索、Notion 等功能依赖各自服务的网络与账号状态。",
                    "- 首次建立资料索引可能消耗 CPU；应用会复用未变化资料的既有索引。",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        feedback_path.write_text(
            "\n".join(
                [
                    "# ScanSci 内测反馈",
                    "",
                    "- 构建编号：",
                    "- Windows 版本：",
                    "- 发生时间：",
                    "- 操作步骤：",
                    "- 实际结果：",
                    "- 期望结果：",
                    "- 是否可以稳定复现：是 / 否",
                    "- 截图或日志文件：",
                    "",
                    "请勿提交 API 密钥、Access Token、私有文档全文或未脱敏个人信息。",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _write_json(
            manifest_path,
            {
                "schema_version": 1,
                "product": str(self.contract.get("product", "ScanSci")),
                "channel": "invited-internal-beta",
                "version": str(self.contract["version"]),
                "build_id": self.build_id,
                "installer": {
                    "path": str(installer),
                    "file_name": installer.name,
                    "sha256": installer_sha256,
                    "authenticode_status": installer_status,
                    "unsigned_acknowledgement_required": True,
                },
                "packaged_executable": {
                    "sha256": executable_sha256,
                    "authenticode_status": executable_status,
                },
                "materials": {
                    "checksums": str(checksum_path),
                    "readme": str(readme_path),
                    "feedback_template": str(feedback_path),
                },
                "distribution_guardrails": [
                    "invited_testers_only",
                    "do_not_publish_to_a_public_download_page",
                    "verify_sha256_before_installing",
                    "do_not_collect_or_share_secrets_in_feedback",
                ],
            },
        )
        details = {
            "delivery_dir": str(delivery_dir),
            "distribution_manifest": str(manifest_path),
            "checksums": str(checksum_path),
            "readme": str(readme_path),
            "feedback_template": str(feedback_path),
            "installer_sha256": installer_sha256,
            "unsigned": True,
        }
        self.report["artifacts"]["beta_delivery"] = details
        self._persist()
        return details

    def packaged_diagnostics(self) -> None:
        output = self.diagnostics_dir / "packaged-runtime.json"
        runtime_dir = self.diagnostics_dir / "packaged-runtime-state"
        command = [
            str(self.executable),
            "--workspace",
            str(runtime_dir / "workspace.sqlite"),
            "--evidence-db",
            str(runtime_dir / "evidence.sqlite"),
            "--diagnose",
            "--diagnostics-output",
            str(output),
        ]
        self.command_step(
            step_id="packaged-diagnostics",
            title="正式 EXE 运行时依赖诊断",
            command=command,
            required_result=output,
        )
        payload = _read_json(output)
        if not bool(payload.get("ok")):
            raise GateFailure("Packaged runtime diagnostics reported ok=false")

    def packaged_health(self) -> dict[str, Any]:
        port = _find_available_port()
        runtime_dir = self.diagnostics_dir / "packaged-health-state"
        command = [
            str(self.executable),
            "--workspace",
            str(runtime_dir / "workspace.sqlite"),
            "--evidence-db",
            str(runtime_dir / "evidence.sqlite"),
            "--serve-only",
            "--port",
            str(port),
        ]
        process = subprocess.Popen(command, cwd=self.package_dir)
        try:
            deadline = time.monotonic() + 45
            health: dict[str, Any] | None = None
            last_error = ""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise GateFailure(f"Packaged server exited early with code {process.returncode}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
                        health = json.loads(response.read().decode("utf-8"))
                    break
                except Exception as error:
                    last_error = str(error)
                    time.sleep(0.5)
            if not health or health.get("status") != "ok":
                raise GateFailure(f"Packaged /api/health did not become ready: {last_error}")
            if str(health.get("build_id")) != self.build_id:
                raise GateFailure("Packaged health endpoint reported a different build id")
            return {"port": port, "health": health, "process_id": process.pid}
        finally:
            _stop_process(process)

    def packaged_liveness(self) -> dict[str, Any]:
        runtime_dir = self.diagnostics_dir / "packaged-desktop-state"
        command = [
            str(self.executable),
            "--workspace",
            str(runtime_dir / "workspace.sqlite"),
            "--evidence-db",
            str(runtime_dir / "evidence.sqlite"),
            "--title",
            f"ScanSci release verification {self.build_id}",
        ]
        process = subprocess.Popen(command, cwd=self.package_dir)
        try:
            time.sleep(15)
            if process.poll() is not None:
                raise GateFailure(f"Packaged desktop exited early with code {process.returncode}")
            return {"process_id": process.pid, "executable_path": str(self.executable), "survived_seconds": 15}
        finally:
            _stop_process(process)

    def visual_acceptance(self) -> dict[str, Any]:
        visual = dict(self.contract["visual_acceptance"])
        evidence_path = self.visual_evidence_dir / str(visual["evidence_file"])
        if not evidence_path.is_file():
            self.write_visual_template(evidence_path)
            raise GatePending(f"Desktop visual evidence is required: {evidence_path}")
        evidence = _read_json(evidence_path)
        expected_path = os.path.normcase(str(self.executable.resolve()))
        actual_path = os.path.normcase(str(Path(str(evidence.get("executable_path", ""))).resolve()))
        if actual_path != expected_path:
            raise GateFailure("Visual evidence executable_path does not match this release")
        if str(evidence.get("build_id")) != self.build_id:
            raise GateFailure("Visual evidence build_id does not match this release")
        expected_hash = str(self.report["artifacts"].get("executable_sha256", ""))
        if str(evidence.get("executable_sha256", "")).casefold() != expected_hash.casefold():
            raise GateFailure("Visual evidence executable_sha256 does not match this release")
        checks = dict(evidence.get("checks", {}) or {})
        failed = [name for name in list(visual["required_checks"]) if checks.get(name) is not True]
        if failed:
            raise GatePending("Desktop checks are not confirmed: " + ", ".join(failed))
        screenshots: dict[str, str] = {}
        for name in list(visual["required_screenshots"]):
            path = self.visual_evidence_dir / str(name)
            if not path.is_file() or path.stat().st_size <= 0:
                raise GatePending(f"Required desktop screenshot is missing: {path}")
            screenshots[str(name)] = str(path)
        return {"evidence_file": str(evidence_path), "screenshots": screenshots, "checks": checks}

    def write_visual_template(self, evidence_path: Path) -> None:
        visual = dict(self.contract["visual_acceptance"])
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        if evidence_path.exists():
            return
        payload = {
            "build_id": self.build_id,
            "executable_path": str(self.executable),
            "executable_sha256": str(self.report.get("artifacts", {}).get("executable_sha256", "")),
            "checked_at": None,
            "checks": {name: False for name in list(visual["required_checks"])},
            "screenshots": list(visual["required_screenshots"]),
            "notes": "只在真实桌面 EXE 中逐项验收后改为 true；截图必须来自同一 build_id。",
        }
        _write_json(evidence_path, payload)

    def plan(self) -> dict[str, Any]:
        steps = ["scope-contract"]
        if self.profile == "release":
            steps.append("signing-environment")
        groups = ["targeted_commands"]
        if self.profile in {"source", "beta", "release"}:
            groups.extend(["full_commands", "real_verifications"])
        for group in groups:
            steps.extend(str(item["id"]) for item in list(self.contract.get(group, []) or []))
        if self.is_packaged_profile:
            steps.extend(
                [
                    "build-desktop",
                    "package-integrity",
                    "build-installer",
                    "installer-integrity",
                    "installer-installation",
                    "packaged-diagnostics",
                    "packaged-health",
                    "packaged-liveness",
                ]
            )
            if self.profile == "release":
                steps.append("visual-acceptance")
            else:
                steps.append("beta-delivery")
        self.report.update(status="planned", finished_at=_utc_now(), planned_steps=steps)
        self._persist()
        return self.report

    def run(self) -> int:
        self.report.update(status="running", finished_at=None)
        self._persist()
        try:
            self.internal_step(
                "scope-contract",
                "单一 P0、验收标准与非目标契约",
                lambda: {
                    "p0_objective": self.scope["p0_objective"],
                    "acceptance_ids": [item["id"] for item in self.scope["acceptance"]],
                    "non_goals": self.scope["non_goals"],
                },
            )
            if self.profile == "release":
                self.internal_step(
                    "signing-environment",
                    "正式版签名环境预检",
                    self.signing_environment,
                )
            self.run_configured_commands("targeted_commands")
            if self.profile in {"source", "beta", "release"}:
                self.run_configured_commands("full_commands")
                self.run_configured_commands("real_verifications")
            if self.is_packaged_profile:
                self.build_desktop()
                self.internal_step("package-integrity", "包完整性、build_id 与 SHA256", self.verify_package)
                self.build_installer()
                self.internal_step("installer-integrity", "安装包、来源 EXE 与 SHA256", self.verify_installer_manifest)
                self.verify_installer_installation()
                self.packaged_diagnostics()
                self.internal_step("packaged-health", "打包 EXE 本地服务健康检查", self.packaged_health)
                self.internal_step("packaged-liveness", "打包桌面进程存活检查", self.packaged_liveness)
                if self.profile == "release":
                    self.internal_step("visual-acceptance", "正式 EXE 人工交互与视觉证据", self.visual_acceptance)
                else:
                    self.internal_step("beta-delivery", "受邀内测交付清单、校验值与反馈模板", self.prepare_beta_delivery)
        except GatePending as error:
            self.report.update(status="awaiting_visual_evidence", finished_at=_utc_now(), message=str(error))
            self._persist()
            _emit_console(f"[pending] {error}")
            _emit_console(f"Resume without rebuilding: .\\scripts\\release_gate.ps1 -Profile release -ResumeReport \"{self.report_path}\"")
            return 2
        except Exception as error:
            self.report.update(status="failed", finished_at=_utc_now(), message=str(error))
            self._persist()
            _emit_console(f"[failed] {error}", file=sys.stderr)
            return 1
        self.report.update(status="passed", finished_at=_utc_now(), message="All mandatory gates passed")
        self._persist()
        _emit_console(f"[passed] {self.report_path}")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run staged ScanSci source or Windows release gates.")
    parser.add_argument("--profile", choices=("targeted", "source", "beta", "release"), default="release")
    parser.add_argument("--contract", default="config/release-gate.json")
    parser.add_argument("--scope", default="")
    parser.add_argument("--knowledge-source", default=r"D:\光伏生态文献")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--build-id", default="")
    parser.add_argument("--resume-report", default="")
    parser.add_argument("--promote-report", default="")
    parser.add_argument("--visual-evidence-dir", default="")
    parser.add_argument("--plan-only", action="store_true")
    return parser


def default_output_root(*, profile: str, plan_only: bool) -> Path:
    if plan_only:
        return PROJECT_ROOT / ".scansci-diagnostics" / "release-gate-plans"
    if profile == "release":
        return PROJECT_ROOT / "releases"
    if profile == "beta":
        return PROJECT_ROOT / "internal-beta-releases"
    return PROJECT_ROOT / ".scansci-diagnostics" / "release-gates"


def validate_build_id(build_id: str) -> bool:
    """Accept a filesystem-safe build token, including SemVer build metadata."""

    return bool(build_id) and all(character.isalnum() or character in "._+-" for character in build_id)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.resume_report and args.promote_report:
        _emit_console("[failed] --resume-report and --promote-report are mutually exclusive", file=sys.stderr)
        return 1
    contract_path = _resolve_from_root(args.contract)
    contract = _read_json(contract_path)
    scope_path = _resolve_from_root(args.scope or str(contract.get("scope_file", "config/release-scope.json")))
    build_id = args.build_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    if not validate_build_id(build_id):
        _emit_console(
            "[failed] build-id may contain only letters, numbers, dots, underscores, plus signs, and hyphens",
            file=sys.stderr,
        )
        return 1
    if args.output_root:
        output_root = _resolve_from_root(args.output_root)
    else:
        output_root = default_output_root(profile=args.profile, plan_only=bool(args.plan_only))
    try:
        gate = ReleaseGate(
            contract_path=contract_path,
            scope_path=scope_path,
            profile=args.profile,
            knowledge_source=_resolve_from_root(args.knowledge_source),
            output_root=output_root,
            build_id=build_id,
            resume_report=_resolve_from_root(args.resume_report) if args.resume_report else None,
            promote_report=_resolve_from_root(args.promote_report) if args.promote_report else None,
            visual_evidence_dir=_resolve_from_root(args.visual_evidence_dir) if args.visual_evidence_dir else None,
        )
    except Exception as error:
        _emit_console(f"[failed] {error}", file=sys.stderr)
        return 1
    if args.plan_only:
        report = gate.plan()
        _emit_console(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    return gate.run()


if __name__ == "__main__":
    raise SystemExit(main())
