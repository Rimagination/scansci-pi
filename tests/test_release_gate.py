from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from scripts.verify_scansci_agent import _numbered_section_bullet_counts, _numbered_section_count


SCRIPT = Path(__file__).parents[1] / "scripts" / "release_gate.py"
SPEC = importlib.util.spec_from_file_location("scansci_release_gate", SCRIPT)
assert SPEC and SPEC.loader
release_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_gate)


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _scope() -> dict:
    return {
        "schema_version": 1,
        "p0_objective": "验证发布门禁",
        "acceptance": [{"id": "gate", "requirement": "门禁留下证据"}],
        "non_goals": ["不改产品功能"],
    }


def _contract(command: list[str] | None = None) -> dict:
    return {
        "schema_version": 1,
        "product": "ScanSci",
        "version": "0.2.0-test",
        "targeted_commands": (
            [{"id": "fake-targeted", "title": "快速命令", "command": command}]
            if command
            else []
        ),
        "full_commands": [],
        "real_verifications": [],
        "package": {"name": "ScanSci", "mode": "onedir", "required_resources": []},
        "visual_acceptance": {
            "evidence_file": "visual-evidence.json",
            "required_checks": ["enter_send"],
            "required_screenshots": ["home.png"],
        },
    }


def test_release_contract_requires_one_p0_with_acceptance_and_non_goals() -> None:
    scope = _scope()
    release_gate.validate_release_inputs(_contract(), scope)
    scope["non_goals"] = []
    with pytest.raises(release_gate.GateFailure, match="non-empty acceptance and non_goals"):
        release_gate.validate_release_inputs(_contract(), scope)


def test_release_gate_console_output_survives_legacy_windows_codepages(capsys: pytest.CaptureFixture[str]) -> None:
    release_gate._emit_console("证据 \ufffd", encoding="gbk")

    output = capsys.readouterr().out
    assert "证据" in output
    assert "\\ufffd" in output


def test_release_gate_accepts_semver_build_metadata_but_rejects_path_separators() -> None:
    assert release_gate.validate_build_id("0.2.0+formal-r4-20260728")
    assert release_gate.validate_build_id("20260728-120000")
    assert not release_gate.validate_build_id("../escape")
    assert not release_gate.validate_build_id("release/name")


def test_agent_release_check_accepts_six_numbered_sections_without_an_arbitrary_long_answer() -> None:
    text = "\n".join(f"### {index}. 第{index}项\n- 检查一\n- 检查二\n- 检查三" for index in range(1, 7))
    assert _numbered_section_count(text) == 6
    assert _numbered_section_bullet_counts(text) == [3, 3, 3, 3, 3, 3]


def test_real_release_contract_defaults_to_a_lightweight_core_package() -> None:
    contract = json.loads((Path(__file__).parents[1] / "config" / "release-gate.json").read_text(encoding="utf-8"))

    assert contract["package"]["profile"] == "core"
    assert int(contract["package"]["max_package_bytes"]) <= 1_500_000_000


def test_release_contract_accepts_only_https_runtime_component_manifests() -> None:
    contract = _contract()
    contract["package"]["runtime_manifest_url"] = "https://downloads.example.com/runtime.json"
    release_gate.validate_release_inputs(contract, _scope())

    contract["package"]["runtime_manifest_url"] = "file:///C:/runtime.json"
    with pytest.raises(release_gate.GateFailure, match="runtime_manifest_url must use HTTPS"):
        release_gate.validate_release_inputs(contract, _scope())


def test_plan_only_writes_machine_readable_report_without_running_commands(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract(["{python}", "-c", "raise SystemExit(9)"]))
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="plan-test",
    )
    report = gate.plan()
    persisted = json.loads(gate.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "planned"
    assert persisted["planned_steps"] == ["scope-contract", "fake-targeted"]
    assert not (gate.diagnostics_dir / "fake-targeted.log").exists()


def test_release_plan_default_never_creates_an_empty_release_candidate() -> None:
    plan_root = release_gate.default_output_root(profile="release", plan_only=True)
    real_release_root = release_gate.default_output_root(profile="release", plan_only=False)
    assert plan_root.name == "release-gate-plans"
    assert real_release_root.name == "releases"
    assert plan_root != real_release_root


def test_source_gate_resumes_passed_steps_without_repeating_commands(tmp_path: Path) -> None:
    marker = tmp_path / "command-count.txt"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(marker)!r}); "
        "p.write_text((p.read_text() if p.exists() else '') + 'x', encoding='utf-8')"
    )
    contract_path = _write_json(tmp_path / "contract.json", _contract(["{python}", "-c", code]))
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    first = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="resume-test",
    )
    assert first.run() == 0
    second = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "ignored",
        build_id="ignored",
        resume_report=first.report_path,
    )
    assert second.run() == 0
    assert marker.read_text(encoding="utf-8") == "x"
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert {step["id"] for step in report["steps"]} == {"scope-contract", "fake-targeted"}


