import json
from pathlib import Path

from scansci_html.mcp_marketplace import (
    OFFICIAL_REGISTRY_URL,
    install_marketplace_server,
    marketplace_cache_path,
    marketplace_catalog,
    sync_official_registry,
)


def test_academic_catalogue_is_available_offline_and_installs_as_configuration(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    workspace.touch()

    catalog = marketplace_catalog(workspace)
    pubmed = next(item for item in catalog["items"] if item["id"] == "io.github.cyanheads/pubmed-mcp-server")
    installed = install_marketplace_server(workspace, pubmed["id"])

    assert catalog["source"]["name"] == "Official MCP Registry"
    assert catalog["source"]["api_version"] == "v0.1"
    assert {"life", "medicine"} <= set(pubmed["disciplines"])
    assert installed["created"] is True
    assert installed["record"]["catalog_id"] == pubmed["id"]
    assert installed["record"]["command"] == "bun"
    assert installed["settings"]["mcp_servers"][0]["source"] == "Official MCP Registry"

    duplicate = install_marketplace_server(workspace, pubmed["id"])
    assert duplicate["created"] is False
    assert len(duplicate["settings"]["mcp_servers"]) == 1


def test_sync_official_registry_caches_and_classifies_public_records(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace.sqlite"
    workspace.touch()
    response_body = {
        "servers": [
            {
                "server": {
                    "name": "org.example/protein-search",
                    "title": "Protein Search",
                    "description": "Search protein sequences and UniProt records for genomic research.",
                    "version": "1.4.0",
                    "repository": {"url": "https://github.com/example/protein-search", "source": "github"},
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@example/protein-search",
                            "version": "1.4.0",
                            "runtimeHint": "npx",
                            "transport": {"type": "stdio"},
                        }
                    ],
                },
                "_meta": {"io.modelcontextprotocol.registry/official": {"updatedAt": "2026-07-19T00:00:00Z"}},
            }
        ]
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(response_body).encode("utf-8")

    seen_urls: list[str] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        assert timeout == 7.0
        return Response()

    monkeypatch.setattr("scansci_html.mcp_marketplace.urlopen", fake_urlopen)

    catalog = sync_official_registry(workspace)
    item = next(item for item in catalog["items"] if item["id"] == "org.example/protein-search")

    assert seen_urls
    assert all(url.startswith(OFFICIAL_REGISTRY_URL) for url in seen_urls)
    assert item["command"] == "npx"
    assert item["args"] == "@example/protein-search"
    assert "life" in item["disciplines"]
    assert item["updated_at"] == "2026-07-19T00:00:00Z"
    assert marketplace_cache_path(workspace).is_file()
