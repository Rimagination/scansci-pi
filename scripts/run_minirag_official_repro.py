from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

from tqdm import trange


EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_ALIASES = {
    "PHI": "microsoft/Phi-3.5-mini-instruct",
    "GLM": "THUDM/glm-edge-1.5b-chat",
    "MiniCPM": "openbmb/MiniCPM3-4B",
    "qwen25": "Qwen/Qwen2.5-3B-Instruct",
    "qwen35": "Qwen/Qwen3.5-2B",
    "qwen35tiny": "Qwen/Qwen3.5-0.8B",
    "qwen": "Qwen/Qwen3.5-2B",
}


def main() -> int:
    _configure_utf8_stdio()

    parser = argparse.ArgumentParser(description="Run an official MiniRAG reproduction with explicit local paths.")
    parser.add_argument("--official-root", default="external/minirag-official", help="Path to the cloned MiniRAG repo.")
    parser.add_argument("--phase", choices=["index", "qa", "both"], default="both")
    parser.add_argument("--model", choices=sorted(MODEL_ALIASES), default="qwen")
    parser.add_argument("--llm-provider", choices=["openai", "hf"], default="openai")
    parser.add_argument("--qa-provider", choices=["openai", "hf"], default="hf")
    parser.add_argument(
        "--openai-model",
        default="gpt-4o-mini",
        help="OpenAI-compatible chat model name used when --llm-provider/--qa-provider is openai.",
    )
    parser.add_argument("--workingdir", required=True)
    parser.add_argument("--datapath", required=True)
    parser.add_argument("--querypath", required=True)
    parser.add_argument("--outputpath", required=True)
    parser.add_argument("--question-limit", type=int, default=0)
    parser.add_argument(
        "--insert-mode",
        choices=["batch", "loop"],
        default="batch",
        help=(
            "batch inserts all txt files in one MiniRAG call; loop mirrors the official "
            "Step_0_index.py file-by-file insertion but can re-extract cumulative chunks."
        ),
    )
    parser.add_argument("--llm-max-async", type=int, default=1, help="Maximum concurrent LLM calls.")
    parser.add_argument(
        "--entity-gleaning",
        type=int,
        default=0,
        help="MiniRAG entity extraction gleaning rounds. 0 minimizes API calls for smoke tests.",
    )
    parser.add_argument(
        "--openai-min-interval",
        type=float,
        default=0.0,
        help="Minimum seconds between OpenAI-compatible chat calls.",
    )
    parser.add_argument("--tiktoken-model", default="gpt-4", help="Use gpt-4 to avoid first-run gpt-4o BPE fetch.")
    parser.add_argument(
        "--offline-tokenizer-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Patch MiniRAG token counting with a local regex tokenizer to avoid first-run tiktoken BPE downloads.",
    )
    parser.add_argument("--max-new-tokens", type=int, default=200)
    args = parser.parse_args()

    official_root = Path(args.official_root).resolve()
    sys.path.insert(0, str(official_root))

    if args.llm_provider == "openai" and args.phase in {"index", "both"}:
        _require_openai_env()
    if args.qa_provider == "openai" and args.phase in {"qa", "both"}:
        _require_openai_env()

    Path(args.workingdir).mkdir(parents=True, exist_ok=True)
    Path(args.outputpath).parent.mkdir(parents=True, exist_ok=True)

    from minirag import MiniRAG, QueryParam
    from minirag.llm import hf_embed, hf_model_complete
    from minirag.llm.openai import openai_complete_if_cache
    from minirag.utils import EmbeddingFunc
    from transformers import AutoModel, AutoTokenizer

    if args.offline_tokenizer_fallback:
        _install_offline_tokenizer_fallback()

    llm_model_name = MODEL_ALIASES[args.model]
    embedding_tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL)
    embedding_model = AutoModel.from_pretrained(EMBEDDING_MODEL)
    openai_model_func = _openai_model_func(
        args.openai_model,
        openai_complete_if_cache,
        min_interval_seconds=max(float(args.openai_min_interval), 0.0),
    )
    llm_func = openai_model_func if args.llm_provider == "openai" else hf_model_complete

    rag = MiniRAG(
        working_dir=args.workingdir,
        llm_model_func=llm_func,
        llm_model_max_token_size=args.max_new_tokens,
        llm_model_max_async=max(int(args.llm_max_async), 1),
        llm_model_name=llm_model_name,
        entity_extract_max_gleaning=max(int(args.entity_gleaning), 0),
        tiktoken_model_name=args.tiktoken_model,
        embedding_func=EmbeddingFunc(
            embedding_dim=384,
            max_token_size=1000,
            func=lambda texts: hf_embed(texts, tokenizer=embedding_tokenizer, embed_model=embedding_model),
        ),
    )

    if args.phase in {"index", "both"}:
        txt_files = _find_txt_files(Path(args.datapath))
        if args.insert_mode == "batch":
            print(f"index batch: {len(txt_files)} txt files")
            rag.insert([path.read_text(encoding="utf-8") for path in txt_files])
        else:
            for index, txt_path in enumerate(txt_files, start=1):
                print(f"index {index}/{len(txt_files)}: {txt_path}")
                rag.insert(txt_path.read_text(encoding="utf-8"))

    if args.phase in {"qa", "both"}:
        if args.qa_provider != args.llm_provider:
            qa_llm_func = openai_model_func if args.qa_provider == "openai" else hf_model_complete
            rag.llm_model_func = qa_llm_func
        _run_qa(
            rag,
            QueryParam,
            Path(args.querypath),
            Path(args.outputpath),
            question_limit=max(args.question_limit, 0),
        )

    return 0


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _require_openai_env() -> None:
    missing = [name for name in ("OPENAI_API_KEY", "OPENAI_API_BASE") if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "MiniRAG official OpenAI path requires environment variables: "
            + ", ".join(missing)
            + ". Set them in the shell before running this wrapper."
        )