def test_real_verification_retries_only_an_explicit_rate_limit_result(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="rate-retry-test",
    )
    marker = tmp_path / "attempts.txt"
    result = gate.diagnostics_dir / "agent.json"
    code = (
        "from pathlib import Path; import json; "
        f"marker=Path({str(marker)!r}); result=Path({str(result)!r}); "
        "count=len(marker.read_text() if marker.exists() else '')+1; "
        "marker.write_text('x'*count); "
        "result.write_text(json.dumps({'failure_reason': 'provider_rate_limited' if count == 1 else ''})); "
        "raise SystemExit(1 if count == 1 else 0)"
    )

    step = gate.command_step(
        step_id="rate-limited-model",
        title="rate limited model verification",
        command=[sys.executable, "-c", code],
        required_result=result,
        echo_output=False,
        retry={"max_attempts": 2, "delay_seconds": 0, "failure_reason": "provider_rate_limited"},
    )

    assert step["status"] == "passed"
    assert marker.read_text(encoding="utf-8") == "xx"
    assert [attempt["exit_code"] for attempt in step["attempts"]] == [1, 0]
    assert step["attempts"][0]["failure_reason"] == "provider_rate_limited"


def test_command_retry_can_match_failure_text_in_the_command_log(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="log-retry-test",
    )
    marker = tmp_path / "attempts.txt"
    code = (
        "from pathlib import Path; "
        f"marker=Path({str(marker)!r}); "
        "count=len(marker.read_text() if marker.exists() else '')+1; "
        "marker.write_text('x'*count); "
        "print('test_notebook_webapp_tests_saved_mcp_connection_and_reports_tools' if count == 1 else 'ok'); "
        "raise SystemExit(1 if count == 1 else 0)"
    )

    step = gate.command_step(
        step_id="log-retry",
        title="log retry",
        command=[sys.executable, "-c", code],
        echo_output=False,
        retry={
            "max_attempts": 2,
            "delay_seconds": 0,
            "failure_reason": "test_notebook_webapp_tests_saved_mcp_connection_and_reports_tools",
        },
    )

    assert step["status"] == "passed"
    assert marker.read_text(encoding="utf-8") == "xx"
    assert [attempt["exit_code"] for attempt in step["attempts"]] == [1, 0]
    assert step["attempts"][0]["failure_reason"] == "test_notebook_webapp_tests_saved_mcp_connection_and_reports_tools"


def test_command_step_can_write_nested_process_output_directly_to_its_log(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="file-output-test",
    )

    step = gate.command_step(
        step_id="file-output",
        title="file output",
        command=[sys.executable, "-c", "print('nested output')"],
        echo_output=False,
        output_to_file=True,
    )

    assert step["status"] == "passed"
    assert "nested output" in (gate.diagnostics_dir / "file-output.log").read_text(encoding="utf-8")


def test_release_gate_stops_a_hung_verification_at_the_declared_timeout(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="command-timeout-test",
    )

    with pytest.raises(release_gate.GateFailure, match="hung provider verification"):
        gate.command_step(
            step_id="hung-provider",
            title="hung provider verification",
            command=[sys.executable, "-c", "import time; time.sleep(3)"],
            echo_output=False,
            timeout_seconds=0.1,
        )

    step = gate.report["steps"][-1]

    assert step["status"] == "failed"
    assert step["exit_code"] == 124
    assert step["failure_reason"] == "command_timeout"
    assert step["attempts"][0]["failure_reason"] == "command_timeout"
    assert step["attempts"][0]["timeout_seconds"] == 0.1


