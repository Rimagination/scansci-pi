from __future__ import annotations

from pathlib import Path

from scansci_html.tesseract_installer import TesseractInstallManager


def test_installer_copies_existing_system_language_and_downloads_only_missing(tmp_path: Path, monkeypatch):
    command = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    system_data = command.parent / "tessdata"
    system_data.mkdir(parents=True)
    command.write_bytes(b"exe")
    (system_data / "eng.traineddata").write_bytes(b"e" * 2048)
    target = tmp_path / "user-tessdata"
    downloads: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            del chunk_size
            yield b"z" * 2048

    def get(url, **_kwargs):
        downloads.append(url)
        return Response()

    monkeypatch.setattr("scansci_html.tesseract_installer._tesseract_path", lambda: str(command))
    monkeypatch.setattr("scansci_html.tesseract_installer.requests.get", get)
    manager = TesseractInstallManager(
        tessdata_dir=target,
        status_provider=lambda _languages: {"available": True, "missing_languages": []},
    )

    manager._run(["chi_sim", "eng"])

    assert manager.status()["state"] == "ready"
    assert (target / "chi_sim.traineddata").stat().st_size == 2048
    assert (target / "eng.traineddata").read_bytes() == b"e" * 2048
    assert downloads == ["https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim.traineddata"]
