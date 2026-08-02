"""End-to-end verification that ScanSci's Tor rotation actually works.

Launches a real Tor (with obfs4 bridges by default — direct relays are blocked
on most restricted networks), checks the exit IP, rotates the circuit (NEWNYM),
and checks the exit IP again. The test passes only if the two IPs differ — that
is the only proof that circuit rotation produced a real identity change.

Requires network access (to download Tor on first run + reach the IP echo).
Run manually:

    python bench/verify_tor_rotation.py                # bridges on (default)
    python bench/verify_tor_rotation.py --no-bridges   # direct relays only

Exits 0 on success, 1 if rotation did not change the IP, 2 if Tor failed.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scansci_html.tor_runtime import TorCircuitManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ScanSci Tor circuit rotation end-to-end.")
    parser.add_argument("--transport", default="snowflake", choices=["snowflake", "obfs4", "none"], help="Pluggable transport (default: snowflake).")
    parser.add_argument("--no-bridges", action="store_true", help="Legacy alias for --transport none.")
    args = parser.parse_args()

    transport = "none" if args.no_bridges else args.transport
    workspace = Path(tempfile.gettempdir()) / "scansci_tor_verify.sqlite"
    manager = TorCircuitManager(workspace, transport=transport)
    mode_labels = {"snowflake": "Snowflake（CDN 域前置）", "obfs4": "obfs4 网桥", "none": "直连"}
    mode = mode_labels[transport]
    print(f"→ 启动 Tor（{mode}模式，首次会下载 Expert Bundle，约 30MB）…")
    if not manager.ensure_tor():
        print(f"✗ Tor 启动失败（{mode}）。")
        hints = {
            "snowflake": ["CDN 前置被封、STUN 不可达、或 lyrebird.exe 缺失", "--transport obfs4", "--transport none"],
            "obfs4": ["内置网桥 IP 被封、lyrebird.exe 缺失、或网络阻断 obfs4", "--transport snowflake（更抗封锁）", "--transport none"],
            "none": ["网络阻断了到 Tor relay 的直连（受限网络常见）", "--transport snowflake", "--transport obfs4"],
        }
        print(f"  可能原因：{hints[transport][0]}。")
        print(f"  尝试：python bench/verify_tor_rotation.py {hints[transport][1]}")
        if len(hints[transport]) > 2:
            print(f"       python bench/verify_tor_rotation.py {hints[transport][2]}")
        return 2

    print(f"✓ Tor 已就绪（{mode}），SOCKS 代理：{manager.socks_proxy_url}")
    print("→ 检测当前出口 IP…")
    ip_before = manager.get_exit_ip()
    if ip_before is None:
        print("✗ 无法通过 Tor 获取出口 IP（可能电路尚未建立或出口被封锁）。")
        manager.stop()
        return 2
    print(f"  轮换前出口 IP：{ip_before}")

    print("→ 发送 NEWNYM 信号切换电路（等待 10s 冷却）…")
    if not manager.rotate_circuit():
        print("✗ NEWNYM 信号发送失败（控制端口不可达或 stem 未安装）。")
        manager.stop()
        return 2

    print("→ 再次检测出口 IP…")
    ip_after = manager.get_exit_ip()
    if ip_after is None:
        print("✗ 轮换后无法获取出口 IP。")
        manager.stop()
        return 2
    print(f"  轮换后出口 IP：{ip_after}")

    manager.stop()
    if ip_before == ip_after:
        print(f"\n✗ 轮换前后 IP 相同（{ip_before}）。NEWNYM 可能被 Tor 限流，或电路恰好选了同一出口。")
        print("  建议：等 30s 后重试，或多次轮换后再比较。")
        return 1

    print(f"\n✓ 验证通过：出口 IP 已从 {ip_before} 变为 {ip_after}。Tor 电路轮换真实有效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
