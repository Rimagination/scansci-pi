from pathlib import Path

from scansci_html import vector_index


def test_dead_vector_cache_lock_is_removed_on_windows_style_pid_probe_failure(
    tmp_path: Path,
    monkeypatch,
):
    lock = tmp_path / ".evidence.sqlite.scansci-vec.lock"
    lock.write_text("pid=424242\ncreated=1\n", encoding="utf-8")

    def dead_pid(_pid: int, _signal: int) -> None:
        raise SystemError("Windows dead-process probe")

    monkeypatch.setattr(vector_index.os, "kill", dead_pid)

    assert vector_index._remove_stale_vector_cache_lock(lock) is True
    assert not lock.exists()
