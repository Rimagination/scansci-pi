from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.request import urlopen
from zipfile import ZipFile

import pytest

from scansci_html import local_runtime_component
import scansci_html.local_transformers_runtime as local_transformers_runtime
from scansci_html.app_update import AppUpdateService
from scansci_html.local_runtime_component import LocalRuntimeComponent
from scansci_html.local_runtime_server import LocalRuntimeServer
from scansci_html.webapp import NotebookWebApp


def test_installed_component_is_preferred_even_when_source_has_torch(tmp_path: Path, monkeypatch) -> None:
    class InstalledComponent:
        def executable(self):
            return tmp_path / "ScanSciLocalRuntime.exe"

        def ensure_process(self, model_id: str) -> str:
            assert model_id == "Qwen/Qwen3.5-2B"
            return "http://127.0.0.1:17863/v1"

    monkeypatch.setattr(local_transformers_runtime, "default_local_runtime_component", InstalledComponent)
    monkeypatch.setattr(
        local_transformers_runtime._RUNTIME,
        "ensure",
        lambda _model_id: (_ for _ in ()).throw(AssertionError("in-process runtime must not start")),
    )

    assert local_transformers_runtime.ensure_local_transformers_runtime("Qwen/Qwen3.5-2B") == (
        "http://127.0.0.1:17863/v1"
    )


