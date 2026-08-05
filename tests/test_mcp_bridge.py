from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from scansci_html.pi_agent import PiAgentClient


def _probe(tmp_path: Path, *, allow_write: bool, deferred: bool = False) -> dict[str, object]:
    node, sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.mjs"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    process = subprocess.Popen(
        [str(node), str(sidecar)],
        cwd=Path(__file__).parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(
            json.dumps(
                {
                    "type": "mcp.probe",
                    "request_id": "fixture-probe",
                    "activation_mode": "deferred" if deferred else "direct",
                    "cwd": str(tmp_path),
                    "mcp_servers": [
                        {
                            "id": "fixture",
                            "name": "Fixture MCP",
                            "enabled": True,
                            "transport": "stdio",
                            "command": str(node),
                            "args_list": [str(fixture)],
                            "allow_write": allow_write,
                            "deferred": deferred,
                        }
                    ],
                }
            )
            + "\n"
        )
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            assert line, process.stderr.read() if process.stderr else "Pi sidecar exited"
            message = json.loads(line)
            if message.get("type") == "mcp.probe.completed":
                return message
            assert message.get("type") != "mcp.probe.failed", message
    finally:
        process.kill()
        process.wait(timeout=5)


def test_pi_mcp_bridge_discovers_read_tools_and_hides_write_tools_by_default(tmp_path: Path) -> None:
    result = _probe(tmp_path, allow_write=False)

    assert result["server_count"] == 1
    assert result["tool_count"] == 1
    assert [tool["name"] for tool in result["tools"]] == ["mcp__fixture__search_library"]


def test_pi_mcp_bridge_exposes_write_tools_after_explicit_authorization(tmp_path: Path) -> None:
    result = _probe(tmp_path, allow_write=True)

    assert result["server_count"] == 1
    assert {tool["name"] for tool in result["tools"]} == {
        "mcp__fixture__search_library",
        "mcp__fixture__create_note",
    }


def test_pi_mcp_bridge_deferred_mode_exposes_compact_proxy_without_starting_server(tmp_path: Path) -> None:
    result = _probe(tmp_path, allow_write=False, deferred=True)

    assert result["server_count"] == 0
    assert {tool["name"] for tool in result["tools"]} == {
        "mcp__fixture__search",
        "mcp__fixture__call",
    }
