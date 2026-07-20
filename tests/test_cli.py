import json
import sys
from pathlib import Path

import pytest

from scansci_html import cli
from scansci_html.models import SaveResult


def _assert_default_official_source_order(source_fetchers):
    source_names = [source.source_name for source in source_fetchers]
    assert source_names[0] == "pmc-jats"
    assert "crossref-fulltext-xml" in source_names
    if "elsevier-xml" in source_names:
        assert source_names.index("elsevier-xml") < source_names.index("crossref-fulltext-xml")


def test_cli_parser_can_use_scansci_brand_program_name(capsys):
    parser = cli.build_parser(prog="scansci")

    try:
        parser.parse_args(["--help"])
    except SystemExit as error:
        assert error.code == 0
    else:
        raise AssertionError("Expected argparse --help to exit.")

    assert capsys.readouterr().out.startswith("usage: scansci ")


def test_cli_detects_console_script_program_names():
    assert cli._detect_program_name("C:/venv/Scripts/scansci.exe") == "scansci"
    assert cli._detect_program_name("C:/venv/Scripts/scansci-html.exe") == "scansci-html"
    assert cli._detect_program_name("pytest") == "scansci-html"


def test_cli_help_shows_layered_command_aliases(capsys):
    parser = cli.build_parser(prog="scansci")

    try:
        parser.parse_args(["--help"])
    except SystemExit as error:
        assert error.code == 0
    else:
        raise AssertionError("Expected argparse --help to exit.")

    output = capsys.readouterr().out
    assert "Layered command aliases:" in output
    assert "capture  fetch|batch|cnki-reader|broker|discover|references" in output
    assert "rag      search|search-jsonl|ask|local-ask|workflow|verify" in output
    assert "annotate entities|model-entities|classify-types|review|ground|viewer" in output
    assert "agent   status|next|plan|run" in output


def test_cli_normalizes_layered_command_aliases_without_changing_flat_commands():
    assert cli._normalize_layered_argv(["capture", "fetch", "10.1234/example"]) == [
        "fetch",
        "10.1234/example",
    ]
    assert cli._normalize_layered_argv(["evidence", "index", "--db", "evidence.sqlite"]) == [
        "index-v2",
        "--db",
        "evidence.sqlite",
    ]
    assert cli._normalize_layered_argv(["bench", "run", "--db", "evidence.sqlite"]) == [
        "bench",
        "--db",
        "evidence.sqlite",
    ]
    assert cli._normalize_layered_argv(["agent", "status", "--db", "evidence.sqlite"]) == [
        "agent-status",
        "--db",
        "evidence.sqlite",
    ]
    assert cli._normalize_layered_argv(["agent", "plan", "--db", "evidence.sqlite"]) == [
        "agent-plan",
        "--db",
        "evidence.sqlite",
    ]
    assert cli._normalize_layered_argv(["agent", "run", "--db", "evidence.sqlite"]) == [
        "agent-run",
        "--db",
        "evidence.sqlite",
    ]
    assert cli._normalize_layered_argv(["annotate", "viewer", "--layers", "annotation_layers.sqlite"]) == [
        "annotation-viewer",
        "--layers",
        "annotation_layers.sqlite",
    ]
    assert cli._normalize_layered_argv(["bench", "--db", "evidence.sqlite"]) == [
        "bench",
        "--db",
        "evidence.sqlite",
    ]


