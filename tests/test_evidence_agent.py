import json
from pathlib import Path

from scansci_html.evidence_agent import build_agent_next, build_agent_plan, build_agent_status
from scansci_html.evidence_agent_runtime import run_evidence_agent, select_agent_action
from scansci_html.evidence_store import index_evidence_library


def test_agent_status_reports_missing_evidence_store(tmp_path: Path):
    db_path = tmp_path / "missing.sqlite"
    acceptance_dir = tmp_path / "acceptance"

    status = build_agent_status(db_path, acceptance_dir=acceptance_dir)
    next_payload = build_agent_next(db_path, acceptance_dir=acceptance_dir)

    assert status["agent"] == "scansci-evidence-agent"
    assert status["mode"] == "deterministic"
    assert status["status"] == "missing_evidence_store"
    assert status["evidence_store"]["exists"] is False
    assert next_payload["actions"][0]["id"] == "build_evidence_store"
    assert "--library-dir" in next_payload["actions"][0]["command"]


def test_agent_plan_blocks_later_stages_when_evidence_store_is_missing(tmp_path: Path):
    db_path = tmp_path / "missing.sqlite"
    acceptance_dir = tmp_path / "acceptance"

    plan = build_agent_plan(db_path, acceptance_dir=acceptance_dir)
    stages = {stage["id"]: stage for stage in plan["stages"]}

    assert plan["agent"] == "scansci-evidence-agent"
    assert plan["mode"] == "deterministic"
    assert plan["current_stage"] == "evidence_store"
    assert stages["evidence_store"]["state"] == "needs_action"
    assert stages["acceptance_workbench"]["state"] == "blocked"
    assert stages["benchmark"]["state"] == "blocked"
    assert [action["id"] for action in plan["actions"]] == ["build_evidence_store"]


def test_agent_run_dry_run_records_manifest_without_executing(tmp_path: Path):
    db_path = tmp_path / "missing.sqlite"
    acceptance_dir = tmp_path / "acceptance"
    run_output = tmp_path / "agent-run.json"

    manifest = run_evidence_agent(
        db_path,
        acceptance_dir=acceptance_dir,
        dry_run=True,
        run_output=run_output,
    )

    assert manifest["status"] == "dry_run"
    assert manifest["dry_run"] is True
    assert manifest["control_plane"] == {
        "type": "codex",
        "role": "supervisor",
        "supervisor_note": "",
    }
    assert manifest["autonomy"]["level"] == "L1"
    assert manifest["worker_model"]["role"] == "action_decider"
    assert [event["type"] for event in manifest["events"]] == ["observe", "decision", "execution"]
    assert manifest["steps"][0]["workspace"] == "evidence"
    assert manifest["steps"][0]["selected_action"]["id"] == "build_evidence_store"
    assert manifest["steps"][0]["execution"]["executed"] is False
    assert db_path.exists() is False
    assert json.loads(run_output.read_text(encoding="utf-8"))["status"] == "dry_run"


def test_agent_action_selection_falls_back_when_model_returns_invalid_action():
    actions = [
        {"id": "build_evidence_store", "priority": 1, "title": "Build", "requires_human": False},
        {"id": "create_acceptance_workbench", "priority": 2, "title": "Create", "requires_human": False},
    ]

    decision = select_agent_action(
        {"current_stage": "evidence_store", "allowed_actions": actions},
        actions,
        model_decider=lambda context: {"action_id": "delete_project", "rationale": "bad idea"},
    )

    assert decision["source"] == "model_invalid_fallback"
    assert decision["action"]["id"] == "build_evidence_store"
    assert "delete_project" in decision["rationale"]


