from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "tmp" / "elsevier-clean-test-cell" / "evidence.sqlite"
DEFAULT_OUT = ROOT / "tmp" / "compare-paperqa2" / "retrieval-answer-comparison"
DEFAULT_PAPERQA_INDEX = "scansci_vs_paperqa2_cell"


CASES: list[dict[str, Any]] = [
    {
        "id": "q1_emerging_hallmarks",
        "question": "What are the two emerging hallmarks of cancer proposed in this paper?",
        "expected": "reprogramming of energy metabolism; evading immune destruction",
        "concepts": [
            {
                "name": "reprogramming of energy metabolism",
                "all": ["energy", "metabolism"],
                "any": ["reprogramming", "reprogrammed", "deregulating", "altered"],
            },
            {
                "name": "evading immune destruction",
                "all": ["immune", "destruction"],
                "any": ["evading", "evade", "evasion"],
            },
        ],
    },
    {
        "id": "q2_enabling_characteristics",
        "question": "What two enabling characteristics do the authors identify?",
        "expected": "genome instability and mutation; tumor-promoting inflammation",
        "concepts": [
            {
                "name": "genome instability and mutation",
                "all": ["instability", "mutations"],
                "any": ["genome", "genomic", "genetic"],
            },
            {
                "name": "tumor-promoting inflammation",
                "all": ["tumor", "promote"],
                "any": ["inflammation", "inflammatory"],
            },
        ],
    },
    {
        "id": "q3_warburg_effect",
        "question": "What is the Warburg effect or aerobic glycolysis described in this paper?",
        "expected": "cancer cells limit energy metabolism largely to glycolysis even in the presence of oxygen",
        "concepts": [
            {"name": "aerobic glycolysis", "all": ["aerobic", "glycolysis"], "any": []},
            {"name": "oxygen present", "all": ["oxygen"], "any": ["presence", "present"]},
            {"name": "cancer-cell glucose metabolism", "all": ["cancer", "metabolism"], "any": ["glucose", "glycolysis"]},
        ],
    },
    {
        "id": "q4_six_hallmarks",
        "question": "What are the six hallmark capabilities listed in the abstract?",
        "expected": (
            "sustaining proliferative signaling; evading growth suppressors; resisting cell death; "
            "enabling replicative immortality; inducing angiogenesis; activating invasion and metastasis"
        ),
        "concepts": [
            {"name": "sustaining proliferative signaling", "all": ["proliferative", "signaling"], "any": ["sustaining", "sustained"]},
            {"name": "evading growth suppressors", "all": ["growth", "suppressors"], "any": ["evading", "evade"]},
            {"name": "resisting cell death", "all": ["cell", "death"], "any": ["resisting", "resist"]},
            {"name": "enabling replicative immortality", "all": ["replicative", "immortality"], "any": ["enabling", "enable"]},
            {"name": "inducing angiogenesis", "all": ["angiogenesis"], "any": ["inducing", "induce"]},
            {"name": "activating invasion and metastasis", "all": ["invasion", "metastasis"], "any": ["activating", "activate"]},
        ],
    },
    {
        "id": "q5_genome_instability",
        "question": "How does genome instability enable hallmark acquisition in this paper?",
        "expected": "genome instability is an enabling characteristic that generates genetic diversity and is causally associated with acquisition of hallmark capabilities",
        "concepts": [
            {
                "name": "genome instability as enabling characteristic",
                "all": ["genome", "instability"],
                "any": ["enabling", "enable"],
            },
            {
                "name": "genetic diversity generation",
                "all": ["genetic", "diversity"],
                "any": ["generates", "expedites"],
            },
            {
                "name": "hallmark acquisition association",
                "all": ["acquisition", "hallmark", "capabilities"],
                "any": ["causally", "associated", "expedites"],
            },
        ],
    },
    {
        "id": "q6_tumor_microenvironment",
        "question": "What additional dimension of complexity do tumors contain besides cancer cells?",
        "expected": "a repertoire of recruited ostensibly normal cells that create the tumor microenvironment and contribute to hallmark traits",
        "concepts": [
            {
                "name": "recruited normal cells",
                "all": ["recruited", "normal", "cells"],
                "any": ["ostensibly", "repertoire"],
            },
            {
                "name": "tumor microenvironment",
                "all": ["tumor", "microenvironment"],
                "any": [],
            },
            {
                "name": "hallmark trait contribution",
                "all": ["hallmark", "traits"],
                "any": ["contribute", "contributes", "contribution"],
            },
        ],
    },
    {
        "id": "q7_inflammation_bioactive_molecules",
        "question": "How can inflammation contribute to multiple hallmark capabilities?",
        "expected": "inflammation supplies bioactive molecules including growth factors, survival factors, proangiogenic factors, and matrix-modifying enzymes",
        "concepts": [
            {
                "name": "bioactive molecules",
                "all": ["bioactive", "molecules"],
                "any": ["supplying", "supplies"],
            },
            {
                "name": "growth and survival factors",
                "all": ["growth", "survival", "factors"],
                "any": [],
            },
            {
                "name": "proangiogenic and matrix-modifying factors",
                "all": ["proangiogenic", "matrix", "enzymes"],
                "any": ["modifying", "extracellular"],
            },
        ],
    },
    {
        "id": "q8_evading_immune_destruction",
        "question": "How may highly immunogenic cancer cells evade immune destruction?",
        "expected": "they disable components of the immune system dispatched to eliminate them",
        "concepts": [
            {
                "name": "disable immune system components",
                "all": ["immune", "system"],
                "any": ["disable", "disabling", "components", "component"],
            },
            {
                "name": "avoid elimination",
                "all": ["eliminate"],
                "any": ["destruction", "dispatched"],
            },
        ],
    },
]


