import json
from pathlib import Path

from scansci_html import cli
from scansci_html.entity_candidates import extract_entity_candidates_from_jsonl, extract_entity_candidates_from_store
from scansci_html.evidence_store import index_evidence_library
from scansci_html.literature_workflow import LiteratureWorkflowConfig, run_literature_workflow, workflow_profile
from scansci_html.rerankers import CascadeReranker


def test_cascade_reranker_trims_between_stages():
    class FirstStage:
        def rerank(self, query, candidates):
            return sorted(candidates, key=lambda hit: -hit["first_score"])

    class SecondStage:
        def rerank(self, query, candidates):
            return sorted(candidates, key=lambda hit: -hit["second_score"])

    candidates = [
        {"evidence_id": "a", "first_score": 3, "second_score": 1},
        {"evidence_id": "b", "first_score": 2, "second_score": 9},
        {"evidence_id": "c", "first_score": 1, "second_score": 99},
    ]

    reranker = CascadeReranker([(FirstStage(), 2), (SecondStage(), None)])
    ranked = reranker.rerank("query", candidates)

    assert [hit["evidence_id"] for hit in ranked] == ["b", "a"]
    assert "c" not in {hit["evidence_id"] for hit in ranked}
    assert ranked[0]["routes"] == ["cascade-stage-1", "cascade-stage-2"]


def test_cascade_reranker_degrades_on_local_cuda_oom_without_failing_retrieval():
    class FirstStage:
        def rerank(self, query, candidates):
            return list(candidates)

    class ExhaustedAccelerator:
        def rerank(self, query, candidates):
            raise RuntimeError("CUDA error: out of memory")

    ranked = CascadeReranker(
        [(FirstStage(), 2), (ExhaustedAccelerator(), None)]
    ).rerank(
        "光伏生态影响",
        [{"evidence_id": "a"}, {"evidence_id": "b"}],
    )

    assert [hit["evidence_id"] for hit in ranked] == ["a", "b"]
    assert all("reranker-fallback" in hit["routes"] for hit in ranked)


def test_onefind_bge_profile_uses_bge_m3_stack():
    profile = workflow_profile("onefind-bge")

    assert profile["embedding_model"] == "BAAI/bge-m3"
    assert profile["reranker"]["model"] == "BAAI/bge-reranker-v2-m3"
    assert profile["reranker"]["provider"] == "cross-encoder"


def test_qwen3_vl_profile_uses_qwen3_vl_embedding():
    profile = workflow_profile("qwen3-vl")

    assert profile["embedding_model"] == "Qwen/Qwen3-VL-Embedding-2B"
    assert profile["embedding_provider"] == "sentence-transformers"
    assert profile["embedding_max_seq_length"] == 512
    assert profile["reranker"]["model"] == "Qwen/Qwen3-Reranker-0.6B"
    assert profile["reranker"]["provider"] == "cross-encoder"


def test_entity_candidates_export_evidence_bound_rows(tmp_path: Path):
    library = _make_workflow_library(tmp_path)
    db_path = tmp_path / "evidence.sqlite"
    output_path = tmp_path / "entities.jsonl"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    summary = extract_entity_candidates_from_store(db_path, output_path=output_path, max_candidates=20)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

    assert summary["candidates"] > 0
    assert any(row["normalized"] == "arabidopsis thaliana" for row in rows)
    arabidopsis = next(row for row in rows if row["normalized"] == "arabidopsis thaliana")
    assert arabidopsis["entity_type"] == "scientific_name"
    assert arabidopsis["evidence_ids"]
    assert arabidopsis["quotes"][0]["text"]


def test_scientific_ngram_profile_recovers_lowercase_keyphrases(tmp_path: Path):
    input_path = tmp_path / "gold_rows.jsonl"
    output_path = tmp_path / "entities.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "record_id": "scienceie:S001",
                "source_text": "Graph neural networks improve citation classification and relation extraction.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = extract_entity_candidates_from_jsonl(
        input_path,
        output_path=output_path,
        profile="scientific-ngram",
        max_candidates=50,
    )
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

    assert summary["profile"] == "scientific-ngram"
    assert any(row["normalized"] == "citation classification" for row in rows)
    assert any(row["normalized"] == "relation extraction" for row in rows)
    assert any(row["entity_type"] == "scientific_keyphrase" for row in rows)


