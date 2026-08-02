"""ScanSci-managed Tor runtime with circuit rotation (NEWNYM).

This module owns a single Tor process launched with a control port so that
circuit identity can be rotated on demand between batch downloads. It is the
only layer that talks to Tor's control protocol; everything downstream
(``research_tools.download_paper``) just receives a ``TOR_PROXY`` env var
pointing at this process's SOCKS port.

Design notes:
- Fixed ports (SocksPort 9050, ControlPort 9051) so scansci-pdf subprocesses
  can reuse the same endpoint and stem can find the controller.
- Every public method is fail-soft: if Tor cannot start or the controller is
  unreachable, the method returns ``None``/``False`` and the caller falls back
  to a direct connection. Batch downloads must never abort because Tor failed.
- Network/process operations are isolated behind small helpers so tests can
  monkeypatch them without a real Tor install.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import shutil
import socket
import stat
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

# Fixed endpoints — see module docstring.
SOCKS_PORT = 9050
CONTROL_PORT = 9051
TOR_VERSION = "15.0.19"
# The Expert Bundle lives under a versioned torbrowser/ subdirectory. The archive
# mirror is the canonical host; dist.torproject.org redirects there.
TOR_DOWNLOAD_MIRRORS = (
    "https://archive.torproject.org/tor-package-archive/torbrowser",
    "https://dist.torproject.org/tor-package-archive/torbrowser",
)
# NEWNYM is rate-limited by Tor to one new circuit per ~10s. Sleeping just past
# that window is the difference between a real rotation and a silent no-op.
NEWNYM_COOLDOWN_SECONDS = 10.0
# Bootstrap can take 20-60s on a cold start; obfs4 bridges are slower still
# (handshake over an obfuscated channel), so allow more room when bridging.
BOOTSTRAP_TIMEOUT_SECONDS = 90.0
BOOTSTRAP_TIMEOUT_BRIDGES_SECONDS = 180.0
# Snowflake rendezvous (WebRTC + broker + CDN fronting) can take even longer.
BOOTSTRAP_TIMEOUT_SNOWFLAKE_SECONDS = 240.0
# Supported pluggable transports. "none" = direct Tor relay connection.
# Both obfs4 and snowflake run through the bundled lyrebird.exe — no extra binary.
TRANSPORTS = ("none", "obfs4", "snowflake")
IP_CHECK_URL = "https://api.ipify.org"


def _tor_root(workspace: str | Path) -> Path:
    """Directory holding the extracted Tor bundle and runtime data."""
    return Path(workspace).resolve().parent / ".scansci" / "tor"


def _tor_binary_path(workspace: str | Path) -> Path:
    exe = "tor.exe" if platform.system() == "Windows" else "tor"
    return _tor_root(workspace) / "tor" / exe


def _pluggable_transports_dir(workspace: str | Path) -> Path:
    """Directory holding lyrebird.exe and the bundled bridge config."""
    return _tor_root(workspace) / "tor" / "pluggable_transports"


def _lyrebird_path(workspace: str | Path) -> Path | None:
    """Absolute path to the obfs4 pluggable-transport binary, if present.

    Tor's Expert Bundle ships ``lyrebird.exe`` (the modern obfs4proxy
    replacement) inside ``pluggable_transports/``. We point tor at it via an
    absolute path so no global PATH install is ever required.
    """
    exe = "lyrebird.exe" if platform.system() == "Windows" else "lyrebird"
    candidate = _pluggable_transports_dir(workspace) / exe
    return candidate if candidate.exists() else None


def _read_builtin_bridges(workspace: str | Path, transport: str = "obfs4") -> list[str]:
    """Read bridge lines Tor's bundle ships in ``pt_config.json``.

    These rotate with each Tor release and are a reliable cold-start set; we do
    not need to hit ``bridges.torproject.org`` (rate-limited, often captcha'd)
    on first boot. Returns an empty list if the file is missing or malformed.
    """
    config_path = _pluggable_transports_dir(workspace) / "pt_config.json"
    if not config_path.exists():
        return []
    try:
        import json

        data = json.loads(config_path.read_text(encoding="utf-8"))
        bridges = data.get("bridges", {}).get(transport, [])
        return [str(line).strip() for line in bridges if str(line).strip()]
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to read pt_config.json bridges: %s", exc)
        return []


# Common local-proxy ports used by Clash/Mihomo, V2Ray, Shadowsocks, etc.
# Scanned so Tor can route through the user's existing proxy without requiring
# manual configuration — the single most reliable path on restricted networks.
_LOCAL_PROXY_PORTS = (7890, 7897, 10808, 1080, 8080, 8888, 2080)


def detect_local_proxy() -> str | None:
    """Return ``host:port`` of a listening local HTTP proxy, or None.

    Many users run a system proxy (Clash, V2Ray, ...) that already reaches the
    open internet. Routing Tor through it via torrc ``HTTPSProxy`` lets Tor
    bootstrap even where direct relays, obfs4 bridge IPs, and WebRTC are all
    blocked. We probe localhost ports rather than trusting env vars because Tor
    does not honor ``HTTPS_PROXY`` itself.
    """
    for port in _LOCAL_PROXY_PORTS:
        if _is_port_open("127.0.0.1", port, timeout=0.3):
            return f"127.0.0.1:{port}"
    return None


def _download_filename() -> str:
    """Return the Expert Bundle filename for this platform.

    Note: as of Tor 15.x the Windows bundle is also distributed as .tar.gz (not
    .zip), and the filename layout is ``tor-expert-bundle-<os>-<arch>-<ver>``.
    """
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return f"tor-expert-bundle-windows-x86_64-{TOR_VERSION}.tar.gz"
    if system == "Darwin":
        suffix = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"tor-expert-bundle-macos-{suffix}-{TOR_VERSION}.tar.gz"
    suffix = "aarch64" if machine in ("aarch64", "arm64") else "x86_64"
    return f"tor-expert-bundle-linux-{suffix}-{TOR_VERSION}.tar.gz"


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def download_tor_bundle(workspace: str | Path, *, progress_hook=None) -> Path | None:
    """Download and extract the Tor Expert Bundle. Returns the tor binary path.

    Idempotent: if the binary already exists, returns immediately.
    """
    binary = _tor_binary_path(workspace)
    if binary.exists():
        return binary
    root = _tor_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    filename = _download_filename()
    import requests

    proxies = {}
    upstream = os.environ.get("HTTPS_PROXY") or os.environ.get("SCANSCI_PDF_PROXY")
    if upstream:
        proxies = {"http": upstream, "https": upstream}
    last_error = ""
    for mirror in TOR_DOWNLOAD_MIRRORS:
        url = f"{mirror}/{TOR_VERSION}/{filename}"
        try:
            resp = requests.get(url, timeout=300, stream=True, proxies=proxies or None)
            if resp.status_code != 200:
                last_error = f"{url} -> HTTP {resp.status_code}"
                continue
            buffer = io.BytesIO()
            for chunk in resp.iter_content(8192):
                if chunk:
                    buffer.write(chunk)
                    if progress_hook:
                        progress_hook(buffer.tell())
            buffer.seek(0)
            if filename.endswith(".zip"):
                with zipfile.ZipFile(buffer) as zf:
                    zf.extractall(root)
            else:
                with tarfile.open(fileobj=buffer, mode="r:gz") as tf:
                    tf.extractall(root)
            if binary.exists():
                if platform.system() != "Windows":
                    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
                log.info("Tor bundle extracted to %s", root)
                return binary
            last_error = f"extracted but {binary} not found"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{url} -> {type(exc).__name__}: {exc}"
    log.error("Failed to download Tor: %s", last_error)
    return None


class TorCircuitManager:
    """Owns one Tor process and rotates its circuit via NEWNYM.

    Usage::

        manager = TorCircuitManager(workspace)
        if manager.ensure_tor():
            ip_before = manager.get_exit_ip()
            manager.rotate_circuit()
            ip_after = manager.get_exit_ip()
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        socks_port: int = SOCKS_PORT,
        control_port: int = CONTROL_PORT,
        transport: str = "none",
        bridges: list[str] | None = None,
        use_bridges: bool | None = None,
        upstream_proxy: str | bool | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.socks_port = socks_port
        self.control_port = control_port
        # Back-compat: the older `use_bridges=True` flag means obfs4.
        if use_bridges and transport == "none":
            transport = "obfs4"
        self.transport = transport if transport in TRANSPORTS else "none"
        # Pluggable transports route Tor through the bundled lyrebird.exe — no
        # global install needed. Snowflake (CDN domain-fronting) works where
        # direct relays AND obfs4 bridge IPs are both blocked.
        self.bridges = bridges  # None => fall back to bundle's built-in lines.
        # Route Tor's own relay connections through an upstream HTTP proxy.
        # This is the most reliable path on networks that block Tor at every
        # layer (TCP/obfs4/WebRTC) — the user's existing proxy (Clash, V2Ray,
        # ...) already reaches the open internet. None = auto-detect; the empty
        # string = explicit disable.
        if upstream_proxy is None or upstream_proxy is True:
            self.upstream_proxy = detect_local_proxy() or ""
        elif upstream_proxy is False:
            self.upstream_proxy = ""
        else:
            self.upstream_proxy = str(upstream_proxy).strip()
        self.root = _tor_root(workspace)
        self.torrc_path = self.root / "torrc"
        self.cookie_path = self.root / "control_auth_cookie"
        self.data_dir = self.root / "data"
        self._process: subprocess.Popen | None = None
        self._owned = False  # True only if *we* launched it (so we stop it).

    @property
    def use_bridges(self) -> bool:
        """Back-compat shim: True when a pluggable transport is active."""
        return self.transport != "none"

    # -- properties --------------------------------------------------------

    @property
    def socks_proxy_url(self) -> str:
        return f"socks5h://127.0.0.1:{self.socks_port}"

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # -- lifecycle ---------------------------------------------------------

    def ensure_tor(self, *, bootstrap_timeout: float | None = None) -> bool:
        """Start Tor if it is not already listening. Returns True if usable.

        If something is already bound to the SOCKS port we assume it is a Tor
        we can drive (e.g. a previous run, or a user-started Tor Browser) and
        reuse it rather than failing on a port conflict.
        """
        if bootstrap_timeout is None:
            # Pluggable transports need a longer handshake window than direct
            # relays; snowflake's WebRTC rendezvous is the slowest.
            if self.transport == "snowflake":
                bootstrap_timeout = BOOTSTRAP_TIMEOUT_SNOWFLAKE_SECONDS
            elif self.transport != "none":
                bootstrap_timeout = BOOTSTRAP_TIMEOUT_BRIDGES_SECONDS
            else:
                bootstrap_timeout = BOOTSTRAP_TIMEOUT_SECONDS
        if _is_port_open("127.0.0.1", self.socks_port):
            # An external Tor is already up; adopt it but don't own it.
            self._owned = False
            log.info("Reusing existing Tor listener on SOCKS %d", self.socks_port)
            return True
        binary = _tor_binary_path(self.workspace)
        if not binary.exists():
            binary = download_tor_bundle(self.workspace)
            if not binary:
                return False
        # A pluggable transport requires the lyrebird binary in the bundle;
        # without it tor would fail at handshake. Fail soft rather than launch.
        if self.transport != "none" and _lyrebird_path(self.workspace) is None:
            log.error("%s transport requested but lyrebird.exe is missing from the bundle", self.transport)
            return False
        self._write_torrc()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(binary), "-f", str(self.torrc_path)]
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation,
            )
            self._owned = True
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to launch Tor: %s", exc)
            return False
        return self._wait_for_socks(bootstrap_timeout)

    def _write_torrc(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        # CookieAuthFile / DataDirectory must use OS-native separators for tor.
        lines = [
            f"SocksPort {self.socks_port}",
            f"ControlPort {self.control_port}",
            "CookieAuthentication 1",
            f"CookieAuthFile {self.cookie_path}",
            f"DataDirectory {self.data_dir}",
            "AvoidDiskWrites 1",
            "Log notice stdout",
        ]
        if self.transport != "none":
            bridge_block = self._bridge_lines()
            if bridge_block:
                lines.extend(bridge_block)
            else:
                log.warning("%s transport requested but no bridge lines available; falling back to direct Tor", self.transport)
        # Route Tor's own relay connections through an upstream HTTP proxy.
        # This is what makes Tor reachable when the physical network blocks
        # direct relay IPs — the user's proxy already has a path out.
        if self.upstream_proxy:
            lines.append(f"HTTPSProxy {self.upstream_proxy}")
        self.torrc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _bridge_lines(self) -> list[str]:
        """Build the torrc block enabling a pluggable transport via lyrebird.

        Supports obfs4 (obfuscated bridges) and snowflake (CDN domain-fronting,
        which works where direct relays AND obfs4 bridge IPs are both blocked).
        Returns an empty list if the transport binary or bridge lines are
        unavailable, so the caller can fall back to a direct connection.
        """
        lyrebird = _lyrebird_path(self.workspace)
        if lyrebird is None:
            log.error("lyrebird (%s transport) not found in bundle", self.transport)
            return []
        # pt_config.json groups bridge lines by transport name.
        bridge_list = self.bridges if self.bridges else _read_builtin_bridges(self.workspace, self.transport)
        if not bridge_list:
            log.error("no %s bridge lines available (pt_config.json missing?)", self.transport)
            return []
        # tor accepts forward slashes on Windows and they avoid backslash
        # escaping pitfalls; use the resolved absolute path verbatim.
        lyrebird_posix = str(lyrebird).replace("\\", "/")
        block = [
            "UseBridges 1",
            f"ClientTransportPlugin {self.transport} exec {lyrebird_posix}",
        ]
        for bridge in bridge_list:
            block.append(f"Bridge {bridge}")
        return block

    def _wait_for_socks(self, timeout: float) -> bool:
        """Wait until Tor is accepting SOCKS connections AND has bootstrapped a
        circuit. The SOCKS port opens within ~2s but the first usable circuit
        (BOOTSTRAPPED 100) can take 20-60s; checking only the port returns
        success before Tor can actually route traffic.
        """
        deadline = time.monotonic() + timeout
        socks_ready = False
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read().decode("utf-8", errors="replace")[:500]
                log.error("Tor exited early (code %s): %s", self._process.returncode, stderr)
                self._process = None
                return False
            if not socks_ready and _is_port_open("127.0.0.1", self.socks_port):
                socks_ready = True
                log.info("Tor SOCKS port ready on %d; waiting for circuit…", self.socks_port)
            if socks_ready:
                # Once the control port is up, confirm bootstrap reached 100%.
                if _is_port_open("127.0.0.1", self.control_port):
                    try:
                        from stem.control import Controller

                        with Controller.from_port(port=self.control_port) as controller:
                            # CookieAuthentication 1 is in the torrc; stem's
                            # bare authenticate() auto-detects and reads the
                            # cookie file. Do NOT pass cookie_path= (stem's
                            # authenticate() takes no such kwarg and raises).
                            controller.authenticate()
                            phase = controller.get_info("status/bootstrap-phase", "")
                            if "PROGRESS=100" in phase:
                                log.info("Tor circuit bootstrapped")
                                return True
                    except Exception:  # noqa: BLE001 - controller not ready yet
                        pass
            time.sleep(1.0)
        log.error("Tor bootstrap timed out after %.0fs", timeout)
        self.stop()
        return False

    def stop(self) -> None:
        """Stop the Tor process if we launched it. Never raises."""
        if not self._owned or self._process is None:
            self._process = None
            return
        if self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    self._process.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._process = None
        self._owned = False

    # -- circuit rotation --------------------------------------------------

    def rotate_circuit(self, *, cooldown: float = NEWNYM_COOLDOWN_SECONDS) -> bool:
        """Send NEWNYM to request a new circuit. Returns True if the signal
        was accepted by the controller.

        Does NOT prove the exit IP changed — use :meth:`get_exit_ip` before
        and after to verify. Respects Tor's ~10s NEWNYM rate limit.
        """
        if not _is_port_open("127.0.0.1", self.control_port):
            log.warning("Tor control port %d not reachable; cannot rotate", self.control_port)
            return False
        try:
            from stem import Signal
            from stem.control import Controller
        except ImportError:
            log.error("stem library not installed; run: pip install stem")
            return False
        try:
            with Controller.from_port(port=self.control_port) as controller:
                controller.authenticate()  # cookie auth auto-detected from torrc
                controller.signal(Signal.NEWNYM)
        except Exception as exc:  # noqa: BLE001
            log.error("NEWNYM failed: %s", exc)
            return False
        # Honor the rate limit so the next request actually rides the new circuit.
        time.sleep(cooldown)
        return True

    def get_exit_ip(self, *, timeout: float = 30.0) -> str | None:
        """Return the current Tor exit IP by querying an IP echo service.

        Routes the request through our SOCKS port via ``requests`` (which uses
        PySocks for ``socks5h://``, resolving DNS through Tor). Returns None on
        any failure (Tor down, exit blocked, network error).
        """
        try:
            import requests
        except ImportError:
            log.error("requests not installed")
            return None
        proxies = {"http": self.socks_proxy_url, "https": self.socks_proxy_url}
        try:
            resp = requests.get(IP_CHECK_URL, proxies=proxies, timeout=timeout)
            if resp.status_code == 200:
                return resp.text.strip() or None
            log.warning("Exit IP check returned HTTP %d", resp.status_code)
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("Exit IP check failed: %s", exc)
            return None

    def verify_rotation(self) -> dict:
        """Rotate and confirm the exit IP actually changed.

        Returns a dict with ``rotated`` (bool), ``before`` / ``after`` IPs,
        and ``error`` on failure. This is the authoritative check that NEWNYM
        produced a real identity change, not just an accepted signal.
        """
        before = self.get_exit_ip()
        if before is None:
            return {"rotated": False, "before": None, "after": None, "error": "无法获取轮换前出口 IP（Tor 可能未就绪）"}
        if not self.rotate_circuit():
            return {"rotated": False, "before": before, "after": None, "error": "NEWNYM 信号发送失败"}
        after = self.get_exit_ip()
        if after is None:
            return {"rotated": False, "before": before, "after": None, "error": "无法获取轮换后出口 IP"}
        return {
            "rotated": before != after,
            "before": before,
            "after": after,
            "error": "" if before != after else "轮换前后出口 IP 相同（NEWNYM 可能被限流）",
        }
