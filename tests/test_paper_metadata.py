from __future__ import annotations

from pathlib import Path

import fitz

from scansci_html.paper_metadata import extract_pdf_metadata


def test_extract_pdf_metadata_prefers_supplied_catalog_fields(tmp_path: Path):
    path = tmp_path / "fallback-file-name.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "正文")
    document.set_metadata(
        {
            "title": "Embedded title",
            "author": "Embedded author",
            "subject": "10.5555/embedded-doi 2021",
        }
    )
    document.save(path)
    document.close()

    metadata = extract_pdf_metadata(
        path,
        supplied={"title": "Zotero title", "doi": "10.5555/supplied-doi", "date": "2024"},
    )

    assert metadata["title"] == "Zotero title"
    assert metadata["doi"] == "10.5555/supplied-doi"
    assert metadata["year"] == "2024"
    assert metadata["metadata_confidence"] == "high"


def test_extract_pdf_metadata_uses_embedded_fields_and_filename_fallback(tmp_path: Path):
    path = tmp_path / "solar-cells-study.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "正文")
    document.set_metadata({"title": "Embedded title", "author": "A. Researcher", "subject": "doi: 10.1000/ABC-42"})
    document.save(path)
    document.close()

    metadata = extract_pdf_metadata(path)

    assert metadata["title"] == "Embedded title"
    assert metadata["author"] == "A. Researcher"
    assert metadata["doi"] == "10.1000/abc-42"


def test_extract_pdf_metadata_splits_common_title_author_filename(tmp_path: Path):
    path = tmp_path / "光伏生态效应研究_李明.pdf"
    path.write_bytes(b"%PDF-1.4\nfixture")

    metadata = extract_pdf_metadata(path)

    assert metadata["title"] == "光伏生态效应研究"
    assert metadata["author"] == "李明"


def test_extract_pdf_metadata_does_not_treat_cnki_as_author(tmp_path: Path):
    path = tmp_path / "paper.pdf"
    document = fitz.open()
    document.new_page()
    document.set_metadata({"title": "A paper", "author": "CNKI"})
    document.save(path)
    document.close()

    assert "author" not in extract_pdf_metadata(path)
