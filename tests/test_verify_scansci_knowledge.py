from __future__ import annotations

from scripts.verify_scansci_knowledge import wait_for_semantic_index


class _IndexRuntime:
    def __init__(self, statuses: list[dict[str, object]]) -> None:
        self.statuses = list(statuses)
        self.started: list[str] = []

    def start_evidence_index(self, notebook_id: str) -> dict[str, str]:
        self.started.append(notebook_id)
        return {"run_id": "index-run"}

    def evidence_index_status(self, notebook_id: str) -> dict[str, object]:
        assert notebook_id == "notebook-1"
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]


def test_wait_for_semantic_index_waits_for_background_readiness() -> None:
    runtime = _IndexRuntime(
        [
            {
                "available": True,
                "ready": False,
                "completed": 12,
                "total": 48,
                "run": {"run_id": "index-run", "status": "running"},
            },
            {
                "available": True,
                "ready": True,
                "completed": 48,
                "total": 48,
                "run": {"run_id": "index-run", "status": "completed"},
            },
        ]
    )

    result = wait_for_semantic_index(
        runtime,  # type: ignore[arg-type]
        "notebook-1",
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert runtime.started == ["notebook-1"]
    assert result["ready"] is True
    assert result["final"] == {
        "ready": True,
        "available": True,
        "completed": 48,
        "total": 48,
        "state": "",
        "error": "",
        "run_id": "index-run",
        "run_status": "completed",
        "run_error": "",
    }


def test_wait_for_semantic_index_reports_a_terminal_failure() -> None:
    runtime = _IndexRuntime(
        [
            {
                "available": True,
                "ready": False,
                "completed": 8,
                "total": 48,
                "run": {
                    "run_id": "index-run",
                    "status": "failed",
                    "error": "embedding unavailable",
                },
            }
        ]
    )

    result = wait_for_semantic_index(
        runtime,  # type: ignore[arg-type]
        "notebook-1",
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert result["ready"] is False
    assert result["reason"] == "index_run_terminal_failure"
    assert result["final"] == {
        "ready": False,
        "available": True,
        "completed": 8,
        "total": 48,
        "state": "",
        "error": "",
        "run_id": "index-run",
        "run_status": "failed",
        "run_error": "embedding unavailable",
    }
