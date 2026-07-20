from pathlib import Path

from scansci_html.assets import localize_image_assets


class FakeAssetResponse:
    def __init__(
        self,
        *,
        content: bytes = b"image-bytes",
        headers: dict[str, str] | None = None,
        status_code: int = 200,
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.headers = headers or {"Content-Type": "image/png"}
        self.status_code = status_code
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAssetSession:
    def __init__(self, responses: dict[str, FakeAssetResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> FakeAssetResponse:
        self.requests.append({"url": url, "timeout": timeout, "headers": headers})
        return self.responses[url]


class CapturingAssetSession(FakeAssetSession):
    def __init__(self, responses: dict[str, FakeAssetResponse]) -> None:
        super().__init__(responses)
        self.captures: list[dict[str, object]] = []

    def capture_image_asset(
        self,
        url: str,
        *,
        output_path: Path,
        source_url: str,
        timeout: float,
    ) -> None:
        self.captures.append(
            {
                "url": url,
                "output_path": output_path,
                "source_url": source_url,
                "timeout": timeout,
            }
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"captured-png")


def test_localize_image_assets_downloads_remote_images_and_rewrites_src(tmp_path: Path):
    output_path = tmp_path / "paper.html"
    image_url = "https://cdn.example.org/figures/Figure%201.png"
    session = FakeAssetSession({image_url: FakeAssetResponse(content=b"figure-bytes")})
    html = f'<article><h1>Paper</h1><figure><img src="{image_url}" alt="Figure 1"></figure></article>'

    localized_html, warnings = localize_image_assets(
        html,
        output_path=output_path,
        source_url="https://publisher.example/article",
        session=session,
    )

    asset_dir = tmp_path / "paper_assets"
    assets = list(asset_dir.iterdir())
    assert warnings == []
    assert len(assets) == 1
    assert assets[0].read_bytes() == b"figure-bytes"
    assert 'src="paper_assets/' in localized_html
    assert image_url not in localized_html
    assert session.requests[0]["headers"]["Referer"] == "https://publisher.example/article"


def test_localize_image_assets_keeps_remote_src_and_warns_when_download_fails(tmp_path: Path):
    output_path = tmp_path / "paper.html"
    image_url = "https://cdn.example.org/figures/missing.jpg"
    session = FakeAssetSession(
        {image_url: FakeAssetResponse(status_code=403, error=RuntimeError("forbidden"))}
    )
    html = f'<article><img src="{image_url}" alt="blocked"></article>'

    localized_html, warnings = localize_image_assets(
        html,
        output_path=output_path,
        source_url="https://publisher.example/article",
        session=session,
    )

    assert image_url in localized_html
    assert not (tmp_path / "paper_assets").exists()
    assert warnings == [f"image asset download failed: {image_url} (RuntimeError: forbidden)"]


def test_localize_image_assets_uses_browser_capture_fallback_after_http_forbidden(tmp_path: Path):
    output_path = tmp_path / "paper.html"
    image_url = "https://cdn.example.org/protected/figure.jpg"
    session = CapturingAssetSession(
        {image_url: FakeAssetResponse(status_code=403, error=RuntimeError("forbidden"))}
    )
    html = f'<article><img src="{image_url}" alt="protected"></article>'

    localized_html, warnings = localize_image_assets(
        html,
        output_path=output_path,
        source_url="https://publisher.example/article",
        session=session,
    )

    assets = list((tmp_path / "paper_assets").iterdir())
    assert warnings == []
    assert len(assets) == 1
    assert assets[0].suffix == ".png"
    assert assets[0].read_bytes() == b"captured-png"
    assert image_url not in localized_html
    assert session.captures[0]["url"] == image_url
    assert session.captures[0]["source_url"] == "https://publisher.example/article"
