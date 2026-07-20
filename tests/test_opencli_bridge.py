import json
from pathlib import Path
from unittest.mock import patch

from scansci_html.browser_config import BrowserIdentityConfig
from scansci_html.opencli_bridge import (
    build_opencli_bridge_diagnostics,
    check_opencli_daemon,
    inspect_opencli_extension_dir,
)


def write_opencli_extension(base: Path) -> Path:
    extension_dir = base / "opencli-1.0.20"
    (extension_dir / "dist").mkdir(parents=True)
    (extension_dir / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "name": "OpenCLI",
                "version": "1.0.20",
                "description": "Browser automation bridge for OpenCLI.",
                "permissions": [
                    "debugger",
                    "tabs",
                    "cookies",
                    "activeTab",
                    "alarms",
                    "storage",
                    "downloads",
                ],
                "host_permissions": ["<all_urls>"],
                "background": {"service_worker": "dist/background.js"},
            }
        ),
        encoding="utf-8",
    )
    (extension_dir / "dist" / "background.js").write_text(
        """
        const DAEMON_HOST = "localhost";
        const DAEMON_PORT = 19825;
        if (message.type === "getStatus") {}
        switch (action) {
          case "exec": break;
          case "navigate": break;
          case "cookies": break;
          case "screenshot": break;
          case "wait-download": break;
          case "unknown-action": break;
        }
        """,
        encoding="utf-8",
    )
    return extension_dir


def test_inspect_opencli_extension_reads_manifest_and_actions(tmp_path: Path):
    extension_dir = write_opencli_extension(tmp_path)

    info = inspect_opencli_extension_dir(extension_dir).to_dict()

    assert info["exists"] is True
    assert info["manifest_ok"] is True
    assert info["name"] == "OpenCLI"
    assert info["version"] == "1.0.20"
    assert info["required_permissions_present"] is True
    assert info["daemon_host"] == "localhost"
    assert info["daemon_port"] == 19825
    assert info["websocket_url"] == "ws://localhost:19825/ext"
    assert info["status_message_supported"] is True
    assert "exec" in info["command_actions"]
    assert "wait-download" in info["command_actions"]
    assert "unknown-action" not in info["command_actions"]


def test_missing_extension_reports_error(tmp_path: Path):
    info = inspect_opencli_extension_dir(tmp_path / "missing").to_dict()

    assert info["exists"] is False
    assert "does not exist" in info["error"]


def test_check_opencli_daemon_reads_ping_and_status():
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/ping"):
            return FakeResponse({"ok": True})
        if request.full_url.endswith("/status"):
            return FakeResponse(
                {
                    "ok": True,
                    "daemonVersion": "1.8.4",
                    "extensionConnected": True,
                    "extensionVersion": "1.0.20",
                    "contextId": "ctx-test",
                    "profiles": [{"name": "default"}],
                }
            )
        raise AssertionError(request.full_url)

    with patch("scansci_html.opencli_bridge.urlopen", side_effect=fake_urlopen):
        result = check_opencli_daemon(timeout_sec=0.1)

    assert result["ping_ok"] is True
    assert result["status_ok"] is True
    assert result["extension_connected"] is True
    assert result["daemon_version"] == "1.8.4"
    assert result["extension_version"] == "1.0.20"
    assert result["context_id"] == "ctx-test"
    assert len(result["profiles"]) == 1


def test_build_diagnostics_reports_connected_without_runtime_probe(tmp_path: Path):
    extension_dir = write_opencli_extension(tmp_path)
    cfg = BrowserIdentityConfig.from_values(browser_extension_dirs=str(extension_dir))
    daemon = {
        "ping_ok": True,
        "status_ok": True,
        "extension_connected": True,
        "daemon_version": "1.8.4",
        "extension_version": "1.0.20",
        "context_id": "ctx-test",
        "profiles": [],
    }

    with patch("scansci_html.opencli_bridge.check_opencli_daemon", return_value=daemon):
        diagnostics = build_opencli_bridge_diagnostics(cfg)

    assert diagnostics["opencli_configured"] is True
    assert diagnostics["configured_extension_count"] == 1
    assert diagnostics["verdict"] == "connected"
