import json

from scansci_html import cli
from scansci_html.discovery import (
    CrossrefDiscoveryProvider,
    OpenAlexDiscoveryProvider,
    PubMedDiscoveryProvider,
    SemanticScholarDiscoveryProvider,
)


def test_openalex_discovery_provider_parses_work_results():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "OpenAlex Paper",
                        "doi": "https://doi.org/10.1234/openalex",
                        "publication_year": 2026,
                        "primary_location": {"source": {"display_name": "Journal A"}},
                    }
                ]
            }

    class FakeSession:
        def get(self, url, *, params, timeout):
            calls.append((url, params, timeout))
            return FakeResponse()

    papers = OpenAlexDiscoveryProvider(session=FakeSession()).search("cortical activity", limit=1)

    assert calls == [("https://api.openalex.org/works", {"search": "cortical activity", "per-page": 1}, 30.0)]
    assert [paper.to_dict() for paper in papers] == [
        {
            "title": "OpenAlex Paper",
            "doi": "10.1234/openalex",
            "year": 2026,
            "venue": "Journal A",
            "source": "openalex",
            "url": "https://openalex.org/W1",
        }
    ]


def test_crossref_discovery_provider_parses_work_results():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["Crossref Paper"],
                            "DOI": "10.1234/crossref",
                            "published-print": {"date-parts": [[2025, 1, 1]]},
                            "container-title": ["Journal B"],
                            "URL": "https://doi.org/10.1234/crossref",
                        }
                    ]
                }
            }

    class FakeSession:
        def get(self, url, *, params, timeout):
            return FakeResponse()

    papers = CrossrefDiscoveryProvider(session=FakeSession()).search("biomass", limit=1)

    assert papers[0].to_dict() == {
        "title": "Crossref Paper",
        "doi": "10.1234/crossref",
        "year": 2025,
        "venue": "Journal B",
        "source": "crossref",
        "url": "https://doi.org/10.1234/crossref",
    }


def test_semantic_scholar_discovery_provider_parses_paper_results():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "title": "Semantic Scholar Paper",
                        "year": 2024,
                        "venue": "Conference C",
                        "url": "https://semanticscholar.org/paper/1",
                        "externalIds": {"DOI": "10.1234/semantic"},
                    }
                ]
            }

    class FakeSession:
        def get(self, url, *, params, timeout):
            return FakeResponse()

    papers = SemanticScholarDiscoveryProvider(session=FakeSession()).search("language model", limit=1)

    assert papers[0].to_dict() == {
        "title": "Semantic Scholar Paper",
        "doi": "10.1234/semantic",
        "year": 2024,
        "venue": "Conference C",
        "source": "semantic-scholar",
        "url": "https://semanticscholar.org/paper/1",
    }


def test_pubmed_discovery_provider_uses_esearch_and_esummary():
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeSession:
        def get(self, url, *, params, timeout):
            calls.append((url, params, timeout))
            if url.endswith("/esearch.fcgi"):
                return FakeResponse({"esearchresult": {"idlist": ["123"]}})
            return FakeResponse(
                {
                    "result": {
                        "123": {
                            "title": "PubMed Paper",
                            "fulljournalname": "Journal D",
                            "pubdate": "2023 Jan",
                            "elocationid": "doi: 10.1234/pubmed",
                            "uid": "123",
                        }
                    }
                }
            )

    papers = PubMedDiscoveryProvider(session=FakeSession()).search("cortical activity", limit=1)

    assert calls == [
        (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {"db": "pubmed", "term": "cortical activity", "retmode": "json", "retmax": 1},
            30.0,
        ),
        (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            {"db": "pubmed", "id": "123", "retmode": "json"},
            30.0,
        ),
    ]
    assert papers[0].to_dict() == {
        "title": "PubMed Paper",
        "doi": "10.1234/pubmed",
        "year": 2023,
        "venue": "Journal D",
        "source": "pubmed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
    }


def test_cli_discover_emits_discovered_papers(monkeypatch, capsys):
    class FakePaper:
        def to_dict(self):
            return {
                "title": "Discovered Paper",
                "doi": "10.1234/discovered",
                "year": 2026,
                "venue": "Journal",
                "source": "openalex",
                "url": "https://example.test",
            }

    class FakeProvider:
        def search(self, query, *, limit):
            return [FakePaper()]

    monkeypatch.setattr(cli, "build_discovery_provider", lambda provider: FakeProvider())

    exit_code = cli.main(["discover", "--provider", "openalex", "--query", "cortical activity", "--limit", "1"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "query": "cortical activity",
        "provider": "openalex",
        "papers": [
            {
                "title": "Discovered Paper",
                "doi": "10.1234/discovered",
                "year": 2026,
                "venue": "Journal",
                "source": "openalex",
                "url": "https://example.test",
            }
        ],
    }
