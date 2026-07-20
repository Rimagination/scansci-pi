import json
from pathlib import Path

from bs4 import BeautifulSoup

from scansci_html import cli
from scansci_html.cnki_reader import download_cnki_reader_images, render_cnki_reader_json


def _zh(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


def _sample_cnki_payload() -> dict[str, object]:
    title = _zh(
        0x57FA,
        0x4E8E,
        0x6700,
        0x4F18,
        0x6027,
        0x539F,
        0x7406,
        0x7684,
        0x666E,
        0x9002,
        0x6027,
        0x78B3,
        0x6C34,
        0x901A,
        0x91CF,
        0x8026,
        0x5408,
        0x4F30,
        0x7B97,
        0x65B9,
        0x6CD5,
        0x7814,
        0x7A76,
    )
    return {
        "code": 200,
        "data": {
            "metadata": {
                "resourceType": "CJFQ",
                "fileName": "STXB202204021",
                "title": f"<b>{title}</b>",
                "titleEN": "<b>Towards a universal model</b>",
                "receivedDate": "2021-01-01",
                "abstracts": _zh(0x8FD9, 0x662F, 0x4E2D, 0x6587, 0x6458, 0x8981),
                "abstractsEN": "English abstract.",
            },
            "authors": [
                {"title": _zh(0x8C2D, 0x6DF1)},
                {"title": _zh(0x738B, 0x7113)},
            ],
            "authorsEN": [{"title": "TAN Shen"}, {"title": "WANG Han"}],
            "affiliation": [{"title": _zh(0x6E05, 0x534E, 0x5927, 0x5B66)}],
            "affiliationEn": [{"title": "Tsinghua University"}],
            "keywords": [{"title": _zh(0x6700, 0x4F18, 0x6027, 0x539F, 0x7406)}],
            "keywordsEN": [{"title": "First-Principles Theory"}],
            "funds": [{"title": _zh(0x56FD, 0x5BB6, 0x81EA, 0x7136, 0x79D1, 0x5B66, 0x57FA, 0x91D1)}],
            "source": {"type": "JOURNAL", "year": "2022", "issue": "04"},
            "fullText": [
                {
                    "type": "PARAGRAPH",
                    "value": {
                        "no": "190",
                        "content": (
                            _zh(0x690D, 0x7269, 0x5149, 0x5408, 0x4F5C, 0x7528)
                            + '<sup><a id="68" type="reference">[1]</a></sup>'
                        ),
                    },
                },
                {
                    "type": "CATALOG",
                    "value": {"no": "193", "title": f"<b>1 {_zh(0x65B9, 0x6CD5)}</b>", "level": "1"},
                },
                {
                    "type": "PARAGRAPH",
                    "value": {
                        "no": "200",
                        "content": (
                            '<mathml><math><mrow><mtext>G</mtext><mtext>\u03a1</mtext>'
                            '<mtext>\u03a1</mtext><mo>=</mo><mi>\u03c6</mi>'
                            '<mi>\u0399</mi><msub><mrow></mrow><mtext>obs</mtext></msub>'
                            '<mtext>V</mtext><mtext>\u03a1</mtext><mtext>D</mtext>'
                            "</mrow></math></mathml>(3)"
                        ),
                    },
                },
                {
                    "type": "TABLE",
                    "value": {
                        "no": "223",
                        "title": f"<b>{_zh(0x8868)}1</b>",
                        "content": "<tr><td>Name</td><td>Value</td></tr><tr><td>A</td><td>1</td></tr>",
                    },
                },
                {
                    "type": "FIGURE",
                    "value": {
                        "no": "231",
                        "title": f"<b>{_zh(0x56FE)}1 GPP</b>",
                        "enTitle": "<b>Fig.1 GPP</b>",
                        "listImageHref": [
                            "https://kns.cnki.net/ossapi/kreader-api/v1/attachment"
                            "?product=CJFQ&filename=STXB202204021&tablename=cjfdlast2022"
                            "&type=JOURNAL&annexid=STXB202204021_231.jpg"
                            "&invoice=SECRET&nonce=SECRET&idenid=SECRET"
                        ],
                    },
                },
            ],
            "references": [{"no": "68", "seq": "1", "title": "[1] Fisher J B. Example reference."}],
        },
    }


def test_cnki_reader_json_renders_clean_html_without_temporary_credentials():
    document = render_cnki_reader_json(
        _sample_cnki_payload(),
        tablename="cjfdlast2022",
    )

    soup = BeautifulSoup(document.html, "html.parser")

    assert document.has_fulltext is True
    assert document.access_status == "fulltext"
    assert document.title.startswith(_zh(0x57FA, 0x4E8E, 0x6700, 0x4F18, 0x6027))
    assert soup.select_one('article[data-source="cnki"][data-filename="STXB202204021"]')
    assert soup.select_one('a.citation[href="#ref-68"][data-ref="68"]')
    assert soup.select_one("li#ref-68")
    assert soup.select_one('figure.article-figure[data-annexid="STXB202204021_231.jpg"]')
    assert not soup.select_one("figure.article-figure img")

    text = soup.get_text(" ", strip=True)
    assert "G P P" in text
    assert "V P D" in text
    assert "\u03a1" not in text
    assert "\u0399" not in text
    assert "SECRET" not in document.html
    assert "invoice" not in document.html
    assert "nonce" not in document.html
    assert "idenid" not in document.html
    assert "?" not in document.html


def test_cnki_reader_json_can_embed_local_image_assets():
    document = render_cnki_reader_json(
        _sample_cnki_payload(),
        tablename="cjfdlast2022",
        image_assets={"STXB202204021_231.jpg": "paper_assets/STXB202204021_231.jpg"},
    )

    soup = BeautifulSoup(document.html, "html.parser")
    image = soup.select_one('figure.article-figure img[src="paper_assets/STXB202204021_231.jpg"]')

    assert image is not None
    assert image["data-annexid"] == "STXB202204021_231.jpg"
    assert _zh(0x56FE) + "1 GPP" in image["alt"]
    assert not soup.select_one("figure.article-figure .figure-media")
    assert "SECRET" not in document.html
    assert "invoice" not in document.html
    assert "nonce" not in document.html
    assert "idenid" not in document.html


def test_cnki_reader_downloads_images_to_local_assets_without_persisting_credentials(tmp_path: Path):
    class FakeResponse:
        content = b"fake-jpeg"
        headers = {"Content-Type": "image/jpeg"}

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def get(self, url: str, *, timeout: float, headers: dict[str, str]):
            self.calls.append({"url": url, "timeout": timeout, "headers": headers})
            return FakeResponse()

    output_path = tmp_path / "paper.html"
    session = FakeSession()

    image_assets, warnings = download_cnki_reader_images(
        _sample_cnki_payload(),
        output_path=output_path,
        session=session,
        source_url="https://kns.cnki.net/reader/xml?invoice=SECRET&nonce=SECRET&product=CJFQ",
        timeout=12.5,
    )

    asset_path = tmp_path / "paper_assets" / "STXB202204021_231.jpg"
    assert image_assets == {"STXB202204021_231.jpg": "paper_assets/STXB202204021_231.jpg"}
    assert asset_path.read_bytes() == b"fake-jpeg"
    assert warnings == []
    assert session.calls[0]["timeout"] == 12.5
    assert "invoice=SECRET" in str(session.calls[0]["url"])
    assert "invoice" not in str(image_assets)
    assert "nonce" not in str(image_assets)
    assert "invoice" not in str(session.calls[0]["headers"])
    assert "nonce" not in str(session.calls[0]["headers"])


def test_cli_cnki_reader_writes_html_from_xml_data_json(tmp_path: Path, capsys):
    input_path = tmp_path / "xml_data_all.json"
    output_path = tmp_path / "paper.html"
    input_path.write_text(json.dumps(_sample_cnki_payload(), ensure_ascii=False), encoding="utf-8")

    exit_code = cli.main(
        [
            "cnki-reader",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--tablename",
            "cjfdlast2022",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    html = output_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["output_path"] == str(output_path)
    assert payload["counts"] == {"paragraphs": 2, "sections": 1, "figures": 1, "tables": 1, "references": 1}
    assert "STXB202204021" in html
    assert "SECRET" not in html


def test_cli_cnki_reader_can_include_downloaded_local_images(tmp_path: Path, monkeypatch, capsys):
    input_path = tmp_path / "xml_data_all.json"
    output_path = tmp_path / "paper.html"
    input_path.write_text(json.dumps(_sample_cnki_payload(), ensure_ascii=False), encoding="utf-8")

    def fake_download_cnki_reader_images(
        payload,
        *,
        output_path,
        assets_dir=None,
        source_url="",
        session=None,
        timeout=30.0,
    ):
        asset_dir = assets_dir or output_path.with_name(f"{output_path.stem}_assets")
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "STXB202204021_231.jpg"
        asset_path.write_bytes(b"fake-jpeg")
        return {"STXB202204021_231.jpg": f"{asset_dir.name}/STXB202204021_231.jpg"}, []

    monkeypatch.setattr(cli, "download_cnki_reader_images", fake_download_cnki_reader_images)

    exit_code = cli.main(
        [
            "cnki-reader",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--include-images",
            "--assets-dir",
            str(tmp_path / "assets"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    soup = BeautifulSoup(output_path.read_text(encoding="utf-8"), "html.parser")

    assert exit_code == 0
    assert payload["image_assets"] == 1
    assert soup.select_one('figure.article-figure img[src="assets/STXB202204021_231.jpg"]')
    assert "SECRET" not in output_path.read_text(encoding="utf-8")
