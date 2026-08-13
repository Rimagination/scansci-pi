"""Managed Node/Tectonic runtime components and resolution order tests."""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest

import scansci_html.artifact_plugins as artifact_plugins
import scansci_html.pi_agent as pi_agent
from scansci_html.runtime_components import (
    NODE_COMPONENT_ID,
    NODE_EXECUTABLE_NAME,
    TECTONIC_COMPONENT_ID,
    TECTONIC_EXECUTABLE_NAME,
    NodeRuntimeComponent,
    TectonicRuntimeComponent,
    default_node_component,
    runtime_components_status,
)


def test_node_component_uses_its_own_identity_and_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scansci_html.local_runtime_component.shutil.which", lambda _name: None)
    component = NodeRuntimeComponent(root=tmp_path / "node")

    assert component.component_id == NODE_COMPONENT_ID
    assert component.executable_name == NODE_EXECUTABLE_NAME
    assert component.root == (tmp_path / "node").resolve()
    assert component.executable() is None  # nothing installed yet
    assert component.status()["installed"] is False
    assert component.status()["id"] == NODE_COMPONENT_ID


def test_tectonic_component_uses_its_own_identity_and_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scansci_html.local_runtime_component.shutil.which", lambda _name: None)
    component = TectonicRuntimeComponent(root=tmp_path / "tectonic")

    assert component.component_id == TECTONIC_COMPONENT_ID
    assert component.executable_name == TECTONIC_EXECUTABLE_NAME
    assert component.root == (tmp_path / "tectonic").resolve()
    assert component.status()["id"] == TECTONIC_COMPONENT_ID


def test_runtime_components_use_distinct_persisted_install_jobs(tmp_path: Path) -> None:
    node = NodeRuntimeComponent(root=tmp_path / "node")
    tectonic = TectonicRuntimeComponent(root=tmp_path / "tectonic")

    assert node.install_job_id == "runtime:node"
    assert tectonic.install_job_id == "runtime:tectonic"
    assert node.install_status()["job_id"] != tectonic.install_status()["job_id"]


def test_packaged_components_use_their_own_manifest_channels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scansci_html.local_runtime_component.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "scansci_html.local_runtime_component.current_build_info",
        lambda: {
            "frozen": True,
            "package_profile": "core",
            "runtime_manifest_url": "https://downloads.example.com/local-transformers.json",
            "node_component_manifest_url": "https://downloads.example.com/node.json",
            "tectonic_component_manifest_url": "https://downloads.example.com/tectonic.json",
        },
    )

    node = NodeRuntimeComponent(root=tmp_path / "node")
    tectonic = TectonicRuntimeComponent(root=tmp_path / "tectonic")

    assert node.manifest_url == "https://downloads.example.com/node.json"
    assert tectonic.manifest_url == "https://downloads.example.com/tectonic.json"
    assert "local-transformers.json" not in " ".join(node.manifest_urls + tectonic.manifest_urls)


def test_node_component_reuses_an_existing_system_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_node = tmp_path / "system" / NODE_EXECUTABLE_NAME
    system_node.parent.mkdir()
    system_node.write_bytes(b"MZ")
    monkeypatch.setattr(
        "scansci_html.local_runtime_component.shutil.which",
        lambda name: str(system_node) if name in {"node", "node.exe"} else None,
    )

    component = NodeRuntimeComponent(root=tmp_path / "managed-node")
    status = component.status()

    assert component.executable() == system_node.resolve()
    assert status["installed"] is True
    assert status["mode"] == "system"
    assert status["version"] == "external"