def test_agent_status_reads_evidence_store_and_acceptance_manifest(tmp_path: Path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "paper.html").write_text(
        """
        <html><body>
          <article class="paper" data-doi="10.1234/agent">
            <h1>Agent Evidence</h1>
            <section>
              <h2>Results</h2>
              <p>Deterministic evidence agents can inspect stored spans, cite anchors,
              and propose the next human review task without asking a model to guess.</p>
            </section>
          </article>
        </body></html>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library_dir, db_path=db_path)

    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    manifest_path = acceptance_dir / "acceptance-workbench.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "needs_human_review",
                "validation": {
                    "passed": False,
                    "questions": 1,
                    "issues": [{"message": "review required"}],
                },
                "artifacts": {
                    "template_jsonl": str(acceptance_dir / "gold_questions.template.jsonl"),
                    "template_html": str(acceptance_dir / "gold_template.html"),
                    "validation_html": str(acceptance_dir / "gold_validation.html"),
                    "local_gold_jsonl": str(acceptance_dir / "gold_questions.local.jsonl"),
                },
            }
        ),
        encoding="utf-8",
    )

    status = build_agent_status(db_path, acceptance_dir=acceptance_dir)

    assert status["status"] == "needs_human_review"
    assert status["evidence_store"]["documents"] == 1
    assert status["evidence_store"]["spans"] >= 1
    assert status["acceptance_workbench"]["manifest_path"] == str(manifest_path)
    assert status["acceptance_workbench"]["validation_passed"] is False
    assert status["next_actions"][0]["id"] == "review_acceptance_gold"


def test_agent_plan_includes_review_and_validate_actions_from_manifest(tmp_path: Path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "paper.html").write_text(
        """
        <html><body>
          <article class="paper" data-doi="10.1234/agent-plan">
            <h1>Agent Plan Evidence</h1>
            <section>
              <h2>Results</h2>
              <p>A planning agent should expose review and validation commands before benchmark execution.</p>
            </section>
          </article>
        </body></html>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library_dir, db_path=db_path)

    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    copy_command = "Copy-Item -LiteralPath template.jsonl -Destination local.jsonl"
    validate_command = "scansci bench validate --gold local.jsonl --db evidence.sqlite"
    (acceptance_dir / "acceptance-workbench.manifest.json").write_text(
        json.dumps(
            {
                "status": "needs_human_review",
                "validation": {"passed": False, "questions": 1, "issues": [{"message": "todo"}]},
                "artifacts": {
                    "template_jsonl": str(acceptance_dir / "gold_questions.template.jsonl"),
                    "local_gold_jsonl": str(acceptance_dir / "gold_questions.local.jsonl"),
                },
                "next_commands": [
                    copy_command,
                    validate_command,
                    "scansci bench run --db evidence.sqlite --gold local.jsonl",
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = build_agent_plan(db_path, acceptance_dir=acceptance_dir)
    stages = {stage["id"]: stage for stage in plan["stages"]}

    assert plan["current_stage"] == "acceptance_workbench"
    assert stages["evidence_store"]["state"] == "ready"
    assert stages["acceptance_workbench"]["state"] == "needs_human_review"
    assert stages["benchmark"]["state"] == "blocked"
    assert [action["id"] for action in stages["acceptance_workbench"]["actions"]] == [
        "review_acceptance_gold",
        "validate_local_gold",
    ]
    assert stages["acceptance_workbench"]["actions"][0]["command"] == copy_command
    assert stages["acceptance_workbench"]["actions"][1]["command"] == validate_command


def test_agent_run_stops_at_human_review_gate_even_when_execute_is_requested(tmp_path: Path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    (library_dir / "paper.html").write_text(
        """
        <html><body>
          <article class="paper" data-doi="10.1234/human-gate">
            <h1>Human Gate</h1>
            <section>
              <h2>Results</h2>
              <p>The agent must not silently approve local gold questions without human review.</p>
            </section>
          </article>
        </body></html>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library_dir, db_path=db_path)
    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    template_path = acceptance_dir / "gold_questions.template.jsonl"
    local_gold_path = acceptance_dir / "gold_questions.local.jsonl"
    template_path.write_text("{}\n", encoding="utf-8")
    (acceptance_dir / "acceptance-workbench.manifest.json").write_text(
        json.dumps(
            {
                "status": "needs_human_review",
                "validation": {"passed": False, "questions": 1, "issues": [{"message": "todo"}]},
                "artifacts": {
                    "template_jsonl": str(template_path),
                    "local_gold_jsonl": str(local_gold_path),
                },
                "next_commands": [
                    f"Copy-Item -LiteralPath \"{template_path}\" -Destination \"{local_gold_path}\"",
                    f"scansci bench validate --gold \"{local_gold_path}\" --db \"{db_path}\"",
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = run_evidence_agent(
        db_path,
        acceptance_dir=acceptance_dir,
        dry_run=False,
        control_plane="codex",
        supervisor_note="Codex reviewed the plan and allowed safe execution only.",
        max_steps=2,
    )

    assert manifest["status"] == "blocked_human"
    assert manifest["autonomy"]["level"] == "L2"
    assert manifest["control_plane"]["supervisor_note"] == "Codex reviewed the plan and allowed safe execution only."
    assert manifest["steps"][0]["selected_action"]["id"] == "review_acceptance_gold"
    assert manifest["steps"][0]["execution"]["executed"] is False
    assert local_gold_path.exists() is False