def test_higher_profile_can_promote_unchanged_passed_evidence(tmp_path: Path) -> None:
    marker = tmp_path / "promoted-command-count.txt"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(marker)!r}); "
        "p.write_text((p.read_text() if p.exists() else '') + 'x', encoding='utf-8')"
    )
    contract_path = _write_json(tmp_path / "contract.json", _contract(["{python}", "-c", code]))
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    targeted = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="targeted",
        knowledge_source=tmp_path,
        output_root=tmp_path / "targeted-reports",
        build_id="targeted",
    )
    assert targeted.run() == 0
    promoted = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="source",
        knowledge_source=tmp_path,
        output_root=tmp_path / "source-reports",
        build_id="source",
        promote_report=targeted.report_path,
    )
    assert promoted.run() == 0
    assert marker.read_text(encoding="utf-8") == "x"
    report = json.loads(promoted.report_path.read_text(encoding="utf-8"))
    assert report["promoted_from"]["profile"] == "targeted"
    assert report["promoted_from"]["step_ids"] == ["scope-contract", "fake-targeted"]


def test_build_script_reuses_dependency_cache_and_only_cleans_on_request() -> None:
    build_script = (Path(__file__).parents[1] / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")
    assert 'build\\desktop-cache\\$cacheName' in build_script
    assert 'build\\desktop-spec\\$cacheName' in build_script
    assert 'build\\desktop\\$resolvedBuildId' not in build_script
    assert '$metadataPath = Join-Path $projectRoot "build\\release-metadata\\$resolvedBuildId"' in build_script
    assert "if ($Clean)" in build_script
    assert '$pyInstallerArgs = @("--clean") + $pyInstallerArgs' in build_script
    assert '"--clean",' not in build_script
    assert '[string]$ReleaseSourceSha256 = ""' in build_script
    assert 'release_source_sha256 = $ReleaseSourceSha256.ToLowerInvariant()' in build_script


def test_release_package_is_bound_to_the_source_fingerprint_that_passed_the_gate(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="release-source-binding",
    )
    package = gate.package_dir
    internal = package / "_internal" / "scansci_html"
    internal.mkdir(parents=True)
    gate.executable.write_bytes(b"scan-sci")
    _write_json(internal / "build-info.json", {
        "build_id": gate.build_id,
        "package_profile": "core",
        "release_source_sha256": "0" * 64,
    })

    with pytest.raises(release_gate.GateFailure, match="source fingerprint"):
        gate.verify_package()


def test_core_package_rejects_bundled_model_runtime_or_huggingface_snapshot(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="core-forbidden-runtime",
    )
    internal = gate.package_dir / "_internal" / "scansci_html"
    internal.mkdir(parents=True)
    gate.executable.write_bytes(b"scan-sci")
    _write_json(internal / "build-info.json", {
        "build_id": gate.build_id,
        "package_profile": "core",
        "release_source_sha256": gate.source_sha256,
    })
    bundled_torch = gate.package_dir / "_internal" / "torch" / "lib"
    bundled_torch.mkdir(parents=True)
    (bundled_torch / "torch_cpu.dll").write_bytes(b"not-a-runtime")

    with pytest.raises(release_gate.GateFailure, match="optional runtime resources"):
        gate.verify_package()


def test_release_build_keeps_long_pyinstaller_output_in_its_artifact_log(tmp_path: Path, monkeypatch) -> None:
    contract = _contract()
    contract["package"]["runtime_manifest_url"] = "https://downloads.example.com/runtime.json"
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="quiet-package-build",
    )
    captured: dict[str, object] = {}

    def fake_command_step(**kwargs):
        captured.update(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(gate, "command_step", fake_command_step)
    monkeypatch.setattr(release_gate.shutil, "which", lambda _name: "powershell.exe")
    gate.build_desktop()

    assert captured["step_id"] == "build-desktop"
    assert captured["echo_output"] is False
    command = list(captured["command"])
    output_dir_index = command.index("-OutputDir") + 1
    assert Path(command[output_dir_index]) == gate.package_staging_root
    runtime_manifest_index = command.index("-RuntimeManifestUrl") + 1
    assert command[runtime_manifest_index] == "https://downloads.example.com/runtime.json"
    assert "-ExcludeRuntimes" not in command
    assert gate.package_dir == gate.package_staging_root / "ScanSci"
    assert len(str(gate.package_dir)) < len(str(gate.release_dir / "ScanSci"))


def test_windows_installer_build_script_supports_standard_and_per_user_inno_locations() -> None:
    installer_script = (Path(__file__).parents[1] / "scripts" / "build_windows_installer.ps1").read_text(encoding="utf-8")

    assert "Inno Setup 6\\ISCC.exe" in installer_script
    assert "$env:LOCALAPPDATA\\Programs\\Inno Setup 6\\ISCC.exe" in installer_script
    assert "Get-AuthenticodeSignature" in installer_script
    assert "SCANSCI_SIGNING_CERT_THUMBPRINT" in installer_script
    assert "SCANSCI_TIMESTAMP_URL" in installer_script
    assert "Sign-Artifact -Artifact $exe -Signing $signing" in installer_script
    assert "Sign-Artifact -Artifact $installer -Signing $signing" in installer_script


def test_formal_release_requests_a_signed_installer(tmp_path: Path, monkeypatch) -> None:
    contract = _contract()
    contract["package"]["signature_required"] = True
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="signed-installer",
    )
    captured: dict[str, object] = {}

    def fake_command_step(**kwargs):
        captured.update(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(gate, "command_step", fake_command_step)
    monkeypatch.setattr(release_gate.shutil, "which", lambda _name: "powershell.exe")
    gate.build_installer()

    assert "-RequireSignature" in captured["command"]


def test_formal_release_signing_preflight_rejects_missing_configuration(tmp_path: Path, monkeypatch) -> None:
    contract = _contract()
    contract["package"]["signature_required"] = True
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="signing-preflight",
    )
    monkeypatch.delenv("SCANSCI_SIGNING_CERT_THUMBPRINT", raising=False)
    monkeypatch.delenv("SCANSCI_TIMESTAMP_URL", raising=False)

    with pytest.raises(release_gate.GateFailure, match="signing is not configured"):
        gate.signing_environment()


