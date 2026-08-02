"""Tests for the Tor circuit-rotation runtime.

Every test mocks network/process operations — no real Tor is launched.
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scansci_html import tor_runtime


def _isolated_workspace(tmp_path: Path) -> Path:
    """Workspace whose .scansci/tor dir is unique to this test."""
    ws = tmp_path / "ws" / "workspace.sqlite"
    ws.parent.mkdir(parents=True, exist_ok=True)
    return ws


# --------------------------------------------------------------------------- #
# torrc + paths
# --------------------------------------------------------------------------- #


def test_write_torrc_enables_control_port_and_cookie_auth(tmp_path):
    ws = _isolated_workspace(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws)
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "SocksPort 9050" in content
    assert "ControlPort 9051" in content
    assert "CookieAuthentication 1" in content
    assert "CookieAuthFile" in content
    assert "DataDirectory" in content


def test_socks_proxy_url_uses_remote_dns(tmp_path):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    # socks5h (not socks5) so DNS resolves through Tor, avoiding leaks.
    assert manager.socks_proxy_url == "socks5h://127.0.0.1:9050"


# --------------------------------------------------------------------------- #
# ensure_tor — reuse existing, launch new, fail soft
# --------------------------------------------------------------------------- #


def test_ensure_tor_reuses_existing_listener_without_owning(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    # Simulate a Tor already listening on the SOCKS port.
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda _h, _p, **_k: True)
    assert manager.ensure_tor() is True
    assert manager._owned is False  # we must NOT kill an external Tor
    assert manager._process is None


def test_ensure_tor_launches_process_when_port_free(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws)
    # Pretend the binary already exists so no download is attempted.
    fake_binary = tmp_path / "tor.exe"
    fake_binary.write_bytes(b"")
    monkeypatch.setattr(tor_runtime, "_tor_binary_path", lambda _ws: fake_binary)
    # Ports start closed; after one sleep tick both SOCKS and control open and
    # stem reports a fully-bootstrapped circuit (PROGRESS=100).
    state = {"ready": False}

    def fake_open(_h, port, **_k):
        return state["ready"]  # both 9050 and 9051 open together

    fake_controller = MagicMock()
    fake_controller.__enter__ = lambda self: self
    fake_controller.__exit__ = lambda *a: False
    fake_controller.get_info.return_value = "NOTICE BOOTSTRAP PROGRESS=100 TAG=done"
    fake_stem_control = MagicMock()
    fake_stem_control.Controller.from_port.return_value = fake_controller
    import sys

    monkeypatch.setitem(sys.modules, "stem.control", fake_stem_control)

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # alive
    monkeypatch.setattr(tor_runtime, "_is_port_open", fake_open)
    monkeypatch.setattr(tor_runtime.subprocess, "Popen", lambda *a, **k: fake_proc)
    monkeypatch.setattr(tor_runtime.time, "sleep", lambda _s: state.__setitem__("ready", True))
    # Cookie auth is auto-detected by stem's bare authenticate().
    manager.cookie_path.parent.mkdir(parents=True, exist_ok=True)
    manager.cookie_path.write_bytes(b"x")
    assert manager.ensure_tor() is True
    assert manager._owned is True
    assert manager._process is fake_proc


def test_ensure_tor_fails_soft_when_download_missing(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: False)
    monkeypatch.setattr(tor_runtime, "_tor_binary_path", lambda _ws: Path("/nonexistent/tor"))
    monkeypatch.setattr(tor_runtime, "download_tor_bundle", lambda _ws, **_k: None)
    assert manager.ensure_tor() is False
    assert manager._process is None


def test_ensure_tor_detects_early_process_death(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws)
    fake_binary = tmp_path / "tor.exe"
    fake_binary.write_bytes(b"")
    monkeypatch.setattr(tor_runtime, "_tor_binary_path", lambda _ws: fake_binary)
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: False)
    dead = MagicMock()
    dead.poll.return_value = 1  # exited immediately
    dead.stderr = MagicMock()
    dead.stderr.read.return_value = b"config error"
    monkeypatch.setattr(tor_runtime.subprocess, "Popen", lambda *a, **k: dead)
    assert manager.ensure_tor() is False


# --------------------------------------------------------------------------- #
# rotate_circuit — NEWNYM via stem
# --------------------------------------------------------------------------- #


def test_rotate_circuit_sends_newnym_and_sleeps_cooldown(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: True)
    # Fake the stem Controller context manager.
    fake_controller = MagicMock()
    fake_controller.__enter__ = lambda self: self
    fake_controller.__exit__ = lambda *a: False

    fake_stem_signal = MagicMock()
    fake_stem_controller = MagicMock()
    fake_stem_controller.from_port.return_value = fake_controller

    fake_stem = types.ModuleType("stem")
    fake_stem.Signal = types.SimpleNamespace(NEWNYM="NEWNYM")
    fake_stem_control = types.ModuleType("stem.control")
    fake_stem_control.Controller = fake_stem_controller

    sleeps: list[float] = []
    monkeypatch.setattr(tor_runtime.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setitem(__import__("sys").modules, "stem", fake_stem)
    monkeypatch.setitem(__import__("sys").modules, "stem.control", fake_stem_control)

    assert manager.rotate_circuit(cooldown=10.0) is True
    fake_controller.authenticate.assert_called_once()
    fake_controller.signal.assert_called_once_with("NEWNYM")
    assert sleeps == [10.0]  # honored the rate-limit cooldown


def test_rotate_circuit_returns_false_when_control_port_closed(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: False)
    assert manager.rotate_circuit() is False


def test_rotate_circuit_returns_false_when_stem_not_installed(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: True)
    builtins = __import__("builtins")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("stem"):
            raise ImportError("no stem")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert manager.rotate_circuit() is False


# --------------------------------------------------------------------------- #
# verify_rotation — authoritative IP-change check
# --------------------------------------------------------------------------- #


def test_verify_rotation_detects_real_ip_change(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    ips = iter(["1.1.1.1", "2.2.2.2"])
    monkeypatch.setattr(manager, "get_exit_ip", lambda **_k: next(ips))
    monkeypatch.setattr(manager, "rotate_circuit", lambda **_k: True)
    result = manager.verify_rotation()
    assert result["rotated"] is True
    assert result["before"] == "1.1.1.1"
    assert result["after"] == "2.2.2.2"


def test_verify_rotation_flags_same_ip(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    monkeypatch.setattr(manager, "get_exit_ip", lambda **_k: "1.1.1.1")
    monkeypatch.setattr(manager, "rotate_circuit", lambda **_k: True)
    result = manager.verify_rotation()
    assert result["rotated"] is False
    assert "相同" in result["error"]


def test_verify_rotation_reports_when_ip_unreachable(tmp_path, monkeypatch):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    monkeypatch.setattr(manager, "get_exit_ip", lambda **_k: None)
    result = manager.verify_rotation()
    assert result["rotated"] is False
    assert result["before"] is None


# --------------------------------------------------------------------------- #
# stop — only kills processes we own
# --------------------------------------------------------------------------- #


def test_stop_does_not_kill_external_tor(tmp_path):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    manager._owned = False  # external Tor, not ours
    proc = MagicMock()
    manager._process = proc
    manager.stop()
    proc.terminate.assert_not_called()


def test_stop_terminates_owned_process(tmp_path):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    manager._owned = True
    manager._process = proc
    manager.stop()
    proc.terminate.assert_called_once()
    assert manager._owned is False


# --------------------------------------------------------------------------- #
# pluggable transports (obfs4 + snowflake) — lyrebird + pt_config.json
# --------------------------------------------------------------------------- #

_PT_CONFIG = {
    "recommendedDefault": "obfs4",
    "pluggableTransports": {
        "lyrebird": "ClientTransportPlugin meek_lite,obfs2,obfs3,obfs4,scramblesuit,webtunnel exec ${pt_path}lyrebird.exe",
    },
    "bridges": {
        "obfs4": [
            "obfs4 37.218.245.14:38224 D9A82D2F9C2F65A18407B1D2B764F130847F8B5D cert=bjRaMrr1BRiAW8IE9U5z27fQaYgOhX1UCmOpg2pFpoMvo6ZgQMzLsaTzzQNTlm7hNcb+Sg iat-mode=0",
            "obfs4 209.148.46.65:443 74FAD13168806246602538555B5521A0383A1875 cert=ssH+9rP8dG2NLDN2XuFw63hIO/9MNNinLmxQDpVa+7kTOa9/m+tGWT1SmSYpQ9uTBGa6Hw iat-mode=0",
        ],
        "snowflake": [
            "snowflake 192.0.2.3:80 2B280B23E1107BB62ABFC40DDCC8824814F80A72 fingerprint=2B280B23E1107BB62ABFC40DDCC8824814F80A72 url=https://1098762253.rsc.cdn77.org/ fronts=app.datapacket.com,www.datapacket.com ice=stun:stun.epygi.com:3478 utls-imitate=hellorandomizedalpn",
        ],
    },
}


def _install_fake_bundle(tmp_path: Path) -> Path:
    """Create a fake extracted Tor bundle (tor.exe + lyrebird + pt_config.json)."""
    import json

    ws = _isolated_workspace(tmp_path)
    pt_dir = tor_runtime._pluggable_transports_dir(ws)
    pt_dir.mkdir(parents=True, exist_ok=True)
    (pt_dir / "lyrebird.exe").write_bytes(b"fake-pt-binary")
    (pt_dir / "pt_config.json").write_text(json.dumps(_PT_CONFIG), encoding="utf-8")
    tor_dir = tor_runtime._tor_binary_path(ws).parent
    tor_dir.mkdir(parents=True, exist_ok=True)
    (tor_dir / "tor.exe").write_bytes(b"fake-tor")
    return ws


def test_read_builtin_bridges_parses_pt_config(tmp_path):
    ws = _install_fake_bundle(tmp_path)
    bridges = tor_runtime._read_builtin_bridges(ws)
    assert len(bridges) == 2
    assert all(line.startswith("obfs4 ") for line in bridges)


def test_read_builtin_bridges_returns_empty_when_missing(tmp_path):
    ws = _isolated_workspace(tmp_path)  # no bundle installed
    assert tor_runtime._read_builtin_bridges(ws) == []


def test_lyrebird_path_found_and_none_when_absent(tmp_path):
    ws = _install_fake_bundle(tmp_path)
    assert tor_runtime._lyrebird_path(ws) is not None
    assert tor_runtime._lyrebird_path(_isolated_workspace(tmp_path / "other")) is None


def test_write_torrc_with_obfs4_includes_transport_block(tmp_path):
    ws = _install_fake_bundle(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws, transport="obfs4")
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "UseBridges 1" in content
    assert "ClientTransportPlugin obfs4 exec" in content
    assert "pluggable_transports/lyrebird.exe" in content
    assert "Bridge obfs4 37.218.245.14" in content
    assert "Bridge obfs4 209.148.46.65" in content


def test_write_torrc_with_snowflake_uses_cdn_fronted_bridges(tmp_path):
    """Snowflake routes through CDN domain-fronting, not direct bridge IPs."""
    ws = _install_fake_bundle(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws, transport="snowflake")
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "UseBridges 1" in content
    assert "ClientTransportPlugin snowflake exec" in content
    assert "pluggable_transports/lyrebird.exe" in content
    assert "Bridge snowflake 192.0.2.3" in content
    assert "fronts=app.datapacket.com" in content
    # obfs4 bridges must NOT appear under the snowflake transport.
    assert "obfs4" not in content


def test_write_torrc_transport_none_has_no_bridge_lines(tmp_path):
    """Regression: transport=none must not emit any bridge directives."""
    ws = _install_fake_bundle(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws, transport="none")
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "UseBridges" not in content
    assert "ClientTransportPlugin" not in content
    assert "Bridge " not in content


def test_use_bridges_backcompat_maps_to_obfs4(tmp_path):
    """The older use_bridges=True flag still works and selects obfs4."""
    ws = _install_fake_bundle(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws, use_bridges=True)
    assert manager.transport == "obfs4"
    assert manager.use_bridges is True


def test_transport_invalid_falls_back_to_none(tmp_path):
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path), transport="bogus")
    assert manager.transport == "none"


# --------------------------------------------------------------------------- #
# upstream proxy — route Tor through the user's local proxy (Clash/V2Ray/...)
# --------------------------------------------------------------------------- #


def test_detect_local_proxy_finds_listening_port(monkeypatch):
    """detect_local_proxy returns the first open local proxy port."""
    open_ports = {7890, 1080}

    def fake_open(_host, port, **_k):
        return port in open_ports

    monkeypatch.setattr(tor_runtime, "_is_port_open", fake_open)
    assert tor_runtime.detect_local_proxy() == "127.0.0.1:7890"


def test_detect_local_proxy_returns_none_when_nothing_listening(monkeypatch):
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: False)
    assert tor_runtime.detect_local_proxy() is None


def test_upstream_proxy_auto_detected_when_none_given(tmp_path, monkeypatch):
    monkeypatch.setattr(tor_runtime, "detect_local_proxy", lambda: "127.0.0.1:7890")
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path))
    assert manager.upstream_proxy == "127.0.0.1:7890"


def test_upstream_proxy_explicit_overrides_auto(tmp_path, monkeypatch):
    monkeypatch.setattr(tor_runtime, "detect_local_proxy", lambda: "127.0.0.1:7890")
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path), upstream_proxy="127.0.0.1:10808")
    assert manager.upstream_proxy == "127.0.0.1:10808"


def test_upstream_proxy_disabled_with_false(tmp_path, monkeypatch):
    monkeypatch.setattr(tor_runtime, "detect_local_proxy", lambda: "127.0.0.1:7890")
    manager = tor_runtime.TorCircuitManager(_isolated_workspace(tmp_path), upstream_proxy=False)
    assert manager.upstream_proxy == ""


def test_write_torrc_includes_httpsproxy_when_upstream_set(tmp_path, monkeypatch):
    monkeypatch.setattr(tor_runtime, "detect_local_proxy", lambda: "127.0.0.1:7890")
    ws = _install_fake_bundle(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws, transport="none")
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "HTTPSProxy 127.0.0.1:7890" in content


def test_write_torrc_omits_httpsproxy_when_no_proxy(tmp_path, monkeypatch):
    monkeypatch.setattr(tor_runtime, "detect_local_proxy", lambda: None)
    ws = _install_fake_bundle(tmp_path)
    manager = tor_runtime.TorCircuitManager(ws, transport="none")
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "HTTPSProxy" not in content


def test_write_torrc_user_supplied_bridges_override_builtin(tmp_path):
    ws = _install_fake_bundle(tmp_path)
    custom = ["obfs4 1.2.3.4:444 FINGERPRINT cert=CUSTOMCERT iat-mode=0"]
    manager = tor_runtime.TorCircuitManager(ws, transport="obfs4", bridges=custom)
    manager._write_torrc()
    content = manager.torrc_path.read_text(encoding="utf-8")
    assert "1.2.3.4:444" in content
    assert "CUSTOMCERT" in content
    assert "37.218.245.14" not in content


def test_ensure_tor_fails_soft_when_lyrebird_missing_but_transport_requested(tmp_path, monkeypatch):
    """If a transport is requested but lyrebird is absent, fail rather than launch."""
    ws = _isolated_workspace(tmp_path)
    fake_binary = tmp_path / "tor.exe"
    fake_binary.write_bytes(b"")
    monkeypatch.setattr(tor_runtime, "_tor_binary_path", lambda _ws: fake_binary)
    monkeypatch.setattr(tor_runtime, "_lyrebird_path", lambda _ws: None)
    monkeypatch.setattr(tor_runtime, "_is_port_open", lambda *_a, **_k: False)
    manager = tor_runtime.TorCircuitManager(ws, transport="snowflake")
    assert manager.ensure_tor() is False
    assert manager._process is None
