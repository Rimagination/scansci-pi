"""Managed Node/Tectonic runtime components and resolution order tests."""

from __future__ import annotations

import json
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


def test_node_component_uses_its_own_identity_and_root(tmp_path: Path) -> None:
    component = NodeRuntimeComponent(root=tmp_path / "node")

    assert component.component_id == NODE_COMPONENT_ID
    assert component.executable_name == NODE_EXECUTABLE_NAME
    assert component.root == (tmp_path / "node").resolve()
    assert component.executable() is None  # nothing installed yet
    assert component.status()["installed"] is False
    assert component.status()["id"] == NODE_COMPONENT_ID


def test_tectonic_component_uses_its_own_identity_and_root(tmp_path: Path) -> None:
    component = TectonicRuntimeComponent(root=tmp_path / "tectonic")

    assert component.component_id == TECTONIC_COMPONENT_ID
    assert component.executable_name == TECTONIC_EXECUTABLE_NAME
    assert component.root == (tmp_path / "tectonic").resolve()
    assert component.status()["id"] == TECTONIC_COMPONENT_ID


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


def test_component_install_requires_user_initiated_download(tmp_path: Path) -> None:
    component = NodeRuntimeComponent(root=tmp_path / "node")
    # ensure_installed must never silently fetch the runtime: it raises until
    # the user confirms an install through start_install()/install().
    with pytest.raises(RuntimeError):
        component.ensure_installed()
