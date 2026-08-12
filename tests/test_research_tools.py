import json
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scansci_html import research_tools


def test_search_journals_uses_scansci_origin_headers(monkeypatch):
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "items": [
                {
                    "id": 1,
                    "title": "Example Journal",
                    "issn": "1234-5678",
                    "if_2023": 5.2,
                    "jcr_quartile": "Q1",
                    "cas_2025": "1区",
                }
            ]
        }

    monkeypatch.setattr(research_tools, "_request_json", fake_request)

    result = research_tools.search_journals("请查询期刊：Example Journal")

    assert result["items"][0]["title"] == "Example Journal"
    assert parse_qs(urlparse(calls[0][0]).query)["q"] == ["Example Journal"]
    assert result["search_intent"]["subject"] == "Example Journal"
    assert calls[0][1]["headers"]["Origin"] == "https://journal.scansci.com"


def test_paper_atlas_returns_honest_web_fallback(monkeypatch):
    def fail_request(*args, **kwargs):
        raise RuntimeError("远程服务返回 HTTP 503")

    monkeypatch.setattr(research_tools, "_request_json", fail_request)

    result = research_tools.search_paper_atlas("climate change")

    assert result["status"] == "external"
    assert result["items"] == []
    assert result["external_url"] == "https://paperatlas.scansci.com/"
    assert "503" in result["message"]


def test_paper_atlas_forwards_only_compiled_subject(monkeypatch):
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return []

    monkeypatch.setattr(research_tools, "_request_json", fake_request)

    result = research_tools.search_paper_atlas(
        "请检索并整理相关论文的作者、年份、来源与 DOI。\n研究主题：植物功能性状"
    )

    assert parse_qs(urlparse(calls[0][0]).query)["q"] == ["植物功能性状"]
    assert result["search_intent"]["raw_query"].startswith("请检索并整理")
    assert result["search_intent"]["subject"] == "植物功能性状"


def test_capability_snapshot_marks_paper_atlas_as_web_handoff(tmp_path: Path):
    evidence = tmp_path / "evidence.sqlite"
    evidence.write_bytes(b"")

    snapshot = research_tools.capability_snapshot(workspace=tmp_path / "workspace.sqlite", evidence_db=evidence)
    atlas = next(item for item in snapshot["tools"] if item["id"] == "paper-atlas")

    assert atlas["status"] == "external"


# --------------------------------------------------------------------------- #
# download_papers — batch download loop
# --------------------------------------------------------------------------- #


_VALID_DOI = "10.1038/s41586-024-99999-9"
_VALID_ARXIV = "2401.04088"


@pytest.fixture(autouse=True)
def _no_batch_throttling(monkeypatch):
    """Zero out the inter-item delay so batch tests run instantly.

    Production defaults sleep 3-8s between downloads; tests must not.
    """
    monkeypatch.setattr(research_tools, "_BATCH_DELAY_MIN", 0.0)
    monkeypatch.setattr(research_tools, "_BATCH_DELAY_MAX", 0.0)


def _isolated_workspace(tmp_path: Path) -> Path:
    """Return a workspace path whose downloads dir is unique to this test.

    ``_download_directory`` resolves to ``workspace.parent / "downloads"``, and
    pytest nests every test's tmp_path under the same session parent — so two
    batch tests would otherwise share one downloads/ folder and a PDF written
    by one would be seen as "already downloaded" by the next. Nesting the
    workspace one level deeper gives each test its own downloads/ dir.
    """
    nested = tmp_path / "ws" / "workspace.sqlite"
    nested.parent.mkdir(parents=True, exist_ok=True)
    return nested


def _fake_download_factory(results: dict[str, dict]):
    """Build a fake download_paper that serves canned results per identifier.

    Identifiers without a canned result raise RuntimeError, simulating a
    network/archive failure so we can exercise the per-item resilience.
    """

    def _fake(identifier, *, workspace, strategy="legal_only", timeout=180.0, **_kwargs):
        if identifier in results:
            return results[identifier]
        raise RuntimeError(f"no fixture for {identifier}")

    return _fake


