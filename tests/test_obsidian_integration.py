from __future__ import annotations

from pathlib import Path

import pytest

from scansci_html.obsidian_integration import (
    obsidian_backlinks,
    obsidian_status,
    read_obsidian_note,
    search_obsidian_vault,
)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "Research Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Methods").mkdir()
    (vault / "Methods" / "Retrieval.md").write_text(
        "# Retrieval\n\nHybrid retrieval combines embeddings and lexical search.\n\n[[Evidence Review]]",
        encoding="utf-8",
    )
    (vault / "Evidence Review.md").write_text(
        "# Evidence Review\n\nThis review compares retrieval evidence and cites [[Methods/Retrieval|the method]].",
        encoding="utf-8",
    )
    (vault / ".obsidian" / "workspace.md").write_text("private config", encoding="utf-8")
    return vault


def test_obsidian_connector_search_read_and_backlinks_are_vault_scoped(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    status = obsidian_status(vault)
    search = search_obsidian_vault(vault, "hybrid retrieval", limit=5)
    note = read_obsidian_note(vault, "Methods/Retrieval")
    backlinks = obsidian_backlinks(vault, "Methods/Retrieval.md")

    assert status["read_only"] is True
    assert status["has_obsidian_config"] is True
    assert status["note_count"] == 2
    assert search["results"][0]["note_path"] == "Methods/Retrieval.md"
    assert "embeddings" in note["content"]
    assert backlinks["backlinks"][0]["note_path"] == "Evidence Review.md"


def test_obsidian_connector_rejects_paths_outside_linked_vault(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="relative"):
        read_obsidian_note(vault, str(outside.resolve()))
    with pytest.raises(ValueError, match="escapes"):
        read_obsidian_note(vault, "../outside.md")