def test_cli_agent_next_reports_deterministic_actions(tmp_path: Path, capsys):
    db_path = tmp_path / "missing.sqlite"
    acceptance_dir = tmp_path / "acceptance"

    exit_code = cli.main(["agent", "next", "--db", str(db_path), "--acceptance-dir", str(acceptance_dir)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["agent"] == "scansci-evidence-agent"
    assert payload["mode"] == "deterministic"
    assert payload["status"] == "missing_evidence_store"
    assert payload["actions"][0]["id"] == "build_evidence_store"


def test_cli_agent_plan_reports_stages(tmp_path: Path, capsys):
    db_path = tmp_path / "missing.sqlite"
    acceptance_dir = tmp_path / "acceptance"

    exit_code = cli.main(["agent", "plan", "--db", str(db_path), "--acceptance-dir", str(acceptance_dir)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["agent"] == "scansci-evidence-agent"
    assert payload["current_stage"] == "evidence_store"
    assert [stage["id"] for stage in payload["stages"]] == [
        "evidence_store",
        "acceptance_workbench",
        "benchmark",
    ]


def test_cli_agent_run_defaults_to_dry_run_and_can_write_manifest(tmp_path: Path, capsys):
    db_path = tmp_path / "missing.sqlite"
    acceptance_dir = tmp_path / "acceptance"
    run_output = tmp_path / "agent-run.json"

    exit_code = cli.main(
        [
            "agent",
            "run",
            "--db",
            str(db_path),
            "--acceptance-dir",
            str(acceptance_dir),
            "--run-output",
            str(run_output),
            "--control-plane",
            "codex",
            "--supervisor-note",
            "Codex supervised this dry-run.",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["agent"] == "scansci-evidence-agent"
    assert payload["status"] == "dry_run"
    assert payload["dry_run"] is True
    assert payload["control_plane"]["type"] == "codex"
    assert payload["control_plane"]["supervisor_note"] == "Codex supervised this dry-run."
    assert payload["autonomy"]["level"] == "L1"
    assert payload["events"][0]["type"] == "observe"
    assert payload["steps"][0]["selected_action"]["id"] == "build_evidence_store"
    assert json.loads(run_output.read_text(encoding="utf-8"))["status"] == "dry_run"


def test_cli_main_normalizes_layered_console_script_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scansci", "rag", "search", "--help"])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 0


def test_cli_evidence_index_alias_runs_index_v2(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "paper.html").write_text(
        """
        <html><body>
          <article class="paper" data-doi="10.1234/layered-cli">
            <h1>Layered CLI</h1>
            <section>
              <h2>Results</h2>
              <p>Layered command aliases preserve evidence indexing behavior.</p>
            </section>
          </article>
        </body></html>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"

    exit_code = cli.main(["evidence", "index", "--library-dir", str(library_dir), "--db", str(db_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert db_path.exists()
    assert payload["db_path"] == str(db_path)
    assert payload["spans"] >= 1


def test_cli_batch_reads_fixed_input_file_and_reports_counts(tmp_path: Path, monkeypatch, capsys):
    input_file = tmp_path / "dois.txt"
    input_file.write_text(
        "\n".join(
            [
                "10.1234/first",
                "",
                "10.1234/second",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    seen: dict[str, object] = {}
    auth_fetcher = object()

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        seen["identifiers"] = list(identifiers)
        seen["output_dir"] = output_dir
        seen["auth_fetcher"] = auth_fetcher
        seen["source_fetchers"] = source_fetchers
        seen["snapshotter"] = snapshotter
        seen["download_assets"] = download_assets
        seen["retry_incomplete_rounds"] = retry_incomplete_rounds
        return [
            SaveResult(identifier="10.1234/first", status="success", doi="10.1234/first"),
            SaveResult(identifier="10.1234/second", status="auth_required", doi="10.1234/second"),
        ]

    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)
    monkeypatch.setattr(cli, "_build_auth_fetcher", lambda args, output_dir: auth_fetcher)

    exit_code = cli.main(["batch", "--input-file", str(input_file), "--output-dir", str(output_dir)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert seen["identifiers"] == ["10.1234/first", "10.1234/second"]
    assert seen["output_dir"] == output_dir
    assert seen["auth_fetcher"] is auth_fetcher
    _assert_default_official_source_order(seen["source_fetchers"])
    assert seen["snapshotter"] is None
    assert seen["download_assets"] is True
    assert seen["retry_incomplete_rounds"] == 1
    assert payload["counts"] == {"success": 1, "auth_required": 1}
    assert [result["identifier"] for result in payload["results"]] == [
        "10.1234/first",
        "10.1234/second",
    ]
    assert payload["results"][0]["structure"] == {}


def test_cli_strips_utf8_bom_from_identifier_file(tmp_path: Path):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("\ufeff10.1234/first\n10.1234/second\n", encoding="utf-8")

    assert cli._read_identifier_file(input_file) == ["10.1234/first", "10.1234/second"]


def test_cli_can_disable_automatic_auth_browser(tmp_path: Path, monkeypatch, capsys):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("10.1234/locked\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        seen["auth_fetcher"] = auth_fetcher
        seen["source_fetchers"] = source_fetchers
        seen["snapshotter"] = snapshotter
        seen["retry_incomplete_rounds"] = retry_incomplete_rounds
        return [SaveResult(identifier="10.1234/locked", status="auth_required")]

    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)
    monkeypatch.setattr(cli, "_build_auth_fetcher", lambda args, output_dir: object())

    exit_code = cli.main(["batch", "--input-file", str(input_file), "--no-auth-browser"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert seen["auth_fetcher"] is None
    _assert_default_official_source_order(seen["source_fetchers"])
    assert seen["snapshotter"] is None
    assert seen["retry_incomplete_rounds"] == 0
    assert payload["counts"] == {"auth_required": 1}


def test_cli_passes_institution_to_auth_browser(tmp_path: Path, monkeypatch):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("10.1234/locked\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_new_browser_fetcher(args, output_dir, *, wait_login_seconds):
        captured["institution"] = args.institution
        captured["wait_login_seconds"] = wait_login_seconds
        return object()

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        return [SaveResult(identifier="10.1234/locked", status="auth_required")]

    monkeypatch.setattr(cli, "_new_browser_fetcher", fake_new_browser_fetcher)
    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)

    cli.main(
        [
            "batch",
            "--input-file",
            str(input_file),
            "--institution",
            "Example University",
        ]
    )

    assert captured == {
        "institution": "Example University",
        "wait_login_seconds": 300,
    }


def test_cli_batch_enables_one_same_session_retry_when_auth_browser_is_available(
    tmp_path: Path, monkeypatch, capsys
):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("10.1126/science.aed5051\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        captured["retry_incomplete_rounds"] = retry_incomplete_rounds
        captured["auth_fetcher"] = auth_fetcher
        return [SaveResult(identifier="10.1126/science.aed5051", status="success")]

    auth_fetcher = object()
    monkeypatch.setattr(cli, "_build_auth_fetcher", lambda args, output_dir: auth_fetcher)
    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)

    exit_code = cli.main(["batch", "--input-file", str(input_file), "--output-dir", str(tmp_path / "out")])

    assert exit_code == 0
    assert captured == {
        "retry_incomplete_rounds": 1,
        "auth_fetcher": auth_fetcher,
    }
    json.loads(capsys.readouterr().out)


def test_cli_index_writes_evidence_manifest(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/index" data-source-url="https://publisher.example/index">
          <h1>Indexed Article</h1>
          <h2>Results</h2>
          <p>The evidence index should preserve this paragraph.</p>
        </article>
        """,
        encoding="utf-8",
    )
    output = tmp_path / "index" / "evidence.jsonl"

    exit_code = cli.main(
        [
            "index",
            "--library-dir",
            str(library_dir),
            "--output",
            str(output),
            "--min-text-length",
            "20",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {"documents": 1, "blocks": 1, "output_path": str(output)}
    assert output.exists()
    assert "The evidence index should preserve this paragraph." in output.read_text(encoding="utf-8")


def test_cli_index_v2_writes_sentence_evidence_store_and_jsonl(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/index-v2">
          <h1>Indexed V2 Article</h1>
          <h2>Results</h2>
          <p id="results-p1">The evidence store should preserve this sentence. It should preserve another sentence.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "index" / "evidence.sqlite"
    jsonl_path = tmp_path / "index" / "spans.jsonl"

    exit_code = cli.main(
        [
            "index-v2",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--jsonl-output",
            str(jsonl_path),
            "--inject-evidence-html",
            "--min-sentence-length",
            "10",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["documents"] == 1
    assert payload["spans"] == 2
    assert payload["db_path"] == str(db_path)
    assert payload["evidence_html_files"] == 1
    assert payload["jsonl_output_path"] == str(jsonl_path)
    assert db_path.exists()
    assert jsonl_path.exists()
    assert (library_dir / "article.evidence.html").exists()


def test_cli_index_md_writes_sentence_evidence_store_and_jsonl(tmp_path: Path, capsys):
    library_dir = tmp_path / "markdown"
    library_dir.mkdir()
    (library_dir / "article.md").write_text(
        """# Markdown Indexed Article

## Results

Markdown indexing should preserve this sentence. It should preserve another Markdown sentence.
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "index" / "markdown.sqlite"
    jsonl_path = tmp_path / "index" / "markdown.jsonl"

    exit_code = cli.main(
        [
            "index-md",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--jsonl-output",
            str(jsonl_path),
            "--min-sentence-length",
            "10",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["documents"] == 1
    assert payload["spans"] == 2
    assert payload["db_path"] == str(db_path)
    assert payload["jsonl_output_path"] == str(jsonl_path)
    assert db_path.exists()
    assert jsonl_path.exists()


def test_cli_search_returns_ranked_evidence_hits(tmp_path: Path, capsys):
    index = tmp_path / "evidence.jsonl"
    index.write_text(
        json.dumps(
            {
                "doc_id": "10.1234/search",
                "block_id": "10.1234_search:evidence-0001",
                "title": "Searchable Paper",
                "doi": "10.1234/search",
                "source_url": "https://publisher.example/search",
                "html_path": "search.html",
                "anchor": "evidence-0001",
                "section": "Results",
                "block_type": "paragraph",
                "text": "The blastopore lip induced a secondary pharynx.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "search",
            "--index",
            str(index),
            "--query",
            "secondary pharynx",
            "--limit",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["query"] == "secondary pharynx"
    assert payload["hits"][0]["block_id"] == "10.1234_search:evidence-0001"
    assert payload["hits"][0]["matched_terms"] == ["secondary", "pharynx"]


def test_cli_search_v2_returns_sentence_evidence_hits(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/search-v2" data-publication-year="2024">
          <h1>Search V2 Article</h1>
          <h2>Results</h2>
          <p id="results-p1">The blastopore lip induced a secondary pharynx. Control explants lacked this structure.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    trace_path = tmp_path / "trace.json"
    cli.main(
        [
            "index-v2",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--min-sentence-length",
            "10",
        ]
    )
    capsys.readouterr()

    exit_code = cli.main(
        [
            "search-v2",
            "--db",
            str(db_path),
            "--query",
            "secondary pharynx blastopore",
            "--limit",
            "2",
            "--per-document-limit",
            "2",
            "--trace-output",
            str(trace_path),
            "--year-min",
            "2020",
            "--embedding-provider",
            "local",
            "--reranker",
            "local",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["query"] == "secondary pharynx blastopore"
    assert payload["trace_output_path"] == str(trace_path)
    assert payload["hits"][0]["evidence_id"] == "10.1234_search-v2.s0001"
    assert payload["hits"][0]["html_anchor"] == "results-p1-s0001"
    assert payload["hits"][0]["publication_year"] == 2024
    assert payload["hits"][0]["routes"] == ["dense", "fts"]
    trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace_payload["query"] == "secondary pharynx blastopore"
    assert trace_payload["hits"][0]["evidence_id"] == "10.1234_search-v2.s0001"
    assert trace_payload["trace"][0]["stage"] == "search"
    assert trace_payload["trace"][0]["returned_hits"] == 1


def test_cli_search_v2_can_return_parent_block_context(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/search-context">
          <h1>Search Context Article</h1>
          <h2>Results</h2>
          <p id="results-p1">The cohort included 120 participants. Treatment increased cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    cli.main(
        [
            "index-v2",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--min-sentence-length",
            "10",
        ]
    )
    capsys.readouterr()

    exit_code = cli.main(
        [
            "search-v2",
            "--db",
            str(db_path),
            "--query",
            "cortical activity language",
            "--limit",
            "1",
            "--context-mode",
            "block",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["hits"][0]["span_text"] == "Treatment increased cortical activity in language regions."
    assert payload["hits"][0]["text"] == (
        "The cohort included 120 participants. "
        "Treatment increased cortical activity in language regions."
    )
    assert payload["hits"][0]["parent_evidence_ids"] == [
        "10.1234_search-context.s0001",
        "10.1234_search-context.s0002",
    ]


def test_cli_search_v2_passes_cross_encoder_reranker_options(monkeypatch, capsys):
    captured: dict[str, object] = {}
    embedding_provider = object()
    reranker = object()

    def fake_build_embedding_provider(
        provider,
        *,
        base_url="",
        api_key="",
        model="",
        dimensions=128,
        batch_size=32,
        max_seq_length=0,
    ):
        captured["embedding_provider"] = (provider, base_url, api_key, model, dimensions)
        return embedding_provider

    def fake_build_reranker(provider, *, model_name="", batch_size=32):
        captured["reranker"] = (provider, model_name, batch_size)
        return reranker

    def fake_search_evidence_store(
        db_path,
        query,
        *,
        limit,
        initial_limit,
        per_document_limit,
        filters,
        embedding_provider,
        reranker,
        context_mode,
    ):
        captured["search"] = {
            "db_path": db_path,
            "query": query,
            "limit": limit,
            "initial_limit": initial_limit,
            "per_document_limit": per_document_limit,
            "filters": filters,
            "embedding_provider": embedding_provider,
            "reranker": reranker,
            "context_mode": context_mode,
        }
        return []

    monkeypatch.setattr(cli, "build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr(cli, "build_reranker", fake_build_reranker)
    monkeypatch.setattr(cli, "search_evidence_store", fake_search_evidence_store)

    exit_code = cli.main(
        [
            "search-v2",
            "--db",
            "evidence.sqlite",
            "--query",
            "cortical activity",
            "--embedding-provider",
            "sentence-transformers",
            "--embedding-model",
            "sentence-transformers/all-MiniLM-L6-v2",
            "--reranker",
            "cross-encoder",
            "--reranker-model",
            "BAAI/bge-reranker-large",
            "--reranker-batch-size",
            "7",
            "--year-min",
            "2020",
            "--section-kind",
            "methods",
            "--section-kind",
            "results",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["embedding_provider"] == (
        "sentence-transformers",
        "",
        "",
        "sentence-transformers/all-MiniLM-L6-v2",
        128,
    )
    assert captured["search"]["embedding_provider"] is embedding_provider
    assert captured["reranker"] == ("cross-encoder", "BAAI/bge-reranker-large", 7)
    assert captured["search"]["reranker"] is reranker
    assert captured["search"]["context_mode"] == "sentence"
    assert captured["search"]["filters"] == {"year_min": 2020, "section_kinds": ["methods", "results"]}
    assert payload == {"query": "cortical activity", "hits": []}


def test_cli_ask_writes_evidence_only_report_and_json(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/ask">
          <h1>Ask Article</h1>
          <h2>Results</h2>
          <p id="results-p1">Model predictions explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    report_path = tmp_path / "report.html"
    json_path = tmp_path / "report.json"
    cli.main(
        [
            "index-v2",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--inject-evidence-html",
            "--min-sentence-length",
            "10",
        ]
    )
    capsys.readouterr()

    exit_code = cli.main(
        [
            "ask",
            "--db",
            str(db_path),
            "--question",
            "What evidence links models to cortical activity?",
            "--output",
            str(report_path),
            "--json-output",
            str(json_path),
            "--limit",
            "5",
            "--min-quotes",
            "1",
            "--min-documents",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["question"] == "What evidence links models to cortical activity?"
    assert payload["claims"] == 1
    assert payload["quotes"] == 1
    assert payload["evidence_rows"] == 1
    assert payload["output_path"] == str(report_path)
    assert payload["json_output_path"] == str(json_path)
    assert report_path.exists()
    assert json_path.exists()
    report_html = report_path.read_text(encoding="utf-8")
    assert "data-quote-id=\"q0001\"" in report_html
    assert "article.evidence.html#results-p1-s0001" in report_html
    assert "Retrieval Audit" in report_html
    assert "What evidence links models to cortical activity?" in report_html
    assert "Evidence sufficient" in report_html
    assert "Minimum quotes" in report_html
    assert "Minimum documents" in report_html
    report_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert report_payload["answer"]["answer"][0]["quote_ids"] == ["q0001"]
    assert report_payload["adequacy"]["profile"] == "auto"
    assert report_payload["adequacy"]["min_quotes"] == 1
    assert report_payload["adequacy"]["min_documents"] == 1
    assert report_payload["evidence_table"][0]["html_path"].endswith("article.evidence.html")


def test_cli_local_ask_indexes_library_then_writes_report_and_json(tmp_path: Path, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/local-ask">
          <h1>Local Ask Article</h1>
          <h2>Results</h2>
          <p id="results-p1">Treatment increased root biomass in the drought experiment.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "work" / "evidence.sqlite"
    report_path = tmp_path / "reports" / "local-ask.html"
    json_path = tmp_path / "reports" / "local-ask.json"

    exit_code = cli.main(
        [
            "local-ask",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--question",
            "What changed root biomass in the drought experiment?",
            "--output",
            str(report_path),
            "--json-output",
            str(json_path),
            "--limit",
            "5",
            "--min-sentence-length",
            "10",
            "--inject-evidence-html",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    report_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["question"] == "What changed root biomass in the drought experiment?"
    assert payload["indexed"] is True
    assert payload["index"]["documents"] == 1
    assert payload["index"]["spans"] == 1
    assert payload["db_path"] == str(db_path)
    assert payload["output_path"] == str(report_path)
    assert payload["json_output_path"] == str(json_path)
    assert payload["evidence_rows"] == 1
    assert db_path.exists()
    assert report_path.exists()
    assert (library_dir / "article.evidence.html").exists()
    assert report_payload["evidence_table"][0]["html_path"].endswith("article.evidence.html")


def test_cli_local_ask_reuses_existing_db_without_reindex(tmp_path: Path, monkeypatch, capsys):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    db_path = tmp_path / "evidence.sqlite"
    db_path.write_text("existing", encoding="utf-8")
    report_path = tmp_path / "report.html"
    captured: dict[str, object] = {}

    def fake_index_evidence_library(*args, **kwargs):
        raise AssertionError("should not reindex existing db by default")

    def fake_answer_question(db_path_arg, question, **kwargs):
        captured["answer"] = {"db_path": db_path_arg, "question": question, **kwargs}
        return {
            "answer": {"question": question, "answer": [], "insufficient_evidence": True},
            "evidence_table": [],
            "quotes": [],
            "query_plan": {},
            "retrieval_queries": [question],
            "adequacy": {"is_sufficient": False},
        }

    monkeypatch.setattr(cli, "index_evidence_library", fake_index_evidence_library)
    monkeypatch.setattr(cli, "answer_question", fake_answer_question)

    exit_code = cli.main(
        [
            "local-ask",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--question",
            "Reusable?",
            "--output",
            str(report_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["indexed"] is False
    assert payload["index"] == {}
    assert captured["answer"]["db_path"] == db_path
    assert report_path.exists()


def test_cli_ask_can_use_llm_quote_answer_and_verification_providers(
    tmp_path: Path, monkeypatch, capsys
):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "article.html").write_text(
        """
        <article class="paper" data-doi="10.1234/ask-llm">
          <h1>Ask LLM Article</h1>
          <h2>Results</h2>
          <p id="results-p1">Model predictions explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    report_path = tmp_path / "report.html"
    json_path = tmp_path / "report.json"
    cli.main(
        [
            "index-v2",
            "--library-dir",
            str(library_dir),
            "--db",
            str(db_path),
            "--inject-evidence-html",
            "--min-sentence-length",
            "10",
        ]
    )
    capsys.readouterr()
    calls: list[str] = []

    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            calls.append(schema_name)
            if schema_name == "extracted_quotes":
                return [
                    {
                        "quote_id": "q9000",
                        "evidence_ids": ["10.1234_ask-llm.s0001"],
                        "exact_quote": "Model predictions explained cortical activity in language regions.",
                        "role": "supports",
                        "claim_hint": "Model predictions explained cortical activity.",
                        "confidence": 0.91,
                    }
                ]
            if schema_name == "answer_claims":
                return {
                    "answer": [
                        {
                            "claim_id": "c9000",
                            "text": "Model predictions explained cortical activity.",
                            "quote_ids": ["q9000"],
                        }
                    ],
                    "limitations": ["Only one local paper was retrieved."],
                }
            if schema_name == "claim_verification":
                return {
                    "claims": [
                        {
                            "claim_id": "c9000",
                            "support_status": "supported",
                            "verification_score": 0.91,
                        }
                    ]
                }
            raise AssertionError(f"unexpected schema: {schema_name}")

    monkeypatch.setattr(cli, "build_chat_json_client", lambda *args, **kwargs: FakeChatClient())

    exit_code = cli.main(
        [
            "ask",
            "--db",
            str(db_path),
            "--question",
            "What evidence links models to cortical activity?",
            "--output",
            str(report_path),
            "--json-output",
            str(json_path),
            "--limit",
            "5",
            "--quote-provider",
            "llm",
            "--answer-provider",
            "llm",
            "--verification-provider",
            "llm",
            "--chat-provider",
            "openai-compatible",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    report_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert calls == ["extracted_quotes", "answer_claims", "claim_verification"]
    assert payload["claims"] == 1
    assert payload["quotes"] == 1
    assert report_payload["quotes"][0]["quote_id"] == "q9000"
    assert report_payload["answer"]["answer"][0]["claim_id"] == "c9000"
    assert report_payload["answer"]["answer"][0]["support_status"] == "supported"
    assert "q9000" in report_path.read_text(encoding="utf-8")


def test_cli_broker_runs_queue_with_visible_browser(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}
    fetcher = object()

    def fake_new_browser_fetcher(args, output_dir, *, wait_login_seconds):
        captured["output_dir"] = output_dir
        captured["wait_login_seconds"] = wait_login_seconds
        captured["keep_browser_open"] = args.keep_browser_open
        captured["institution"] = args.institution
        return fetcher

    class FakeBrokerService:
        def __init__(self, **kwargs):
            captured["service_kwargs"] = kwargs

        def run_forever(self):
            captured["ran"] = True

    monkeypatch.setattr(cli, "_new_browser_fetcher", fake_new_browser_fetcher)
    monkeypatch.setattr(cli, "BrokerService", FakeBrokerService)

    exit_code = cli.main(
        [
            "broker",
            "--broker-dir",
            str(tmp_path / "broker"),
            "--output-dir",
            str(tmp_path / "papers"),
            "--institution",
            "Tsinghua University",
            "--wait-login",
            "900",
        ]
    )

    service_kwargs = captured["service_kwargs"]
    assert exit_code == 0
    assert captured["ran"] is True
    assert captured["wait_login_seconds"] == 900
    assert captured["keep_browser_open"] is True
    assert captured["institution"] == "Tsinghua University"
    assert service_kwargs["fetcher"] is fetcher
    _assert_default_official_source_order(service_kwargs["source_fetchers"])
    assert service_kwargs["snapshotter"] is None
    assert service_kwargs["broker_dir"] == tmp_path / "broker"
    assert service_kwargs["output_dir"] == tmp_path / "papers"
    assert service_kwargs["download_assets"] is True


def test_cli_passes_browser_identity_options_to_browser_fetcher(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeBrowserFetcher:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cli, "BrowserFetcher", FakeBrowserFetcher)
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "fetch",
            "10.1111/gcb.70943",
            "--browser",
            "--browser-proxy-url",
            "socks5://reader:secret@example.proxy:1080",
            "--opencli-extension-dir",
            str(tmp_path / "opencli-extension"),
            "--browser-extension-dir",
            str(tmp_path / "reader-extension"),
        ]
    )

    fetcher = cli._new_browser_fetcher(args, tmp_path / "out", wait_login_seconds=0)

    assert isinstance(fetcher, FakeBrowserFetcher)
    assert captured["browser_proxy_url"] == "socks5://reader:secret@example.proxy:1080"
    assert captured["browser_extension_dirs"] == ";".join(
        [
            str(tmp_path / "opencli-extension"),
            str(tmp_path / "reader-extension"),
        ]
    )


def test_cli_can_disable_browser_extensions_for_a_run(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeBrowserFetcher:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cli, "BrowserFetcher", FakeBrowserFetcher)
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "fetch",
            "10.1111/gcb.70943",
            "--browser",
            "--opencli-extension-dir",
            str(tmp_path / "opencli-extension"),
            "--disable-browser-extensions",
        ]
    )

    cli._new_browser_fetcher(args, tmp_path / "out", wait_login_seconds=0)

    assert captured["browser_extension_dirs"] == ""


def test_cli_can_disable_image_asset_downloads(tmp_path: Path, monkeypatch):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("10.1234/illustrated\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        seen["download_assets"] = download_assets
        return [SaveResult(identifier="10.1234/illustrated", status="success")]

    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)
    monkeypatch.setattr(cli, "_build_auth_fetcher", lambda args, output_dir: None)

    exit_code = cli.main(
        [
            "batch",
            "--input-file",
            str(input_file),
            "--no-download-assets",
        ]
    )

    assert exit_code == 0
    assert seen["download_assets"] is False


def test_cli_can_disable_official_sources(tmp_path: Path, monkeypatch, capsys):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("10.1234/locked\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        seen["source_fetchers"] = source_fetchers
        return [SaveResult(identifier="10.1234/locked", status="auth_required")]

    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)
    monkeypatch.setattr(cli, "_build_auth_fetcher", lambda args, output_dir: None)

    exit_code = cli.main(
        [
            "batch",
            "--input-file",
            str(input_file),
            "--no-official-sources",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert seen["source_fetchers"] == []
    assert payload["counts"] == {"auth_required": 1}


def test_cli_passes_snapshotter_when_snapshot_dir_requested(tmp_path: Path, monkeypatch):
    input_file = tmp_path / "dois.txt"
    input_file.write_text("10.1234/snapshot\n", encoding="utf-8")
    snapshotter = object()
    seen: dict[str, object] = {}

    def fake_snapshotter(snapshot_dir):
        seen["snapshot_dir"] = snapshot_dir
        return snapshotter

    def fake_batch_save_clean_html(
        identifiers,
        *,
        output_dir,
        fetcher,
        source_fetchers=None,
        auth_fetcher,
        snapshotter=None,
        min_text_length,
        download_assets,
        retry_incomplete_rounds,
    ):
        seen["snapshotter"] = snapshotter
        return [SaveResult(identifier="10.1234/snapshot", status="success")]

    monkeypatch.setattr(cli, "RawHtmlSnapshotter", fake_snapshotter, raising=False)
    monkeypatch.setattr(cli, "batch_save_clean_html", fake_batch_save_clean_html)
    monkeypatch.setattr(cli, "_build_auth_fetcher", lambda args, output_dir: None)

    exit_code = cli.main(
        [
            "batch",
            "--input-file",
            str(input_file),
            "--snapshot-dir",
            str(tmp_path / "snapshots"),
        ]
    )

    assert exit_code == 0
    assert seen["snapshot_dir"] == tmp_path / "snapshots"
    assert seen["snapshotter"] is snapshotter


def test_cli_broker_submit_waits_for_response(tmp_path: Path, monkeypatch, capsys):
    broker_dir = tmp_path / "broker"
    captured: dict[str, object] = {}

    def fake_enqueue_request(actual_broker_dir, identifier):
        captured["broker_dir"] = actual_broker_dir
        captured["identifier"] = identifier
        return "request-1"

    def fake_wait_for_response(actual_broker_dir, request_id, *, timeout_seconds, poll_interval_seconds):
        captured["wait"] = (actual_broker_dir, request_id, timeout_seconds, poll_interval_seconds)
        return {
            "request_id": request_id,
            "status": "success",
            "identifier": "10.1126/science.aed5051",
            "doi": "10.1126/science.aed5051",
            "title": "Fast cell wall softening causes Venus flytrap closure",
            "source_url": "https://www.science.org/doi/10.1126/science.aed5051",
            "output_path": str(tmp_path / "paper.html"),
            "warnings": [],
            "error": "",
        }

    monkeypatch.setattr(cli, "enqueue_request", fake_enqueue_request)
    monkeypatch.setattr(cli, "wait_for_response", fake_wait_for_response)

    exit_code = cli.main(
        [
            "broker-submit",
            "10.1126/science.aed5051",
            "--broker-dir",
            str(broker_dir),
            "--wait-response",
            "--timeout-seconds",
            "12",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["broker_dir"] == broker_dir
    assert captured["identifier"] == "10.1126/science.aed5051"
    assert captured["wait"] == (broker_dir, "request-1", 12.0, 0.5)
    assert payload["status"] == "success"
    assert payload["request_id"] == "request-1"


def test_cli_credentials_list_reports_redacted_status(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "credential_status",
        lambda: [
            {
                "name": "elsevier-api-key",
                "status": "present",
                "source": "keyring",
                "value": "***",
                "env_vars": ["ELSEVIER_API_KEY"],
            }
        ],
        raising=False,
    )

    exit_code = cli.main(["credentials", "list"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["credentials"][0]["name"] == "elsevier-api-key"
    assert payload["credentials"][0]["value"] == "***"


def test_cli_credentials_set_writes_to_keyring(monkeypatch, capsys):
    captured: dict[str, str] = {}

    def fake_set_credential(name, value):
        captured["name"] = name
        captured["value"] = value

    monkeypatch.setattr(cli, "set_credential", fake_set_credential, raising=False)

    exit_code = cli.main(
        [
            "credentials",
            "set",
            "elsevier-api-key",
            "--value",
            "secret-key",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured == {"name": "elsevier-api-key", "value": "secret-key"}
    assert payload == {"status": "stored", "name": "elsevier-api-key"}


def test_cli_credentials_set_can_read_from_gui_prompt(monkeypatch, capsys):
    captured: dict[str, str] = {}

    def fake_set_credential(name, value):
        captured["name"] = name
        captured["value"] = value

    monkeypatch.setattr(cli, "set_credential", fake_set_credential, raising=False)
    monkeypatch.setattr(cli, "_read_gui_secret", lambda name: "gui-secret\n", raising=False)

    exit_code = cli.main(
        [
            "credentials",
            "set",
            "elsevier-api-key",
            "--gui",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured == {"name": "elsevier-api-key", "value": "gui-secret"}
    assert payload == {"status": "stored", "name": "elsevier-api-key"}


def test_cli_credentials_set_rejects_value_and_gui_together(monkeypatch):
    monkeypatch.setattr(cli, "set_credential", lambda name, value: None, raising=False)

    try:
        cli.main(
            [
                "credentials",
                "set",
                "elsevier-api-key",
                "--value",
                "secret-key",
                "--gui",
            ]
        )
    except SystemExit as error:
        assert str(error) == "Use either --value or --gui, not both."
    else:
        raise AssertionError("Expected --value and --gui to be mutually exclusive.")


def test_cli_credentials_delete_removes_keyring_secret(monkeypatch, capsys):
    captured: dict[str, str] = {}

    def fake_delete_credential(name):
        captured["name"] = name

    monkeypatch.setattr(cli, "delete_credential", fake_delete_credential, raising=False)

    exit_code = cli.main(["credentials", "delete", "springer-nature-api-key"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured == {"name": "springer-nature-api-key"}
    assert payload == {"status": "deleted", "name": "springer-nature-api-key"}


def test_cli_opencli_bridge_doctor_emits_diagnostics(tmp_path: Path, monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_build_opencli_bridge_diagnostics(
        config,
        *,
        runtime_probe,
        use_config_profile,
        timeout_sec,
        keep_open,
    ):
        captured["config"] = config
        captured["runtime_probe"] = runtime_probe
        captured["use_config_profile"] = use_config_profile
        captured["timeout_sec"] = timeout_sec
        captured["keep_open"] = keep_open
        return {"verdict": "connected", "configured_extension_count": 1}

    monkeypatch.setattr(cli, "build_opencli_bridge_diagnostics", fake_build_opencli_bridge_diagnostics)

    exit_code = cli.main(
        [
            "opencli-bridge-doctor",
            "--opencli-extension-dir",
            str(tmp_path / "opencli-extension"),
            "--browser-profile",
            str(tmp_path / "profile"),
            "--runtime-probe",
            "--use-browser-profile",
            "--timeout-seconds",
            "3",
            "--keep-open",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    config = captured["config"]
    assert exit_code == 0
    assert payload["verdict"] == "connected"
    assert config.browser_extension_dirs == str(tmp_path / "opencli-extension")
    assert config.chrome_profile_dir == str(tmp_path / "profile")
    assert captured["runtime_probe"] is True
    assert captured["use_config_profile"] is True
    assert captured["timeout_sec"] == 3.0
    assert captured["keep_open"] is True