def test_download_papers_rejects_empty_or_invalid_list(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    monkeypatch.setattr(research_tools, "download_paper", _fake_download_factory({}))
    with pytest.raises(ValueError):
        research_tools.download_papers([], workspace=ws)
    with pytest.raises(ValueError):
        research_tools.download_papers(["not-a-doi", "also invalid"], workspace=ws)


def test_download_papers_reports_per_item_success_and_failure(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    monkeypatch.setattr(research_tools, "download_paper", _fake_download_factory({_VALID_DOI: {"files": [str(tmp_path / "a.pdf")]}}))
    progress: list[dict] = []

    result = research_tools.download_papers(
        [_VALID_DOI, _VALID_ARXIV],
        workspace=ws,
        on_progress=progress.append,
    )

    statuses = {item["identifier"]: item["status"] for item in result["items"]}
    assert statuses[_VALID_DOI] == "completed"
    assert statuses[_VALID_ARXIV] == "failed"
    assert result["completed"] == 1
    assert result["failed"] == 1
    assert result["total"] == 2
    assert result["ok"] is False  # one failure
    # on_progress called once at start, then per-item transitions.
    assert len(progress) >= 3
    assert progress[0]["total"] == 2  # initial emit lists both items


def test_download_papers_one_failure_does_not_abort_batch(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    calls: list[str] = []
    good = {"files": [str(tmp_path / "x.pdf")]}

    def _fake(identifier, **kwargs):
        calls.append(identifier)
        if identifier == _VALID_ARXIV:
            raise RuntimeError("boom")
        return good

    monkeypatch.setattr(research_tools, "download_paper", _fake)
    result = research_tools.download_papers([_VALID_DOI, _VALID_ARXIV], workspace=ws)

    assert _VALID_DOI in calls and _VALID_ARXIV in calls
    assert result["completed"] == 1 and result["failed"] == 1


def test_download_papers_isolates_parallel_worker_output_before_commit(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    identifiers = ["10.1000/alpha", "10.1000/beta"]
    barrier = threading.Barrier(2)

    def fake_download(identifier, *, _output_dir=None, **_kwargs):
        staging = Path(str(_output_dir))
        staging.mkdir(parents=True, exist_ok=True)
        barrier.wait(timeout=5)
        output = staging / "download.pdf"
        output.write_bytes(b"%PDF-1.4 " + identifier.encode("ascii"))
        return {"files": [str(output)]}

    monkeypatch.setattr(research_tools, "download_paper", fake_download)
    monkeypatch.setattr(
        research_tools,
        "_crossref_filename_metadata",
        lambda identifier, **_kwargs: {
            "author": [{"family": identifier.rsplit("/", 1)[-1]}],
            "published": {"date-parts": [[2024]]},
            "title": [identifier.rsplit("/", 1)[-1]],
        },
    )

    result = research_tools.download_papers(identifiers, workspace=ws)

    assert result["completed"] == 2
    assert result["failed"] == 0
    assert len(result["files"]) == 2
    committed = [Path(path) for path in result["files"]]
    assert all(path.is_file() for path in committed)
    assert len({path.name for path in committed}) == 2
    assert {
        path.read_bytes().removeprefix(b"%PDF-1.4 ").decode("ascii")
        for path in committed
    } == set(identifiers)


def test_download_papers_cancel_check_stops_loop_cleanly(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    monkeypatch.setattr(
        research_tools,
        "download_paper",
        _fake_download_factory({_VALID_DOI: {"files": [str(tmp_path / "a.pdf")]}}),
    )

    # Cancel after the first real download attempt.
    attempts = {"n": 0}

    def _cancel():
        attempts["n"] += 1
        return attempts["n"] > 1  # allow first item, cancel before second

    with pytest.raises(research_tools._BatchCancelled):
        research_tools.download_papers(
            [_VALID_DOI, _VALID_ARXIV, "10.1038/s41586-024-00001-0"],
            workspace=ws,
            cancel_check=_cancel,
        )


def test_download_papers_cancelled_after_fetch_does_not_commit_file(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    cancelled = {"value": False}

    def fake_download(identifier, *, _output_dir=None, **_kwargs):
        staging = Path(str(_output_dir))
        output = staging / "download.pdf"
        output.write_bytes(b"%PDF-1.4 staged")
        cancelled["value"] = True
        return {"files": [str(output)]}

    monkeypatch.setattr(research_tools, "download_paper", fake_download)

    with pytest.raises(research_tools._BatchCancelled):
        research_tools.download_papers(
            [_VALID_DOI],
            workspace=ws,
            cancel_check=lambda: cancelled["value"],
        )

    committed = [
        path
        for path in research_tools._download_directory(ws).glob("*.pdf")
        if path.is_file()
    ]
    assert committed == []


def test_download_papers_skips_items_already_on_disk(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    download_dir = research_tools._download_directory(ws)
    download_dir.mkdir(parents=True, exist_ok=True)
    # Pre-create a PDF whose filename contains the slugified identifier.
    slug = research_tools._SAFE_NAME.sub("_", _VALID_DOI).lower()
    existing = download_dir / f"{slug}-paper.pdf"
    existing.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(research_tools, "_crossref_filename_metadata", lambda *_args, **_kwargs: {})

    called: list[str] = []
    monkeypatch.setattr(
        research_tools,
        "download_paper",
        lambda identifier, **kwargs: called.append(identifier) or {"files": [str(tmp_path / "should-not-be-used.pdf")]},
    )

    result = research_tools.download_papers([_VALID_DOI], workspace=ws)

    assert result["completed"] == 1
    assert result["items"][0]["status"] == "completed"
    canonical = download_dir / f"{slug}.pdf"
    assert result["items"][0]["files"] == [str(canonical.resolve())]
    assert canonical.exists()
    assert called == []  # download_paper never invoked for the cached item


def test_download_papers_deduplicates_doi_urls_and_arxiv_aliases(tmp_path, monkeypatch):
    ws = _isolated_workspace(tmp_path)
    called: list[str] = []

    def _fake(identifier, **_kwargs):
        called.append(identifier)
        return {"files": []}

    monkeypatch.setattr(research_tools, "download_paper", _fake)
    result = research_tools.download_papers(
        [
            _VALID_DOI,
            f"https://doi.org/{_VALID_DOI}",
            "2401.04088",
            "arXiv:2401.04088",
            "10.48550/arXiv.2401.04088",
        ],
        workspace=ws,
    )

    # Batch downloads intentionally use a small worker pool, so completion
    # order is nondeterministic.  Deduplication is the contract; ordering is
    # not.
    assert set(called) == {_VALID_DOI, "2401.04088"}
    assert result["total"] == 2


def test_canonicalize_download_files_keeps_one_scansci_pdf_named_copy(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    first = download_dir / "10.1038_nature02403_LibGen.pdf"
    second = download_dir / "10.1038_nature02403_OpenAlex.pdf"
    first.write_bytes(b"%PDF-1.4" + b"a" * 128)
    second.write_bytes(b"%PDF-1.4" + b"b" * 256)
    monkeypatch.setattr(
        research_tools,
        "_crossref_filename_metadata",
        lambda *_args, **_kwargs: {
            "author": [{"family": "Reich"}],
            "published-print": {"date-parts": [[2004]]},
            "title": ["The worldwide leaf economics spectrum"],
        },
    )

    files = research_tools._canonicalize_download_files(
        "10.1038/nature02403",
        [str(first), str(second)],
        download_dir=download_dir,
        timeout=15,
    )

    canonical = download_dir / "Reich2004_Worldwide.pdf"
    assert files == [str(canonical.resolve())]
    assert canonical.read_bytes().endswith(b"b" * 256)
    assert not first.exists()
    assert not second.exists()
    index = json.loads((download_dir / ".doi_index.json").read_text(encoding="utf-8"))
    assert index["10.1038/nature02403"] == str(canonical.resolve())


def test_stale_doi_index_entries_are_pruned_before_cache_lookup(tmp_path):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    missing = download_dir / "missing.pdf"
    valid = download_dir / "valid.pdf"
    valid.write_bytes(b"%PDF-1.4 fixture")
    index_path = download_dir / ".doi_index.json"
    index_path.write_text(
        json.dumps(
            {
                "10.1000/missing": str(missing),
                "10.1000/valid": str(valid),
            }
        ),
        encoding="utf-8",
    )

    result = research_tools._identifier_already_downloaded("10.1000/missing", download_dir)
    cleaned = json.loads(index_path.read_text(encoding="utf-8"))

    assert result == []
    assert "10.1000/missing" not in cleaned
    assert cleaned["10.1000/valid"] == str(valid.resolve())


def test_oa_first_uses_one_public_location_before_cli_race(tmp_path, monkeypatch):
    destination = research_tools._download_directory(_isolated_workspace(tmp_path)) / "10.1038_nature02403.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"%PDF-1.4" + b"x" * 128)
    cli_called = False

    def fail_cli(*_args, **_kwargs):
        nonlocal cli_called
        cli_called = True
        raise AssertionError("OA-first should use the selected public location directly")

    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")
    monkeypatch.setattr(research_tools, "subprocess", type("Subprocess", (), {"run": fail_cli}))
    monkeypatch.setattr(
        research_tools,
        "_download_from_public_archives",
        lambda identifier, **_kwargs: {"files": [str(destination)], "source": "OpenAlex best OA"},
    )
    monkeypatch.setattr(
        research_tools,
        "_crossref_filename_metadata",
        lambda *_args, **_kwargs: {
            "author": [{"family": "Reich"}],
            "published-print": {"date-parts": [[2004]]},
            "title": ["The worldwide leaf economics spectrum"],
        },
    )

    result = research_tools.download_paper(
        "10.1038/nature02403",
        workspace=_isolated_workspace(tmp_path),
        strategy="oa_first",
    )

    assert cli_called is False
    assert result["files"] == [str((destination.parent / "Reich2004_Worldwide.pdf").resolve())]


def test_download_paper_defaults_to_oa_first(tmp_path, monkeypatch):
    identifier = "10.1038/nature02403"
    destination = research_tools._download_directory(_isolated_workspace(tmp_path)) / "10.1038_nature02403.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"%PDF-1.4" + b"x" * 128)
    monkeypatch.setattr(
        research_tools,
        "_download_from_public_archives",
        lambda identifier, **_kwargs: {"files": [str(destination)], "source": "OpenAlex best OA"},
    )
    monkeypatch.setattr(
        research_tools,
        "_crossref_filename_metadata",
        lambda *_args, **_kwargs: {
            "author": [{"family": "Reich"}],
            "published-print": {"date-parts": [[2004]]},
            "title": ["The worldwide leaf economics spectrum"],
        },
    )

    result = research_tools.download_paper(
        identifier,
        workspace=_isolated_workspace(tmp_path),
    )

    assert result["strategy"] == "oa_first"


def test_download_papers_retries_on_rate_limit_then_succeeds(tmp_path, monkeypatch):
    """A 429-ish error is retried with backoff rather than recorded as failure."""
    monkeypatch.setattr(research_tools, "_BATCH_MAX_RETRIES", 3)
    monkeypatch.setattr(research_tools, "_cancelable_sleep", lambda _s, _c: None)
    attempts = {"n": 0}

    def _fake(identifier, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return {"files": [str(tmp_path / "recovered.pdf")]}

    monkeypatch.setattr(research_tools, "download_paper", _fake)
    result = research_tools.download_papers([_VALID_DOI], workspace=_isolated_workspace(tmp_path))

    assert attempts["n"] == 3
    assert result["completed"] == 1
    assert result["items"][0]["status"] == "completed"


def test_batch_downloads_keep_source_health_in_stable_download_dir(tmp_path, monkeypatch):
    captured: list[Path] = []
    monkeypatch.setattr(research_tools, "_BATCH_DELAY_MAX", 0.0)

    def fake_download(identifier, **kwargs):
        captured.append(Path(kwargs["_source_health_dir"]).resolve())
        return {"files": [str(tmp_path / "paper.pdf")], "source": "Working repository"}

    monkeypatch.setattr(research_tools, "download_paper", fake_download)

    workspace = _isolated_workspace(tmp_path)
    result = research_tools.download_papers([_VALID_DOI], workspace=workspace)

    assert result["completed"] == 1
    assert captured == [research_tools._download_directory(workspace).resolve()]


def test_download_papers_does_not_retry_permanent_failure(tmp_path, monkeypatch):
    """A genuine 'not found' is not retried — only rate-limit hints are."""
    monkeypatch.setattr(research_tools, "_cancelable_sleep", lambda _s, _c: None)
    attempts = {"n": 0}

    def _fake(identifier, **kwargs):
        attempts["n"] += 1
        raise RuntimeError("paper not found in any archive")

    monkeypatch.setattr(research_tools, "download_paper", _fake)
    result = research_tools.download_papers([_VALID_DOI], workspace=_isolated_workspace(tmp_path))

    assert attempts["n"] == 1  # no retry
    assert result["failed"] == 1
    assert "not found" in result["items"][0]["error"]


def test_download_papers_inter_request_delay_skipped_for_single_item(tmp_path, monkeypatch):
    """A one-item batch must not pay the inter-item delay (first request skips)."""
    monkeypatch.setattr(research_tools, "_BATCH_DELAY_MIN", 999.0)
    monkeypatch.setattr(research_tools, "_BATCH_DELAY_MAX", 999.0)
    monkeypatch.setattr(
        research_tools,
        "download_paper",
        lambda identifier, **kwargs: {"files": [str(tmp_path / "solo.pdf")]},
    )
    result = research_tools.download_papers([_VALID_DOI], workspace=_isolated_workspace(tmp_path))
    assert result["completed"] == 1


def test_download_paper_passes_env_overrides_to_subprocess(tmp_path, monkeypatch):
    """env_overrides merge into the scansci-pdf subprocess environment."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(research_tools.shutil, "which", lambda _n: "scansci-pdf")
    monkeypatch.setattr(research_tools.subprocess, "run", fake_run)
    monkeypatch.setattr(
        research_tools,
        "_download_from_public_archives",
        lambda *a, **k: {"files": [str(tmp_path / "x.pdf")]},
    )
    research_tools.download_paper(
        _VALID_DOI,
        workspace=_isolated_workspace(tmp_path),
        env_overrides={"TOR_PROXY": "socks5h://127.0.0.1:9050"},
    )
    assert captured["env"]["TOR_PROXY"] == "socks5h://127.0.0.1:9050"
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert "PATH" in captured["env"]  # inherited env preserved


def test_download_papers_rotates_circuit_every_n_downloads(tmp_path, monkeypatch):
    """rotate_circuit fires once per rotate_every successful downloads."""
    monkeypatch.setattr(
        research_tools,
        "download_paper",
        lambda identifier, **kwargs: {"files": [str(tmp_path / (identifier[-4:] + ".pdf"))]},
    )
    rotations: list[bool] = []

    def _rotate():
        rotations.append(True)
        return True

    dois = [f"10.1038/s41586-024-{i:05d}-0" for i in range(6)]
    progress: list[dict] = []
    research_tools.download_papers(
        dois,
        workspace=_isolated_workspace(tmp_path),
        rotate_circuit=_rotate,
        rotate_every=2,
        on_progress=progress.append,
    )
    # 6 downloads, rotate_every=2 → rotation before items 3 and 5 (after 2 and 4 succeed).
    assert len(rotations) == 2
    assert progress[-1].get("tor_rotations") == 2
    assert progress[-1].get("tor_last_rotation_ok") is True


def test_download_papers_no_rotation_when_rotate_every_zero(tmp_path, monkeypatch):
    """rotate_every=0 disables rotation entirely even if a callable is given."""
    monkeypatch.setattr(
        research_tools,
        "download_paper",
        lambda identifier, **kwargs: {"files": [str(tmp_path / "x.pdf")]},
    )
    rotations: list[bool] = []
    research_tools.download_papers(
        [_VALID_DOI, "10.1038/s41586-024-00002-9"],
        workspace=_isolated_workspace(tmp_path),
        rotate_circuit=lambda: rotations.append(True) or True,
        rotate_every=0,
    )
    assert rotations == []


def test_search_papers_for_download_uses_resolved_author_works_before_the_download_cli(monkeypatch):
    cli_called = False

    def unexpected_cli(*_args, **_kwargs):
        nonlocal cli_called
        cli_called = True
        raise AssertionError("author-only search should use the resolved OpenAlex author ID")

    def resolved_author(author, **kwargs):
        assert author == "Peter B. Reich"
        assert kwargs["sort"] == "cited_by_count"
        assert kwargs["limit"] == 20
        return {
            "author_resolution": {"author_id": "A5044264078", "display_name": author, "works_count": 1290},
            "items": [{"title": "The worldwide leaf economics spectrum", "doi": "10.1038/nature02403", "authors": [author], "year": 2004, "cited_by_count": 8905, "is_oa": True, "source": "openalex"}],
        }

    monkeypatch.setattr(research_tools, "search_openalex_author_works", resolved_author)
    monkeypatch.setattr(research_tools.subprocess, "run", unexpected_cli)
    result = research_tools.search_papers_for_download(
        author="Peter B. Reich",
        limit=20,
        sort="cited_by_count",
    )

    assert cli_called is False
    assert result["identifiers"] == ["10.1038/nature02403"]
    assert result["items"][0]["cited_by_count"] == 8905
    assert result["author_resolution"]["author_id"] == "A5044264078"


def test_search_papers_for_download_retries_cli_encoding_failure(monkeypatch):
    environments: list[dict[str, str]] = []
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")

    def fake_run(command, **kwargs):
        environments.append(kwargs["env"])
        if len(environments) == 1:
            return research_tools.subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="UnicodeEncodeError: 'gbk' codec can't encode character '\\u0131'",
            )
        return research_tools.subprocess.CompletedProcess(
            command,
            0,
            stdout='{"results":[{"title":"Soil ı study","doi":"10.1038/nature02403"}]}',
            stderr="",
        )

    monkeypatch.setattr(research_tools.subprocess, "run", fake_run)

    result = research_tools.search_papers_for_download("soil")

    assert result["items"][0]["title"] == "Soil ı study"
    assert [environment["PYTHONIOENCODING"] for environment in environments] == [
        "utf-8",
        "utf-8:backslashreplace",
    ]


def test_search_papers_for_download_skips_json_progress_preamble(monkeypatch):
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")

    def fake_run(command, **_kwargs):
        return research_tools.subprocess.CompletedProcess(
            command,
            0,
            stdout='{"event":"author_resolved","author":"Peter B. Reich"}\n{"results":[{"title":"Leaf economics","doi":"10.1038/nature02403"}]}',
            stderr="",
        )

    monkeypatch.setattr(research_tools.subprocess, "run", fake_run)
    result = research_tools.search_papers_for_download("leaf economics", author="Peter B. Reich")

    assert result["total"] == 1
    assert result["items"][0]["title"] == "Leaf economics"


def test_search_papers_for_download_falls_back_to_public_sources_when_cli_output_is_unreadable(monkeypatch):
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")
    monkeypatch.setattr(
        research_tools.subprocess,
        "run",
        lambda command, **_kwargs: research_tools.subprocess.CompletedProcess(command, 0, stdout="progress: 100%", stderr=""),
    )
    monkeypatch.setattr(
        research_tools,
        "search_academic_papers",
        lambda *_args, **_kwargs: {
            "items": [{"title": "Fallback paper", "doi": "10.1038/nature02403", "source": "openalex"}],
            "provider_errors": {},
        },
    )

    result = research_tools.search_papers_for_download("leaf economics")

    assert result["source"] == "public_academic_fallback"
    assert result["identifiers"] == ["10.1038/nature02403"]
    assert result["fallback_reason"] == "download_cli_unavailable_or_unusable"


def test_search_papers_for_download_turns_cli_timeout_into_retryable_failure(monkeypatch):
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")

    def fake_run(*_args, **_kwargs):
        raise research_tools.subprocess.TimeoutExpired("scansci-pdf", 60)

    monkeypatch.setattr(research_tools.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out after 60s"):
        research_tools.search_papers_for_download("evidence-grounded RAG")