def test_formal_release_signing_preflight_records_a_configured_release_machine(tmp_path: Path, monkeypatch) -> None:
    contract = _contract()
    contract["package"]["signature_required"] = True
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="configured-signing-preflight",
    )
    monkeypatch.setenv("SCANSCI_SIGNING_CERT_THUMBPRINT", "A" * 40)
    monkeypatch.setenv("SCANSCI_TIMESTAMP_URL", "https://timestamp.example.test/rfc3161")
    monkeypatch.setattr(release_gate, "_find_sign_tool", lambda: tmp_path / "signtool.exe")

    assert gate.signing_environment() == {
        "signature_required": True,
        "certificate_reference_present": True,
        "timestamp_endpoint_present": True,
        "sign_tool_available": True,
        "private_key_validation": "deferred_to_build_script",
    }


def test_formal_release_installer_verification_requires_an_installed_signature(tmp_path: Path, monkeypatch) -> None:
    contract = _contract()
    contract["package"]["signature_required"] = True
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="signed-installation",
    )
    gate.report["artifacts"]["installer_path"] = str(tmp_path / "installer.exe")
    captured: dict[str, object] = {}

    def fake_command_step(**kwargs):
        captured.update(kwargs)
        Path(str(kwargs["required_result"])).write_text('{"ok": true}', encoding="utf-8")
        return {"status": "passed"}

    monkeypatch.setattr(gate, "command_step", fake_command_step)
    gate.verify_installer_installation()

    assert "--require-signature" in captured["command"]


def test_formal_release_rejects_an_unsigned_installer_manifest(tmp_path: Path) -> None:
    contract = _contract()
    contract["package"]["signature_required"] = True
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="unsigned-installer",
    )
    installer = gate.installer_dir / "ScanSci-0.2.0-test-windows-x64-setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"installer")
    digest = release_gate._sha256(installer)
    gate.report["artifacts"]["executable_sha256"] = digest
    _write_json(
        gate.installer_manifest,
        {
            "version": "0.2.0-test",
            "build_id": gate.build_id,
            "installer_path": str(installer),
            "installer_sha256": digest,
            "source_executable_sha256": digest,
            "signature_required": False,
            "authenticode_status": "NotSigned",
        },
    )

    with pytest.raises(release_gate.GateFailure, match="both the installer and ScanSci.exe"):
        gate.verify_installer_manifest()


