from pathlib import Path

from scansci_html.broker import BrokerService, enqueue_request, read_response
from scansci_html.models import FetchResponse


def test_broker_processes_request_with_reusable_fetcher(tmp_path: Path):
    broker_dir = tmp_path / "broker"
    output_dir = tmp_path / "papers"
    fetcher = FakeFetcher()
    request_id = enqueue_request(broker_dir, "10.1126/science.aed5051")

    processed = BrokerService(
        broker_dir=broker_dir,
        output_dir=output_dir,
        fetcher=fetcher,
        min_text_length=50,
    ).process_once()

    response = read_response(broker_dir, request_id)
    assert processed is True
    assert response is not None
    assert response["status"] == "success"
    assert response["doi"] == "10.1126/science.aed5051"
    assert Path(response["output_path"]).exists()
    assert response["structure"]["has_body"] is True
    assert response["structure"]["reference_count"] == 1
    assert fetcher.urls == ["https://doi.org/10.1126/science.aed5051"]
    assert fetcher.close_count == 0
    assert list((broker_dir / "requests").glob("*.json")) == []


def test_broker_process_once_returns_false_without_requests(tmp_path: Path):
    fetcher = FakeFetcher()
    service = BrokerService(
        broker_dir=tmp_path / "broker",
        output_dir=tmp_path / "papers",
        fetcher=fetcher,
        min_text_length=50,
    )

    assert service.process_once() is False
    assert fetcher.urls == []


class FakeFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.close_count = 0

    def fetch(self, url: str) -> FetchResponse:
        self.urls.append(url)
        return FetchResponse(
            url=url,
            final_url="https://www.science.org/doi/10.1126/science.aed5051",
            source="cloakbrowser",
            html="""
            <html>
              <head><title>Fast cell wall softening causes Venus flytrap closure</title></head>
              <body>
                <article>
                  <h1>Fast cell wall softening causes Venus flytrap closure</h1>
                  <p>DOI: 10.1126/science.aed5051</p>
                  <section><h2>Abstract</h2><p>Plants can move rapidly without muscles.</p></section>
                  <section><h2>Results</h2><p>Full article text is available after legal institution login.</p></section>
                  <section><h2>Discussion</h2><p>The mechanism combines hydraulic and mechanical measurements.</p></section>
                  <section><h2>References and Notes</h2><p>Reference list is available.</p></section>
                </article>
              </body>
            </html>
            """,
        )

    def close(self) -> None:
        self.close_count += 1