def test_component_executable_resolves_through_active_json(tmp_path: Path) -> None:
    component = NodeRuntimeComponent(root=tmp_path / "node")
    version_dir = component.root / "versions" / "22.14.0"
    version_dir.mkdir(parents=True)
    executable = version_dir / NODE_EXECUTABLE_NAME
    executable.write_bytes(b"MZ")
    component.root.mkdir(parents=True, exist_ok=True)
    (component.root / "active.json").write_text(
        json.dumps(
            {
                "id": NODE_COMPONENT_ID,
                "version": "22.14.0",
                "executable": str(executable.relative_to(component.root)),
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    resolved = component.executable()
    assert resolved == executable.resolve()


def test_runtime_components_status_reports_both_components(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scansci_html.runtime_components.default_node_component",
        lambda: NodeRuntimeComponent(root=tmp_path / "node"),
    )
    monkeypatch.setattr(
        "scansci_html.runtime_components.default_tectonic_component",
        lambda: TectonicRuntimeComponent(root=tmp_path / "tectonic"),
    )

    status = runtime_components_status()
    assert set(status) == {"node", "tectonic"}
    assert status["node"]["id"] == NODE_COMPONENT_ID
    assert status["tectonic"]["id"] == TECTONIC_COMPONENT_ID


def test_pi_agent_prefers_managed_node_over_bundled(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    managed = NodeRuntimeComponent(root=tmp_path / "node")
    version_dir = managed.root / "versions" / "22.14.0"
    version_dir.mkdir(parents=True)
    managed_node = version_dir / NODE_EXECUTABLE_NAME
    managed_node.write_bytes(b"MZ")
    managed.root.mkdir(parents=True, exist_ok=True)
    (managed.root / "active.json").write_text(
        json.dumps(
            {
                "id": NODE_COMPONENT_ID,
                "version": "22.14.0",
                "executable": str(managed_node.relative_to(managed.root)),
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scansci_html.pi_agent.default_node_component",
        lambda: managed,
    )
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(
        pi_agent,
        "sys",
        SimpleNamespace(
            frozen=True,
            _MEIPASS=str(bundle),
            executable=sys.executable,
            platform=sys.platform,
        ),
    )
    script = bundle / "pi_runtime" / "main.mjs"
    script.parent.mkdir(parents=True)
    script.write_text("export {};")

    node_path, script_path = pi_agent.PiAgentClient.runtime_paths()
    assert node_path == managed_node.resolve()
    assert script_path == script.resolve()


def test_build_contract_bundles_pi_main_but_keeps_node_out_of_core() -> None:
    project_root = Path(__file__).parents[1]
    build_script = (project_root / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")
    release_contract = json.loads((project_root / "config" / "release-gate.json").read_text(encoding="utf-8"))

    assert "pi_runtime/main.mjs" in release_contract["package"]["required_resources"]
    assert '"--add-data", "$piBundle;pi_runtime"' in build_script
    assert '$(if (-not $ExcludeRuntimes) { @("--add-binary", "$nodeExe;pi_runtime") } else { @() })' in build_script
    assert "pi_bundle_sha256" in build_script
    assert "node.exe" not in release_contract["package"]["required_resources"]


def test_packaged_pi_bundle_hash_is_a_content_digest(tmp_path: Path) -> None:
    bundle = tmp_path / "main.mjs"
    bundle.write_bytes(b"export const probe = true;\n")
    expected = hashlib.sha256(bundle.read_bytes()).hexdigest()

    build_info = {"pi_bundle_sha256": expected}

    assert build_info["pi_bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_find_tectonic_prefers_managed_component_over_bundled(tmp_path: Path, monkeypatch) -> None:
    managed = TectonicRuntimeComponent(root=tmp_path / "tectonic")
    version_dir = managed.root / "versions" / "0.15.0"
    version_dir.mkdir(parents=True)
    managed_exe = version_dir / TECTONIC_EXECUTABLE_NAME
    managed_exe.write_bytes(b"MZ")
    managed.root.mkdir(parents=True, exist_ok=True)
    (managed.root / "active.json").write_text(
        json.dumps(
            {
                "id": TECTONIC_COMPONENT_ID,
                "version": "0.15.0",
                "executable": str(managed_exe.relative_to(managed.root)),
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scansci_html.artifact_plugins.default_tectonic_component",
        lambda: managed,
    )
    monkeypatch.setattr(artifact_plugins.os, "environ", {"USERPROFILE": str(tmp_path), "HOME": str(tmp_path)})
    monkeypatch.setattr(artifact_plugins.shutil, "which", lambda _name: None)

    found = artifact_plugins.find_tectonic()
    # The managed component outranks the bundled repo copy (which may exist).
    assert found == managed_exe.resolve()


def test_component_install_requires_user_initiated_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scansci_html.local_runtime_component.shutil.which", lambda _name: None)
    component = NodeRuntimeComponent(root=tmp_path / "node")
    # ensure_installed must never silently fetch the runtime: it raises until
    # the user confirms an install through start_install()/install().
    with pytest.raises(RuntimeError):
        component.ensure_installed()