def test_formal_release_rejects_a_manifest_with_an_unsigned_packaged_executable(tmp_path: Path) -> None:
    contract = _contract()
    contract["package"]["signature_required"] = True
    contract_path = _write_json(tmp_path / "contract.json", contract)
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="unsigned-executable",
    )
    installer = gate.installer_dir / "ScanSci-0.2.0-test-windows-x64-setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"installer")
    digest = release_gate._sha256(installer)
    gate.report["artifacts"]["executable_sha256"] = digest
    _write_json(
        gate.installer_manifest,
        {
            "version": "0.2.0-test",
            "build_id": gate.build_id,
            "installer_path": str(installer),
            "installer_sha256": digest,
            "source_executable_sha256": digest,
            "signature_required": True,
            "authenticode_status": "Valid",
            "source_executable_authenticode_status": "NotSigned",
        },
    )

    with pytest.raises(release_gate.GateFailure, match="both the installer and ScanSci.exe"):
        gate.verify_installer_manifest()


def test_release_source_fingerprint_includes_the_installer_and_gateway_definitions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '("src", "scripts", "tests", "config", "installer", "services")' in source


def test_release_plan_requires_a_built_and_exercised_windows_installer(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="installer-plan",
    )

    plan = gate.plan()

    assert "build-installer" in plan["planned_steps"]
    assert "installer-integrity" in plan["planned_steps"]
    assert "installer-installation" in plan["planned_steps"]
    assert "signing-environment" in plan["planned_steps"]


def test_beta_plan_builds_and_exercises_an_unsigned_installer_without_formal_signing(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="beta",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="invited-beta-plan",
    )

    plan = gate.plan()

    assert "signing-environment" not in plan["planned_steps"]
    assert "build-installer" in plan["planned_steps"]
    assert "installer-installation" in plan["planned_steps"]
    assert "beta-delivery" in plan["planned_steps"]
    assert "visual-acceptance" not in plan["planned_steps"]


def test_beta_delivery_materials_bind_to_the_unsigned_verified_installer(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="beta",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="invited-beta-materials",
    )
    installer = gate.installer_dir / "ScanSci-0.2.0-test-windows-x64-setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"unsigned installer")
    gate.report["artifacts"].update(
        {
            "installer_path": str(installer),
            "installer_sha256": release_gate._sha256(installer),
            "installer_authenticode_status": "NotSigned",
            "executable_sha256": "a" * 64,
            "source_executable_authenticode_status": "NotSigned",
        }
    )

    details = gate.prepare_beta_delivery()
    delivery = json.loads(Path(details["distribution_manifest"]).read_text(encoding="utf-8"))

    assert delivery["channel"] == "invited-internal-beta"
    assert delivery["installer"]["sha256"] == release_gate._sha256(installer)
    assert delivery["installer"]["unsigned_acknowledgement_required"] is True
    assert "未知发布者" in Path(details["readme"]).read_text(encoding="utf-8")
    assert "API 密钥" in Path(details["feedback_template"]).read_text(encoding="utf-8")


def test_beta_outputs_are_isolated_from_formal_releases() -> None:
    assert release_gate.default_output_root(profile="beta", plan_only=False).name == "internal-beta-releases"


def test_installer_manifest_must_bind_to_the_verified_packaged_executable(tmp_path: Path) -> None:
    contract_path = _write_json(tmp_path / "contract.json", _contract())
    scope_path = _write_json(tmp_path / "scope.json", _scope())
    gate = release_gate.ReleaseGate(
        contract_path=contract_path,
        scope_path=scope_path,
        profile="release",
        knowledge_source=tmp_path,
        output_root=tmp_path / "reports",
        build_id="installer-binding",
    )
    installer = gate.installer_dir / "ScanSci-0.2.0-test-windows-x64-setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"installer")
    gate.report["artifacts"]["executable_sha256"] = "a" * 64
    _write_json(
        gate.installer_manifest,
        {
            "version": "0.2.0-test",
            "build_id": gate.build_id,
            "installer_path": str(installer),
            "installer_sha256": release_gate._sha256(installer),
            "source_executable_sha256": "b" * 64,
        },
    )

    with pytest.raises(release_gate.GateFailure, match="verified packaged executable"):
        gate.verify_installer_manifest()
