from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.archive_binary_component import archive_binary_component
from scansci_html.runtime_components import NodeRuntimeComponent


def test_archives_a_standalone_runtime_with_an_installable_manifest(tmp_path: Path) -> None:
    package = tmp_path / "node-package"
    package.mkdir()
    (package / "node.exe").write_bytes(b"MZ-node")
    (package / "README.md").write_text("runtime", encoding="utf-8")
    notice = tmp_path / "LICENSE.txt"
    notice.write_text("license", encoding="utf-8")

    archive, manifest_path = archive_binary_component(
        package,
        tmp_path / "release",
        component_id="node",
        version="22.14.0",
        executable_name="node.exe",
        package_url="https://downloads.example.com/node-22.14.0-windows.zip",
        notice_files=(notice,),
    )

    with ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            "node-22.14.0/licenses/LICENSE.txt",
            "node-22.14.0/README.md",
            "node-22.14.0/node.exe",
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["id"] == "node"
    assert manifest["version"] == "22.14.0"
    assert manifest["windows"]["url"].startswith("https://")
    assert manifest["windows"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest["windows"]["size"] == archive.stat().st_size


def test_binary_component_archive_rejects_an_ambiguous_executable(tmp_path: Path) -> None:
    package = tmp_path / "ambiguous"
    (package / "one").mkdir(parents=True)
    (package / "two").mkdir()
    (package / "one" / "tectonic.exe").write_bytes(b"one")
    (package / "two" / "tectonic.exe").write_bytes(b"two")

    with pytest.raises(FileNotFoundError, match="exactly one tectonic.exe"):
        archive_binary_component(
            package,
            tmp_path / "release",
            component_id="tectonic",
            version="0.15.0",
            executable_name="tectonic.exe",
        )


def test_archived_binary_component_installs_through_the_shared_component_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "node-package"
    package.mkdir()
    (package / "node.exe").write_bytes(b"MZ-managed-node")
    _archive, manifest_path = archive_binary_component(
        package,
        tmp_path / "release",
        component_id="node",
        version="22.14.0",
        executable_name="node.exe",
    )
    monkeypatch.setattr("scansci_html.local_runtime_component.shutil.which", lambda _name: None)
    component = NodeRuntimeComponent(
        root=tmp_path / "installed-node",
        manifest_url=manifest_path.as_uri(),
    )

    installed = component.install()

    assert installed["installed"] is True
    assert component.executable() is not None
    assert component.executable().read_bytes() == b"MZ-managed-node"
