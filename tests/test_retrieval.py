import json
from pathlib import Path

from scansci_html.retrieval import search_evidence_index


def test_search_evidence_index_ranks_blocks_by_query_terms(tmp_path: Path):
    index = tmp_path / "evidence.jsonl"
    rows = [
        {
            "doc_id": "10.1234_a",
            "block_id": "10.1234_a:evidence-0001",
            "title": "Organizer Paper",
            "doi": "10.1234/a",
            "source_url": "https://publisher.example/a",
            "html_path": "a.html",
            "anchor": "evidence-0001",
            "section": "Results",
            "block_type": "paragraph",
            "text": "Blastopore lip transplantation induced a complete secondary pharynx.",
        },
        {
            "doc_id": "10.1234_b",
            "block_id": "10.1234_b:evidence-0001",
            "title": "Statistics Paper",
            "doi": "10.1234/b",
            "source_url": "https://publisher.example/b",
            "html_path": "b.html",
            "anchor": "evidence-0001",
            "section": "Methods",
            "block_type": "paragraph",
            "text": "Replicate-level counts were analysed with a mixed model.",
        },
    ]
    index.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    hits = search_evidence_index(index, "blastopore secondary pharynx", limit=2)

    assert [hit["block_id"] for hit in hits] == [
        "10.1234_a:evidence-0001",
    ]
    assert hits[0]["score"] > 0
    assert hits[0]["matched_terms"] == ["blastopore", "secondary", "pharynx"]


def test_offline_retrieval_matches_chinese_terms_and_spaced_pdf_glyphs(tmp_path: Path):
    index = tmp_path / "chinese-evidence.jsonl"
    rows = [
        {"block_id": "pv", "title": "光伏生态", "text": "光 伏 电 站 改 变 了 土 壤 水 分 与 植 被 覆 盖。"},
        {"block_id": "other", "title": "城市交通", "text": "道路网络影响通勤时间。"},
    ]
    index.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    hits = search_evidence_index(index, "光伏电站对土壤水分的影响", limit=2)

    assert hits
    assert hits[0]["block_id"] == "pv"
    assert "光伏" in hits[0]["matched_terms"]
