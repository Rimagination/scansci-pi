from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bench import generate_gold_question_templates, validate_gold_questions
from .render.gold_template import render_gold_template_report
from .render.gold_validation import render_gold_validation_report


def build_local_acceptance_workbench(
    db_path: str | Path,
    output_dir: str | Path,
    *,
    questions_per_type: int = 2,
    answer_types: list[str] | None = None,
    min_questions: int = 0,
    required_answer_types: list[str] | None = None,
    min_per_answer_type: int = 0,
) -> dict[str, Any]:
    """Create a local acceptance-set review pack without approving draft gold rows."""

    db = Path(db_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    template_payload = generate_gold_question_templates(
        db,
        questions_per_type=questions_per_type,
        answer_types=answer_types,
    )
    template_rows = list(template_payload.get("templates", []) or [])

    template_path = out / "gold_questions.template.jsonl"
    template_html_path = out / "gold_questions.template.html"
    validation_html_path = out / "gold-validation.template.html"
    review_draft_path = out / "review-draft.template.md"
    readme_path = out / "README.zh.md"
    manifest_path = out / "acceptance-workbench.manifest.json"

    _write_jsonl(template_path, template_rows)
    _write_text(template_html_path, render_gold_template_report(template_rows))

    validation = validate_gold_questions(
        template_path,
        min_questions=min_questions,
        required_answer_types=required_answer_types,
        min_per_answer_type=min_per_answer_type,
        db_path=db,
    )
    _write_text(validation_html_path, render_gold_validation_report(validation))
    _write_text(review_draft_path, render_review_draft_template(template_rows))

    template_summary = dict(template_payload)
    template_summary.pop("templates", None)
    status = "ready_for_benchmark" if validation.get("passed") else "needs_human_review"
    artifacts = {
        "template_jsonl": str(template_path),
        "template_html": str(template_html_path),
        "validation_html": str(validation_html_path),
        "review_draft_template": str(review_draft_path),
        "readme": str(readme_path),
        "manifest": str(manifest_path),
    }
    manifest: dict[str, Any] = {
        "workbench": "local-acceptance",
        "status": status,
        "db_path": str(db),
        "output_dir": str(out),
        "questions_per_type": max(0, int(questions_per_type)),
        "answer_types": list(answer_types or template_summary.get("requested_answer_types", []) or []),
        "min_questions": max(0, int(min_questions)),
        "required_answer_types": list(required_answer_types or []),
        "min_per_answer_type": max(0, int(min_per_answer_type)),
        "artifacts": artifacts,
        "template_summary": template_summary,
        "validation": validation,
        "next_commands": _next_commands(
            db,
            out,
            template_path,
            review_draft_path,
            min_questions=max(0, int(min_questions)),
            required_answer_types=list(required_answer_types or []),
            min_per_answer_type=max(0, int(min_per_answer_type)),
        ),
    }
    _write_text(readme_path, render_acceptance_workbench_readme(manifest))
    _write_json(manifest_path, manifest)
    return manifest


def render_review_draft_template(rows: list[dict[str, Any]], *, max_claims: int = 12) -> str:
    parts = [
        "# Draft claims for grounded annotation review",
        "",
        "This is a starter file for `scansci annotate ground`. It is not a reviewed synthesis.",
        "Use it to test the evidence-bound annotation and review-matrix workflow.",
        "",
        "## Candidate evidence claims",
        "",
    ]
    claim_count = 0
    for row in rows:
        if claim_count >= max_claims:
            break
        question_id = str(row.get("question_id", "")).strip()
        answer_type = str(row.get("answer_type", "")).strip()
        if bool(row.get("answerable", True)):
            points = [str(point).strip() for point in row.get("suggested_required_points", []) or [] if str(point).strip()]
        else:
            points = [
                "The current evidence store should not be used to answer: "
                + str(row.get("suggested_question", "")).strip()
            ]
        for point in points:
            if claim_count >= max_claims:
                break
            if not point:
                continue
            claim_count += 1
            parts.append(f"- [{question_id or answer_type}] {point}")
    if claim_count == 0:
        parts.append("- Add one short, evidence-checkable draft claim here.")
    parts.extend(
        [
            "",
            "## Review notes",
            "",
            "- Replace broad claims with specific, evidence-checkable statements before final review.",
            "- Keep claims tied to source evidence; unsupported claims should stay out of final reports.",
        ]
    )
    return "\n".join(parts) + "\n"


def render_acceptance_workbench_readme(manifest: dict[str, Any]) -> str:
    artifacts = dict(manifest.get("artifacts", {}) or {})
    validation = dict(manifest.get("validation", {}) or {})
    commands = [str(command) for command in manifest.get("next_commands", []) or []]
    command_block = "\n\n".join(f"```powershell\n{command}\n```" for command in commands)
    issues = list(validation.get("issues", []) or [])
    issue_text = "\n".join(
        f"- `{issue.get('question_id', '')}`: {issue.get('message', '')}"
        for issue in issues[:8]
        if isinstance(issue, dict)
    )
    if not issue_text:
        issue_text = "- 当前 validation 没有阻塞项。"
    return "\n".join(
        [
            "# ScanSci 本地 Acceptance Workbench",
            "",
            "这个目录用于把本地 evidence store 变成可人工审阅的 acceptance set 起点。",
            "生成的 `gold_questions.template.jsonl` 默认仍是 `todo`，不能直接当作正式 benchmark gold。",
            "",
            "## 产物",
            "",
            f"- 模板 JSONL：`{artifacts.get('template_jsonl', '')}`",
            f"- HTML 审阅页：`{artifacts.get('template_html', '')}`",
            f"- 模板校验报告：`{artifacts.get('validation_html', '')}`",
            f"- grounded annotation 草稿：`{artifacts.get('review_draft_template', '')}`",
            f"- manifest：`{artifacts.get('manifest', '')}`",
            "",
            "## 人工确认流程",
            "",
            "1. 复制 `gold_questions.template.jsonl` 为 `gold_questions.local.jsonl`。",
            "2. 为每一行填写 `question`，核对 `gold_evidence_ids` 指向的原文。",
            "3. 把确认后的 `suggested_required_points` / `suggested_forbidden_points` 写入正式字段。",
            "4. 只有人工确认后，才把 `annotation_status` 改为 `verified` 或 `approved`。",
            "5. 运行下面的 validation 命令；通过后再跑 benchmark。",
            "",
            "## 当前 validation 摘要",
            "",
            f"- status: `{manifest.get('status', '')}`",
            f"- passed: `{validation.get('passed', False)}`",
            f"- questions: `{validation.get('questions', 0)}`",
            f"- issue_count: `{len(issues)}`",
            "",
            issue_text,
            "",
            "## 下一步命令",
            "",
            command_block,
            "",
        ]
    )


def _next_commands(
    db_path: Path,
    output_dir: Path,
    template_path: Path,
    review_draft_path: Path,
    *,
    min_questions: int,
    required_answer_types: list[str],
    min_per_answer_type: int,
) -> list[str]:
    reviewed_gold = output_dir / "gold_questions.local.jsonl"
    reviewed_validation = output_dir / "gold-validation.local.html"
    details_json = output_dir / "local-benchmark-details.json"
    details_html = output_dir / "local-benchmark-details.html"
    annotation_db = output_dir / "annotation_layers.sqlite"
    annotation_html = output_dir / "grounded-annotation.html"
    annotation_json = output_dir / "grounded-annotation.json"
    viewer_html = output_dir / "annotation-viewer.html"
    review_matrix = output_dir / "review-matrix.csv"
    answer_types = ",".join(required_answer_types)
    validate_parts = [
        "scansci bench validate",
        "--gold",
        _ps_quote(reviewed_gold),
        "--db",
        _ps_quote(db_path),
        "--min-questions",
        str(min_questions),
        "--min-per-answer-type",
        str(min_per_answer_type),
        "--html-output",
        _ps_quote(reviewed_validation),
    ]
    if answer_types:
        validate_parts.extend(["--require-answer-types", _ps_quote(answer_types)])
    return [
        f"Copy-Item -LiteralPath {_ps_quote(template_path)} -Destination {_ps_quote(reviewed_gold)}",
        " ".join(validate_parts),
        " ".join(
            [
                "scansci bench run",
                "--db",
                _ps_quote(db_path),
                "--gold",
                _ps_quote(reviewed_gold),
                "--details-output",
                _ps_quote(details_json),
                "--details-html-output",
                _ps_quote(details_html),
            ]
        ),
        " ".join(
            [
                "scansci annotate ground",
                "--db",
                _ps_quote(db_path),
                "--input",
                _ps_quote(review_draft_path),
                "--layer-db",
                _ps_quote(annotation_db),
                "--output",
                _ps_quote(annotation_html),
                "--json-output",
                _ps_quote(annotation_json),
                "--layer-name",
                _ps_quote("Local acceptance draft review"),
            ]
        ),
        " ".join(
            [
                "scansci annotate viewer",
                "--db",
                _ps_quote(db_path),
                "--layers",
                _ps_quote(annotation_db),
                "--output",
                _ps_quote(viewer_html),
            ]
        ),
        " ".join(
            [
                "scansci annotate review",
                "--layers",
                _ps_quote(annotation_db),
                "--output",
                _ps_quote(review_matrix),
                "--format",
                "csv",
            ]
        ),
    ]


def _ps_quote(value: str | Path) -> str:
    text = str(value)
    return '"' + text.replace('"', '`"') + '"'


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