def _openai_model_func(model_name: str, openai_complete_if_cache, *, min_interval_seconds: float):
    last_call_at = 0.0

    async def complete(prompt, system_prompt=None, history_messages=[], keyword_extraction=False, **kwargs) -> str:
        nonlocal last_call_at
        elapsed = time.monotonic() - last_call_at
        if elapsed < min_interval_seconds:
            time.sleep(min_interval_seconds - elapsed)
        kwargs.pop("keyword_extraction", None)
        result = await openai_complete_if_cache(
            model_name,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            **kwargs,
        )
        last_call_at = time.monotonic()
        return result

    return complete


def _install_offline_tokenizer_fallback() -> None:
    import minirag.operate as operate
    import minirag.utils as utils

    def encode(content: str, model_name: str = "offline-regex") -> list[str]:
        return re.findall(r"\w+|[^\w\s]", str(content or ""), flags=re.UNICODE)

    def decode(tokens: list[str], model_name: str = "offline-regex") -> str:
        return " ".join(str(token) for token in tokens)

    utils.encode_string_by_tiktoken = encode
    utils.decode_tokens_by_tiktoken = decode
    operate.encode_string_by_tiktoken = encode
    operate.decode_tokens_by_tiktoken = decode


def _find_txt_files(root_path: Path) -> list[Path]:
    return sorted(path for path in root_path.rglob("*.txt") if path.is_file())


def _run_qa(rag, QueryParam, query_path: Path, output_path: Path, *, question_limit: int) -> None:
    rows = _read_queries(query_path)
    if question_limit > 0:
        rows = rows[:question_limit]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    completed = set()
    if output_path.exists():
        with output_path.open("r", encoding="utf-8", newline="") as handle:
            completed = {row["Question"] for row in csv.DictReader(handle)}

    with output_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not completed:
            writer.writerow(["Question", "Gold Answer", "minirag"])
        for row_index in trange(len(rows)):
            row = rows[row_index]
            question = row["Question"]
            if question in completed:
                continue
            try:
                answer = rag.query(question, param=QueryParam(mode="mini")).replace("\n", "").replace("\r", "")
            except Exception as exc:
                print("Error in minirag answer", exc)
                answer = "Error"
            writer.writerow([question, row["Gold Answer"], answer])


def _read_queries(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    raise SystemExit(main())