def main() -> int:
    _configure_utf8_stdio()
    args = _parse_args()
    out_dir = _resolve(args.output_dir)
    db_path = _resolve(args.db)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise FileNotFoundError(f"ScanSci evidence DB not found: {db_path}")

    if args.rebuild_paperqa_index:
        _remove_paperqa_index(args.paperqa_index_name)

    if args.run_paperqa:
        if not args.skip_paperqa_index:
            _run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_paperqa2_smoke.py"),
                    "--phase",
                    "index",
                    "--index-name",
                    args.paperqa_index_name,
                    "--clear-paper-dir",
                ],
                label="paperqa2-index",
                cwd=ROOT,
            )

    paperqa_chunks = _load_paperqa_chunks(args.paperqa_index_name) if args.run_paperqa else {}
    rows: list[dict[str, Any]] = []

    for case in CASES:
        case_dir = out_dir / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {case['id']} ===", flush=True)
        print(case["question"], flush=True)

        scansci = _run_scansci_case(case, db_path=db_path, case_dir=case_dir, limit=args.scansci_limit)
        paperqa = (
            _run_paperqa_case(
                case,
                case_dir=case_dir,
                index_name=args.paperqa_index_name,
                chunks=paperqa_chunks,
                timeout=args.paperqa_timeout,
                wall_timeout=args.paperqa_wall_timeout,
                check=not args.keep_going_on_paperqa_error,
            )
            if args.run_paperqa
            else {"skipped": True}
        )
        row = {
            "id": case["id"],
            "question": case["question"],
            "expected": case["expected"],
            "scansci": scansci,
            "paperqa2": paperqa,
        }
        rows.append(row)
        (case_dir / "score.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = _summarize(rows)
    payload = {"cases": rows, "summary": summary}
    (out_dir / "comparison.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "comparison.md").write_text(_render_markdown(payload), encoding="utf-8")
    print(f"\nWrote {out_dir / 'comparison.json'}", flush=True)
    print(f"Wrote {out_dir / 'comparison.md'}", flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare ScanSci and PaperQA2 on same-document retrieval and answer accuracy.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--paperqa-index-name", default=DEFAULT_PAPERQA_INDEX)
    parser.add_argument("--scansci-limit", type=int, default=80)
    parser.add_argument("--run-paperqa", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rebuild-paperqa-index", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--skip-paperqa-index",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Reuse an existing PaperQA2 index instead of rebuilding it.",
    )
    parser.add_argument(
        "--paperqa-timeout",
        type=float,
        default=300.0,
        help="Per-question PaperQA2 agent timeout passed to run_paperqa2_smoke.py.",
    )
    parser.add_argument(
        "--paperqa-wall-timeout",
        type=float,
        default=600.0,
        help="Hard wall-clock timeout for each PaperQA2 subprocess. Use 0 to disable.",
    )
    parser.add_argument(
        "--keep-going-on-paperqa-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Record PaperQA2 failures and continue with later questions.",
    )
    return parser.parse_args()


def _configure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _resolve(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


def _remove_paperqa_index(index_name: str) -> None:
    index_dir = ROOT / "tmp" / "paperqa-src-indexes" / index_name
    resolved = index_dir.resolve()
    tmp_root = (ROOT / "tmp").resolve()
    if not str(resolved).startswith(str(tmp_root)):
        raise RuntimeError(f"Refusing to delete non-tmp PaperQA2 index: {resolved}")
    if index_dir.exists():
        shutil.rmtree(index_dir)


def _run_scansci_case(case: dict[str, Any], *, db_path: Path, case_dir: Path, limit: int) -> dict[str, Any]:
    json_path = case_dir / "scansci.json"
    html_path = case_dir / "scansci.html"
    start = time.perf_counter()
    result = _run(
        [
            sys.executable,
            "-m",
            "scansci_html.cli",
            "ask",
            "--db",
            str(db_path),
            "--question",
            case["question"],
            "--output",
            str(html_path),
            "--json-output",
            str(json_path),
            "--limit",
            str(limit),
            "--max-quotes",
            "8",
            "--answer-provider",
            "local",
            "--quote-provider",
            "local",
            "--verification-provider",
            "local",
        ],
        label=f"scansci-{case['id']}",
        cwd=ROOT,
    )
    elapsed = round(time.perf_counter() - start, 3)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    hit_text = "\n".join(str(hit.get("text", "")) for hit in payload.get("hits", [])[:8])
    evidence_text = "\n".join(
        f"{row.get('claim_target', '')}\n{row.get('exact_quote', '')}" for row in payload.get("evidence_table", [])
    )
    answer_text = json.dumps(payload.get("answer", {}), ensure_ascii=False)
    retrieval_score = _score_concepts(case["concepts"], hit_text)
    evidence_score = _score_concepts(case["concepts"], evidence_text)
    answer_score = _score_concepts(case["concepts"], answer_text + "\n" + evidence_text)
    return {
        "returncode": result.returncode,
        "elapsed_sec": elapsed,
        "json_path": str(json_path),
        "html_path": str(html_path),
        "hit_count": len(payload.get("hits", []) or []),
        "evidence_rows": len(payload.get("evidence_table", []) or []),
        "insufficient_evidence": bool((payload.get("answer", {}) or {}).get("insufficient_evidence", False)),
        "retrieval_concept_recall": retrieval_score,
        "evidence_table_concept_recall": evidence_score,
        "answer_concept_recall": answer_score,
        "top_evidence_ids": [hit.get("evidence_id") for hit in payload.get("hits", [])[:8]],
        "top_quotes": [row.get("exact_quote") for row in payload.get("evidence_table", [])[:4]],
    }


def _run_paperqa_case(
    case: dict[str, Any],
    *,
    case_dir: Path,
    index_name: str,
    chunks: dict[str, str],
    timeout: float,
    wall_timeout: float,
    check: bool,
) -> dict[str, Any]:
    log_dir = case_dir / "paperqa2"
    paperqa_args = [
        sys.executable,
        str(ROOT / "scripts" / "run_paperqa2_smoke.py"),
        "--phase",
        "ask",
        "--index-name",
        index_name,
        "--log-dir",
        str(log_dir),
        "--timeout",
        str(timeout),
        "--question",
        case["question"],
    ]
    if wall_timeout and wall_timeout > 0:
        paperqa_args.extend(["--wall-timeout", str(wall_timeout)])
    start = time.perf_counter()
    result = _run(
        paperqa_args,
        label=f"paperqa2-{case['id']}",
        cwd=ROOT,
        check=check,
    )
    elapsed = round(time.perf_counter() - start, 3)
    log_path = log_dir / f"{index_name}-ask.log"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else result.stdout
    answer = _extract_paperqa_answer(log_text)
    cited_chunk_names = _extract_paperqa_citations(answer)
    cited_chunk_text = "\n".join(chunks.get(name, "") for name in cited_chunk_names)
    answer_score = _score_concepts(case["concepts"], answer)
    cited_score = _score_concepts(case["concepts"], cited_chunk_text)
    return {
        "returncode": result.returncode,
        "elapsed_sec": elapsed,
        "log_path": str(log_path),
        "answer": answer,
        "cited_chunks": cited_chunk_names,
        "cited_chunk_concept_recall": cited_score,
        "answer_concept_recall": answer_score,
        "failed": result.returncode != 0,
    }


def _run(
    command: list[str],
    *,
    label: str,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"[{label}] {' '.join(_quote(part) for part in command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy() | {"PYTHONIOENCODING": "utf-8"},
    )
    if completed.stdout:
        print(completed.stdout[-3000:], flush=True)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{label} failed with code {completed.returncode}")
    return completed


def _load_paperqa_chunks(index_name: str) -> dict[str, str]:
    docs_dir = ROOT / "tmp" / "paperqa-src-indexes" / index_name / "docs"
    if not docs_dir.exists():
        return {}
    venv_python = ROOT / "tmp" / "paperqa-src-venv" / "Scripts" / "python.exe"
    code = (
        "import json,pathlib,pickle,zlib;"
        f"docs_dir=pathlib.Path(r'{docs_dir}');"
        "rows=[];"
        "\nfor p in docs_dir.glob('*.zip'):\n"
        "    docs=pickle.loads(zlib.decompress(p.read_bytes()))\n"
        "    for text in docs.texts:\n"
        "        rows.append({'name': getattr(text, 'name', ''), 'text': getattr(text, 'text', '')})\n"
        "print(json.dumps(rows, ensure_ascii=False))"
    )
    completed = subprocess.run(
        [str(venv_python), "-c", code],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy() | {"PYTHONIOENCODING": "utf-8"},
    )
    if completed.returncode != 0:
        print(completed.stderr, file=sys.stderr, flush=True)
        return {}
    rows = json.loads(completed.stdout or "[]")
    return {str(row.get("name", "")): str(row.get("text", "")) for row in rows}


def _extract_paperqa_answer(log_text: str) -> str:
    marker = "Answer:"
    idx = log_text.rfind(marker)
    if idx < 0:
        return ""
    answer = log_text[idx + len(marker) :]
    answer = re.split(r"\nPaperQA2 ask finished|\nLog written to|\nSummary written to", answer, maxsplit=1)[0]
    lines = [line.strip() for line in answer.splitlines()]
    return " ".join(line for line in lines if line).strip()


def _extract_paperqa_citations(answer: str) -> list[str]:
    matches = re.findall(r"(hanahan2011hallmarksofcancer chunk \d+)", answer)
    seen: list[str] = []
    for match in matches:
        if match not in seen:
            seen.append(match)
    return seen


def _score_concepts(concepts: list[dict[str, Any]], text: str) -> dict[str, Any]:
    normalized = _normalize(text)
    found: list[str] = []
    missing: list[str] = []
    for concept in concepts:
        all_terms = [str(term).lower() for term in concept.get("all", [])]
        any_terms = [str(term).lower() for term in concept.get("any", [])]
        has_all = all(_term_in_text(term, normalized) for term in all_terms)
        has_any = True if not any_terms else any(_term_in_text(term, normalized) for term in any_terms)
        if has_all and has_any:
            found.append(str(concept["name"]))
        else:
            missing.append(str(concept["name"]))
    total = len(concepts)
    return {
        "found": found,
        "missing": missing,
        "recall": round(len(found) / total, 4) if total else 0.0,
    }


def _normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("—", " ").replace("–", " ").replace("�", " ")
    text = re.sub(r"[^a-z0-9β-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _term_in_text(term: str, normalized_text: str) -> bool:
    return re.search(rf"\b{re.escape(term.lower())}\b", normalized_text) is not None


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def avg(path: tuple[str, ...]) -> float:
        values: list[float] = []
        for row in rows:
            value: Any = row
            for key in path:
                value = value.get(key, {}) if isinstance(value, dict) else {}
            if isinstance(value, (int, float)):
                values.append(float(value))
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "case_count": len(rows),
        "scansci_avg_retrieval_concept_recall": avg(("scansci", "retrieval_concept_recall", "recall")),
        "scansci_avg_evidence_table_concept_recall": avg(("scansci", "evidence_table_concept_recall", "recall")),
        "scansci_avg_answer_concept_recall": avg(("scansci", "answer_concept_recall", "recall")),
        "paperqa2_avg_cited_chunk_concept_recall": avg(("paperqa2", "cited_chunk_concept_recall", "recall")),
        "paperqa2_avg_answer_concept_recall": avg(("paperqa2", "answer_concept_recall", "recall")),
        "scansci_total_elapsed_sec": round(sum(float(row["scansci"]["elapsed_sec"]) for row in rows), 3),
        "paperqa2_total_elapsed_sec": round(
            sum(float(row["paperqa2"].get("elapsed_sec", 0.0)) for row in rows if isinstance(row.get("paperqa2"), dict)),
            3,
        ),
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# PaperQA2 vs ScanSci Retrieval/Answer Smoke Comparison",
        "",
        "Same document: `Hallmarks of Cancer: The Next Generation` clean HTML.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Cases | {summary['case_count']} |",
        f"| ScanSci avg top-hit concept recall | {summary['scansci_avg_retrieval_concept_recall']:.2f} |",
        f"| ScanSci avg evidence-table concept recall | {summary['scansci_avg_evidence_table_concept_recall']:.2f} |",
        f"| ScanSci avg answer concept recall | {summary['scansci_avg_answer_concept_recall']:.2f} |",
        f"| PaperQA2 avg cited-chunk concept recall | {summary['paperqa2_avg_cited_chunk_concept_recall']:.2f} |",
        f"| PaperQA2 avg answer concept recall | {summary['paperqa2_avg_answer_concept_recall']:.2f} |",
        f"| ScanSci total elapsed sec | {summary['scansci_total_elapsed_sec']:.2f} |",
        f"| PaperQA2 total elapsed sec | {summary['paperqa2_total_elapsed_sec']:.2f} |",
        "",
        "## Cases",
        "",
        "| ID | Expected | ScanSci hits | ScanSci evidence | ScanSci answer | PaperQA2 cited chunks | PaperQA2 answer |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["cases"]:
        scansci = row["scansci"]
        paperqa = row["paperqa2"]
        lines.append(
            "| {id} | {expected} | {s_hit:.2f} | {s_ev:.2f} | {s_ans:.2f} | {p_cite:.2f} | {p_ans:.2f} |".format(
                id=row["id"],
                expected=row["expected"],
                s_hit=scansci["retrieval_concept_recall"]["recall"],
                s_ev=scansci["evidence_table_concept_recall"]["recall"],
                s_ans=scansci["answer_concept_recall"]["recall"],
                p_cite=paperqa.get("cited_chunk_concept_recall", {}).get("recall", 0.0),
                p_ans=paperqa.get("answer_concept_recall", {}).get("recall", 0.0),
            )
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- ScanSci is scored at sentence/evidence-table level.")
    lines.append("- PaperQA2 is scored at final-answer and cited-chunk level because its CLI exposes paper search and answer citations, not sentence IDs.")
    lines.append("- This is a same-document smoke comparison, not a public benchmark result.")
    return "\n".join(lines) + "\n"


def _quote(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


if __name__ == "__main__":
    raise SystemExit(main())
