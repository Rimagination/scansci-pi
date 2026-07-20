from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION = "What are the two emerging hallmarks of cancer proposed in this paper?"
DEFAULT_MODEL = "openai/deepseek-v4-pro-202606"
DEFAULT_DOC = (
    ROOT
    / "tmp"
    / "elsevier-clean-test-cell"
    / "10.1016_j.cell.2011.02.013_hallmarks_of_cancer_the_next_generation.html"
)


def main() -> int:
    _configure_utf8_stdio()
    args = _parse_args()

    venv = _resolve(args.paperqa_venv)
    source_root = _resolve(args.paperqa_source)
    paper_dir = _resolve(args.paper_dir)
    index_dir = _resolve(args.index_dir)
    pqa_home = _resolve(args.pqa_home)
    log_dir = _resolve(args.log_dir)
    document = _resolve(args.document) if args.document else None

    pqa_exe = _pqa_executable(venv)
    failures = _doctor(
        pqa_exe=pqa_exe,
        source_root=source_root,
        model=args.model,
        strict=args.phase != "doctor",
    )
    if failures and args.phase != "doctor":
        return 2

    if args.phase == "doctor":
        print("PaperQA2 smoke doctor: OK" if not failures else "PaperQA2 smoke doctor: FAILED")
        return 0 if not failures else 2

    _ensure_paperqa_client_data(venv=venv, source_root=source_root)
    _prepare_paper_dir(paper_dir=paper_dir, document=document, clear=args.clear_paper_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    pqa_home.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    if args.phase in {"index", "both"}:
        results.append(
            _run_pqa(
                label="index",
                pqa_exe=pqa_exe,
                env=_paperqa_env(pqa_home),
                log_path=log_dir / f"{args.index_name}-index.log",
                wall_timeout=args.wall_timeout,
                args=[
                    "--index",
                    args.index_name,
                    *_common_pqa_args(args, paper_dir, index_dir, include_agent_type=False),
                    "index",
                    str(paper_dir),
                ],
            )
        )

    if args.phase in {"ask", "both"}:
        results.append(
            _run_pqa(
                label="ask",
                pqa_exe=pqa_exe,
                env=_paperqa_env(pqa_home),
                log_path=log_dir / f"{args.index_name}-ask.log",
                wall_timeout=args.wall_timeout,
                args=[
                    "--index",
                    args.index_name,
                    *_common_pqa_args(args, paper_dir, index_dir, include_agent_type=True),
                    "--agent.rebuild_index",
                    "false",
                    "--agent.timeout",
                    str(args.timeout),
                    "--answer.evidence_k",
                    str(args.evidence_k),
                    "--answer.evidence_skip_summary",
                    str(args.evidence_skip_summary).lower(),
                    "--answer.answer_max_sources",
                    str(args.answer_max_sources),
                    "--answer.max_concurrent_requests",
                    str(args.max_concurrent_requests),
                    "ask",
                    args.question,
                ],
                expect_answer=args.fail_on_empty_answer,
            )
        )

    summary_path = log_dir / f"{args.index_name}-summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Summary written to {summary_path}")
    return 0 if all(item["returncode"] == 0 for item in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a controlled PaperQA2 smoke test using the local source-zip venv, "
            "sparse retrieval, and an OpenAI-compatible model."
        )
    )
    parser.add_argument("--phase", choices=["doctor", "index", "ask", "both"], default="both")
    parser.add_argument("--paperqa-venv", default="tmp/paperqa-src-venv")
    parser.add_argument("--paperqa-source", default="tmp/paper-qa-main-src/paper-qa-main")
    parser.add_argument("--paper-dir", default="tmp/paperqa-src-docs")
    parser.add_argument("--index-dir", default="tmp/paperqa-src-indexes")
    parser.add_argument("--pqa-home", default="tmp/paperqa-src-home")
    parser.add_argument("--log-dir", default="tmp/compare-paperqa2/paperqa2-runs")
    parser.add_argument("--index-name", default="scansci_cell_paperqa2")
    parser.add_argument("--document", default=str(DEFAULT_DOC))
    parser.add_argument("--clear-paper-dir", action="store_true", help="Delete existing files in --paper-dir first.")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--embedding", default="sparse")
    parser.add_argument(
        "--use-doc-details",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Let PaperQA2 enrich metadata through Crossref/Semantic Scholar. Off by default to avoid external 429s.",
    )
    parser.add_argument(
        "--agent-type",
        default="fake",
        help="PaperQA2 agent type. Use fake by default to avoid tool_choice issues on some thinking models.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--wall-timeout",
        type=float,
        default=None,
        help="Hard wall-clock timeout for the pqa subprocess. Use 0 to disable.",
    )
    parser.add_argument("--evidence-k", type=int, default=5)
    parser.add_argument(
        "--evidence-skip-summary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip per-evidence LLM summarization to reduce API calls for smoke tests.",
    )
    parser.add_argument("--answer-max-sources", type=int, default=3)
    parser.add_argument("--max-concurrent-requests", type=int, default=1)
    parser.add_argument(
        "--fail-on-empty-answer",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Treat PaperQA2's zero-exit empty answer as a smoke-test failure.",
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


def _pqa_executable(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "pqa.exe"
    return venv / "bin" / "pqa"


def _doctor(pqa_exe: Path, source_root: Path, model: str, strict: bool) -> list[str]:
    failures: list[str] = []
    checks = [
        (pqa_exe.exists(), f"Missing pqa executable: {pqa_exe}"),
        (source_root.exists(), f"Missing PaperQA2 source root: {source_root}"),
    ]
    if model.startswith("openai/"):
        checks.extend(
            [
                (bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY is not set."),
                (
                    bool(os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")),
                    "OPENAI_API_BASE or OPENAI_BASE_URL is not set.",
                ),
            ]
        )
    for ok, message in checks:
        if ok:
            continue
        failures.append(message)
        print(f"ERROR: {message}", file=sys.stderr)

    if strict and failures:
        print("Run with --phase doctor after fixing the environment.", file=sys.stderr)
    return failures


def _ensure_paperqa_client_data(venv: Path, source_root: Path) -> None:
    dst = venv / "Lib" / "site-packages" / "paperqa" / "clients" / "client_data" / "journal_quality.csv"
    if dst.exists():
        return

    src = source_root / "src" / "paperqa" / "clients" / "client_data" / "journal_quality.csv"
    if not src.exists():
        raise FileNotFoundError(
            f"PaperQA2 source zip did not provide journal_quality.csv at {src}."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied missing PaperQA2 client data to {dst}")


def _prepare_paper_dir(paper_dir: Path, document: Path | None, clear: bool) -> None:
    if clear and paper_dir.exists():
        _remove_children(paper_dir)
    paper_dir.mkdir(parents=True, exist_ok=True)
    if document is None:
        return
    if not document.exists():
        raise FileNotFoundError(f"Document not found: {document}")
    target = paper_dir / document.name
    if document.resolve() != target.resolve():
        shutil.copy2(document, target)
    print(f"Paper directory ready: {paper_dir}", flush=True)


def _remove_children(directory: Path) -> None:
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _paperqa_env(pqa_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PQA_HOME"] = str(pqa_home)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _common_pqa_args(
    args: argparse.Namespace,
    paper_dir: Path,
    index_dir: Path,
    *,
    include_agent_type: bool,
) -> list[str]:
    values = [
        "--agent.index.name",
        args.index_name,
        "--agent.index.paper_directory",
        str(paper_dir),
        "--agent.index.index_directory",
        str(index_dir),
        "--llm",
        args.model,
        "--summary_llm",
        args.model,
        "--agent.agent_llm",
        args.model,
        "--parsing.enrichment_llm",
        args.model,
        "--embedding",
        args.embedding,
        "--parsing.multimodal",
        "false",
        "--parsing.use_doc_details",
        str(args.use_doc_details).lower(),
    ]
    if include_agent_type:
        values.extend(["--agent.agent_type", args.agent_type])
    return values


def _run_pqa(
    *,
    label: str,
    pqa_exe: Path,
    env: dict[str, str],
    log_path: Path,
    wall_timeout: float | None,
    args: list[str],
    expect_answer: bool = False,
) -> dict[str, object]:
    command = [str(pqa_exe), *args]
    print(f"\n== PaperQA2 {label} ==", flush=True)
    print(_format_command(command), flush=True)
    start = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timeout = wall_timeout if wall_timeout and wall_timeout > 0 else None
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        output, _ = process.communicate()
    if output:
        print(output, end="", flush=True)
    returncode = process.returncode if not timed_out else 124
    elapsed_sec = round(time.perf_counter() - start, 3)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    if expect_answer and returncode == 0 and _answer_looks_empty(output):
        print("PaperQA2 ask returned code 0 but produced an empty answer.", file=sys.stderr, flush=True)
        returncode = 3
    print(f"PaperQA2 {label} finished with code {returncode} in {elapsed_sec}s", flush=True)
    print(f"Log written to {log_path}", flush=True)
    return {
        "label": label,
        "returncode": returncode,
        "elapsed_sec": elapsed_sec,
        "log_path": str(log_path),
        "command": command,
        "timed_out": timed_out,
    }


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        process.kill()


def _answer_looks_empty(output: str) -> bool:
    marker = "Answer:"
    idx = output.rfind(marker)
    if idx < 0:
        return True
    tail = output[idx + len(marker) :]
    tail = tail.replace("\x1b", "")
    cleaned = "".join(ch for ch in tail if ch.isprintable()).strip()
    return not cleaned


def _format_command(command: list[str]) -> str:
    return " ".join(_quote(part) for part in command)


def _quote(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


if __name__ == "__main__":
    raise SystemExit(main())