def test_literature_workflow_runs_local_profile(tmp_path: Path):
    library = _make_workflow_library(tmp_path)
    output_dir = tmp_path / "workflow"
    config = LiteratureWorkflowConfig(
        library_dir=library,
        output_dir=output_dir,
        db_path=output_dir / "evidence.sqlite",
        profile="local",
        min_sentence_length=10,
        questions=("What does Arabidopsis thaliana evidence report about growth?",),
        generate_gold_template=True,
        questions_per_type=1,
    )

    manifest = run_literature_workflow(config)

    step_names = [step["name"] for step in manifest["steps"]]
    assert "index" in step_names
    assert "evidence_doctor" in step_names
    assert "corpus_coverage" in step_names
    assert "entity_candidates" in step_names
    assert "ask:question-001" in step_names
    assert "review_matrix" in step_names
    assert "gold_template" in step_names
    assert (output_dir / "workflow.manifest.json").exists()
    assert (output_dir / "workflow.plan.md").exists()
    assert (output_dir / "extraction_schema.template.json").exists()
    assert (output_dir / "entity-candidates.jsonl").exists()
    assert (output_dir / "reports" / "question-001.json").exists()
    assert (output_dir / "review-matrix.csv").exists()
    assert (output_dir / "gold_questions.template.jsonl").exists()


def test_cli_workflow_dry_run_writes_plan(tmp_path: Path, capsys):
    library = tmp_path / "library"
    library.mkdir()
    output_dir = tmp_path / "workflow"

    exit_code = cli.main(
        [
            "workflow",
            "--library-dir",
            str(library),
            "--output-dir",
            str(output_dir),
            "--profile",
            "qwen3-cascade",
            "--question",
            "What evidence should be reviewed?",
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["profile"] == "qwen3-cascade"
    assert payload["steps"][-1]["status"] == "skipped_execution"
    assert (output_dir / "workflow.plan.md").exists()
    assert (output_dir / "workflow.manifest.json").exists()


def test_workflow_writes_paper_style_evaluation_plan_by_default(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    output_dir = tmp_path / "workflow"
    config = LiteratureWorkflowConfig(
        library_dir=library,
        output_dir=output_dir,
        db_path=output_dir / "evidence.sqlite",
        dry_run=True,
    )

    manifest = run_literature_workflow(config)

    evaluation_path = output_dir / "paper-evaluation.plan.md"
    assert manifest["validation_protocol"] == "paper-style-public-benchmark-first"
    assert manifest["artifacts"]["paper_evaluation_plan"] == str(evaluation_path)
    assert evaluation_path.exists()
    evaluation_text = evaluation_path.read_text(encoding="utf-8")
    assert "Public benchmarks are the default validation layer" in evaluation_text
    assert "local gold" in evaluation_text
    assert "optional acceptance" in evaluation_text
    assert not (output_dir / "gold_questions.template.jsonl").exists()


def _make_workflow_library(tmp_path: Path) -> Path:
    library = tmp_path / "library"
    library.mkdir()
    (library / "plant.html").write_text(
        """
        <article class="paper" data-doi="10.1234/plant" data-source-url="https://example.org/plant">
          <h1>Plant Growth Paper</h1>
          <h2>Results</h2>
          <p>Arabidopsis thaliana growth increased after nitrogen treatment in the controlled experiment.</p>
          <p>PCR validation confirmed expression changes in the treatment group.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "forest.html").write_text(
        """
        <article class="paper" data-doi="10.1234/forest" data-source-url="https://example.org/forest">
          <h1>Forest Method Paper</h1>
          <h2>Methods</h2>
          <p>Random Forest models were trained with climate predictors and field observations.</p>
        </article>
        """,
        encoding="utf-8",
    )
    return library