def _component_manifest(tmp_path: Path) -> Path:
    archive = tmp_path / "runtime.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("ScanSciLocalRuntime/ScanSciLocalRuntime.exe", b"runtime-binary")
        output.writestr("ScanSciLocalRuntime/_internal/runtime.dat", b"dependency")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "local-transformers",
                "version": "1.2.0",
                "windows": {
                    "url": archive.as_uri(),
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _multipart_component_manifest(tmp_path: Path) -> Path:
    manifest = _component_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    archive = tmp_path / "runtime.zip"
    content = archive.read_bytes()
    split = max(1, len(content) // 2)
    parts = []
    for index, chunk in enumerate((content[:split], content[split:]), start=1):
        path = tmp_path / f"runtime.zip.part{index:03d}"
        path.write_bytes(chunk)
        parts.append(
            {
                "url": path.as_uri(),
                "sha256": hashlib.sha256(chunk).hexdigest(),
                "size": len(chunk),
            }
        )
    payload["windows"].pop("url")
    payload["windows"]["size"] = len(content)
    payload["windows"]["parts"] = parts
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    archive.unlink()
    return manifest


def test_runtime_component_installs_once_and_uses_active_pointer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    component = LocalRuntimeComponent(root=tmp_path / "installed", manifest_url=_component_manifest(tmp_path).as_uri())

    first = component.install()
    second = component.ensure_installed()

    assert first["installed"] is True
    assert first["version"] == "1.2.0"
    assert second == tmp_path / "installed" / "versions" / "1.2.0" / "ScanSciLocalRuntime.exe"
    assert second.read_bytes() == b"runtime-binary"


def test_runtime_component_installs_from_verified_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    component = LocalRuntimeComponent(
        root=tmp_path / "installed",
        manifest_url=_multipart_component_manifest(tmp_path).as_uri(),
    )

    result = component.install()

    assert result["installed"] is True
    assert component.ensure_installed().read_bytes() == b"runtime-binary"


def test_runtime_component_manual_zip_fallback_installs_without_a_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    manifest = _component_manifest(tmp_path)
    archive = tmp_path / "runtime.zip"
    component = LocalRuntimeComponent(root=tmp_path / "installed", manifest_url="")

    result = component.install_local([str(archive)])

    assert result["installed"] is True
    assert result["source"] == "manual"
    assert component.ensure_installed().read_bytes() == b"runtime-binary"
    assert manifest.is_file()


def test_runtime_component_switches_to_a_healthy_manifest_fallback_and_reports_channels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing.json"
    healthy = _component_manifest(tmp_path)
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {
            "frozen": True,
            "package_profile": "core-without-embedded-fallback",
            "runtime_manifest_url": missing.as_uri(),
        },
    )
    component = LocalRuntimeComponent(
        root=tmp_path / "installed",
        fallback_manifest_url=healthy.as_uri(),
    )

    result = component.install()
    report = component.check_manifest_channels()

    assert result["installed"] is True
    assert result["source"] == healthy.as_uri()
    assert result["manifest_failures"][0]["url"] == missing.as_uri()
    assert report["available"] is True
    assert report["preferred_url"] == healthy.as_uri()
    assert report["channels"][0]["valid"] is False
    assert report["channels"][1]["valid"] is True


def test_runtime_component_extracts_deep_windows_paths_without_zip_extractall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    archive = tmp_path / "runtime-long-path.zip"
    deep_member = "ScanSciLocalRuntime/_internal/" + "/".join(["third_party_component"] * 16) + "/LICENSE.txt"
    with ZipFile(archive, "w") as output:
        output.writestr("ScanSciLocalRuntime/ScanSciLocalRuntime.exe", b"runtime-binary")
        output.writestr(deep_member, b"license")
    manifest = tmp_path / "runtime-long-path.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "local-transformers",
                "version": "1.2.1",
                "windows": {
                    "url": archive.as_uri(),
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    component = LocalRuntimeComponent(root=tmp_path / "installed", manifest_url=manifest.as_uri())

    result = component.install()

    assert result["installed"] is True
    assert component.ensure_installed().read_bytes() == b"runtime-binary"


def test_runtime_component_rejects_a_second_process_install_for_the_same_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    root = tmp_path / "installed"
    first = LocalRuntimeComponent(root=root, manifest_url=_component_manifest(tmp_path).as_uri())
    second = LocalRuntimeComponent(root=root, manifest_url=_component_manifest(tmp_path).as_uri())

    with first._process_install_lock():
        with pytest.raises(RuntimeError, match="正在安装本地运行组件"):
            second.install()


def test_runtime_component_installs_in_background_with_visible_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    component = LocalRuntimeComponent(
        root=tmp_path / "installed",
        manifest_url=_multipart_component_manifest(tmp_path).as_uri(),
    )

    started = component.start_install()
    deadline = time.time() + 5
    while component.install_status()["state"] in {"queued", "installing"} and time.time() < deadline:
        time.sleep(0.02)
    finished = component.install_status()

    assert started["state"] in {"queued", "installing"}
    assert finished["state"] == "ready"
    assert finished["progress"] == 1.0
    assert component.status()["installed"] is True


def test_runtime_component_pause_resume_cancel_and_retry_are_persistent_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )

    def build_fake(component: LocalRuntimeComponent, *, job_name: str) -> tuple[threading.Event, dict[str, int]]:
        entered = threading.Event()
        calls = {"count": 0}

        def fake_install(progress_callback=None):
            calls["count"] += 1
            for index in range(20):
                entered.set()
                if progress_callback:
                    progress_callback("download", index / 20, "下载官方组件", {"completed_bytes": index, "total_bytes": 20})
                time.sleep(0.01)
            return {"job_id": job_name, "installed": True}

        monkeypatch.setattr(component, "install", fake_install)
        return entered, calls

    component = LocalRuntimeComponent(root=tmp_path / "paused", manifest_url="https://example.test/runtime.json")
    entered, calls = build_fake(component, job_name="paused")
    component.start_install()
    assert entered.wait(1)
    requested = component.pause_install()
    assert requested["state"] in {"pausing", "paused"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and component.install_status()["state"] != "paused":
        time.sleep(0.01)
    assert component.install_status()["state"] == "paused"
    resumed = component.resume_install()
    assert resumed["state"] in {"queued", "installing"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and component.install_status()["state"] != "ready":
        time.sleep(0.01)
    assert component.install_status()["state"] == "ready"
    assert calls["count"] == 2

    cancelled = LocalRuntimeComponent(root=tmp_path / "cancelled", manifest_url="https://example.test/runtime.json")
    entered_cancel, cancel_calls = build_fake(cancelled, job_name="cancelled")
    cancelled.start_install()
    assert entered_cancel.wait(1)
    requested = cancelled.cancel_install()
    assert requested["state"] in {"cancelling", "cancelled"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and cancelled.install_status()["state"] != "cancelled":
        time.sleep(0.01)
    assert cancelled.install_status()["state"] == "cancelled"
    retried = cancelled.retry_install()
    assert retried["state"] in {"queued", "installing"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and cancelled.install_status()["state"] != "ready":
        time.sleep(0.01)
    assert cancelled.install_status()["state"] == "ready"
    assert cancel_calls["count"] == 2


def test_runtime_component_download_resumes_an_existing_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "runtime.zip"
    partial = Path(f"{destination}.download")
    partial.write_bytes(b"abcd")
    observed_ranges: list[str | None] = []

    class _Response:
        headers = {"Content-Range": "bytes 4-9/10", "Content-Length": "6"}

        def __init__(self) -> None:
            self._chunks = iter((b"efghij", b""))

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, _size: int = -1) -> bytes:
            return next(self._chunks)

    def _urlopen(request, timeout=0):
        observed_ranges.append(request.get_header("Range"))
        assert timeout == 300
        return _Response()

    monkeypatch.setattr(local_runtime_component, "urlopen", _urlopen)
    progress: list[tuple[int, int]] = []

    LocalRuntimeComponent._download(
        "https://downloads.example.test/runtime.zip",
        destination,
        progress_callback=lambda received, total: progress.append((received, total)),
    )

    assert observed_ranges == ["bytes=4-"]
    assert progress[0] == (4, 10)
    assert progress[-1] == (10, 10)
    assert destination.read_bytes() == b"abcdefghij"
    assert not partial.exists()


def test_runtime_component_retries_a_connection_drop_and_resumes_the_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "runtime.zip"
    calls: list[str | None] = []

    class _Response:
        def __init__(self, payload: bytes, headers: dict[str, str], *, fail_after: bool = False) -> None:
            self._payload = payload
            self.headers = headers
            self._fail_after = fail_after
            self._read = False

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, _size: int = -1) -> bytes:
            if self._read:
                if self._fail_after:
                    raise OSError("connection reset")
                return b""
            self._read = True
            return self._payload

    def _urlopen(request, timeout=0):
        calls.append(request.get_header("Range"))
        assert timeout == 300
        if len(calls) == 1:
            return _Response(b"abcd", {"Content-Length": "10"}, fail_after=True)
        assert calls[-1] == "bytes=4-"
        return _Response(
            b"efghij",
            {"Content-Range": "bytes 4-9/10", "Content-Length": "6"},
        )

    monkeypatch.setattr(local_runtime_component, "urlopen", _urlopen)
    monkeypatch.setattr(local_runtime_component, "_RUNTIME_RETRY_DELAYS_SECONDS", (0.0, 0.0))

    LocalRuntimeComponent._download(
        "https://downloads.example.test/runtime.zip",
        destination,
        expected_size=10,
    )

    assert calls == [None, "bytes=4-"]
    assert destination.read_bytes() == b"abcdefghij"
    assert not Path(f"{destination}.download").exists()


def test_runtime_component_restores_interrupted_install_with_download_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    root = tmp_path / "installed"
    root.mkdir()
    (root / "install-job.json").write_text(
        json.dumps(
            {
                "job_id": "local-runtime",
                "state": "installing",
                "phase": "download",
                "progress": 0.4,
                "message": "下载官方组件 40%",
                "current_file": "runtime.zip",
                "completed_bytes": 40,
                "total_bytes": 100,
                "updated_at": int(time.time()) - 20,
            }
        ),
        encoding="utf-8",
    )

    component = LocalRuntimeComponent(root=root, manifest_url=_component_manifest(tmp_path).as_uri())
    restored = component.install_status()

    assert restored["state"] == "interrupted"
    assert restored["current_file"] == "runtime.zip"
    assert restored["completed_bytes"] == 40
    assert "续传" in restored["message"]
    persisted = json.loads((root / "install-job.json").read_text(encoding="utf-8"))
    assert persisted["state"] == "interrupted"


def test_interrupted_replacement_does_not_hide_the_active_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    root = tmp_path / "installed"
    executable = root / "versions" / "1.2.0" / "ScanSciLocalRuntime.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"stable-runtime")
    (root / "active.json").write_text(
        json.dumps(
            {
                "id": "local-transformers",
                "version": "1.2.0",
                "executable": str(executable.relative_to(root)),
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    (root / "install-job.json").write_text(
        json.dumps(
            {
                "job_id": "local-runtime",
                "state": "installing",
                "phase": "download",
                "progress": 0.37,
                "message": "正在下载替换版本",
                "updated_at": int(time.time()) - 10,
            }
        ),
        encoding="utf-8",
    )

    component = LocalRuntimeComponent(root=root, manifest_url="")
    status = component.status()

    assert status["installed"] is True
    assert status["mode"] == "component"
    assert status["version"] == "1.2.0"
    assert Path(status["executable"]) == executable.resolve()
    assert status["install_job"]["state"] == "interrupted"


def test_runtime_component_rejects_corrupt_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    manifest = _multipart_component_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    (tmp_path / "runtime.zip.part001").write_bytes(b"corrupt")
    component = LocalRuntimeComponent(root=tmp_path / "installed", manifest_url=manifest.as_uri())

    with pytest.raises(RuntimeError, match="分片校验失败"):
        component.install()


def test_core_runtime_requires_a_release_component_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    component = LocalRuntimeComponent(root=tmp_path, manifest_url="")

    with pytest.raises(RuntimeError, match="下载清单"):
        component.ensure_installed()


def test_packaged_core_uses_public_runtime_manifest_fallback_when_build_info_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core", "runtime_manifest_url": ""},
    )

    component = LocalRuntimeComponent(root=tmp_path)

    assert component.manifest_url == local_runtime_component.DEFAULT_RUNTIME_MANIFEST_URL
    assert component.status()["install_available"] is True


def test_core_runtime_never_installs_from_a_manifest_while_only_checking_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core"},
    )
    component = LocalRuntimeComponent(root=tmp_path / "installed", manifest_url=_component_manifest(tmp_path).as_uri())
    monkeypatch.setattr(component, "install", lambda: (_ for _ in ()).throw(AssertionError("must not download")))

    with pytest.raises(RuntimeError, match="设置 → 本地模型确认安装"):
        component.ensure_installed()


def test_source_runtime_is_not_marked_ready_without_its_actual_inference_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_runtime_component, "current_build_info", lambda: {"frozen": False})
    monkeypatch.setattr(local_runtime_component, "find_spec", lambda _module: None)
    component = LocalRuntimeComponent(root=tmp_path / "installed")

    assert component.status()["installed"] is False
    assert component.status()["mode"] == "missing"
    with pytest.raises(RuntimeError, match="设置 → 本地模型查看组件状态"):
        component.ensure_installed()


def test_source_runtime_server_exposes_health_without_loading_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    monkeypatch.setattr(
        "scansci_html.local_runtime_server.installed_models",
        lambda: [{"id": "Qwen/Test", "path": str(snapshot), "ready": True, "format": "transformers"}],
    )
    runtime = LocalRuntimeServer(port=0)
    runtime.start("Qwen/Test")
    try:
        with urlopen(f"http://127.0.0.1:{runtime.port}/health", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["status"] == "ok"
        assert payload["component"] == "local-transformers"
        assert payload["version"] == local_runtime_component.COMPONENT_VERSION
        assert payload["model"] == "Qwen/Test"
        assert payload["loaded"] is False
        assert "cuda_available" in payload
        assert payload["device"] in {"cpu", "cuda:0", "pending", "unavailable"}
    finally:
        runtime.shutdown()


def test_webapp_does_not_mask_embedded_runtime_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _component_manifest(tmp_path).as_uri()
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {"frozen": True, "package_profile": "core", "runtime_manifest_url": manifest},
    )

    app = NotebookWebApp(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")

    assert app.local_runtime.manifest_url == manifest
    assert app.local_runtime.status()["install_available"] is True


def test_webapp_prefers_embedded_runtime_manifest_over_app_update_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_manifest = _component_manifest(tmp_path).as_uri()
    app_update_manifest = (tmp_path / "app-update.json").as_uri()
    monkeypatch.setattr(
        local_runtime_component,
        "current_build_info",
        lambda: {
            "frozen": True,
            "package_profile": "core",
            "runtime_manifest_url": runtime_manifest,
        },
    )

    app = NotebookWebApp(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
        update_service=AppUpdateService(manifest_url=app_update_manifest),
    )

    assert app.local_runtime.manifest_url == runtime_manifest
