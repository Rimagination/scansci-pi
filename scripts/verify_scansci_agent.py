"""Run repeatable end-to-end checks through ScanSci's own agent runtime.

The script uses an isolated workspace and never reads or prints provider keys.
It is intended for release verification, not unit testing.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

from scansci_html.app_settings import load_settings, save_settings
from scansci_html.research_agent import ResearchAgentRuntime


MODELS = ("glm-4.7-flash", "Qwen/Qwen2.5-7B-Instruct")


def _run_stream(runtime: ResearchAgentRuntime, payload: dict[str, object]) -> dict[str, object]:
    started = time.monotonic()
    events = list(runtime.chat_stream(payload))
    terminal = events[-1] if events else {}
    if terminal.get("type") != "RUN_FINISHED":
        raise RuntimeError(str(terminal.get("message") or "ScanSci did not emit RUN_FINISHED"))
    result = dict(terminal.get("result") or {})
    message = dict(result.get("message") or {})
    return {
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "content": str(message.get("content", "")),
        "usage": dict(message.get("usage") or {}),
        "trace": list(message.get("trace") or []),
        "event_types": [str(event.get("type", "")) for event in events],
    }


def verify_model(runtime: ResearchAgentRuntime, workspace: Path, model_id: str) -> dict[str, object]:
    settings = load_settings(workspace)
    settings["active_model"] = {"provider_id": "scansci-managed", "model_id": model_id}
    save_settings(workspace, settings)

    identity = _run_stream(runtime, {
        "chat_mode": "general",
        "messages": [{"role": "user", "content": "你是谁？请说明当前底层模型、ScanSci 版本、可用模式和内置 Skill。"}],
    })
    long_answer = _run_stream(runtime, {
        "chat_mode": "writing",
        "messages": [{
            "role": "user",
            "content": (
                "请写一份结构完整的科研写作质量检查指南，共六个编号部分。"
                "每部分至少包含三条可执行检查，不要省略结尾；最后一行必须单独写【回答完毕】。"
            ),
        }],
    })
    skill = _run_stream(runtime, {
        "chat_mode": "writing",
        "skills": ["good-question"],
        "messages": [{
            "role": "user",
            "content": (
                "$good-question 我有光伏场生态影响方面的本地文献，想研究植被与微气候响应。"
                "无需追问；请在信息不足处作出并标注合理假设，直接给出一张中文好问题卡，"
                "其中必须有‘核心研究问题’小节。"
            ),
        }],
    })
    identity_text = str(identity["content"])
    long_text = str(long_answer["content"])
    skill_text = str(skill["content"])
    checks = {
        "identity_knows_scansci": "ScanSci" in identity_text,
        "identity_knows_model": model_id.casefold() in identity_text.casefold() or model_id.split("/")[-1].casefold() in identity_text.casefold(),
        "identity_knows_skills": "good-question" in identity_text,
        "long_answer_finished": long_text.rstrip().endswith("【回答完毕】"),
        "long_answer_substantial": len(long_text) >= 700,
        "skill_followed": "核心研究问题" in skill_text and ("假设" in skill_text or "研究问题" in skill_text),
        "trace_available": bool(long_answer["trace"]),
        "streamed": long_answer["event_types"].count("TEXT_MESSAGE_CONTENT") >= 2,
    }
    return {
        "model_id": model_id,
        "passed": all(checks.values()),
        "checks": checks,
        "identity": {key: value for key, value in identity.items() if key != "content"},
        "long_answer": {**{key: value for key, value in long_answer.items() if key != "content"}, "characters": len(long_text), "ending": long_text[-80:]},
        "skill": {**{key: value for key, value in skill.items() if key != "content"}, "characters": len(skill_text), "head": skill_text[:120]},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".scansci-diagnostics/agent-e2e.json")
    parser.add_argument("--model", choices=MODELS, action="append", dest="models")
    args = parser.parse_args()
    root = Path(".codex-tmp") / f"agent-e2e-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    root.mkdir(parents=True)
    workspace = root / "workspace.sqlite"
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=root / "evidence.sqlite")
    results = []
    for model_id in (tuple(args.models) if args.models else MODELS):
        try:
            results.append(verify_model(runtime, workspace, model_id))
        except Exception as error:  # release report needs both model results
            results.append({"model_id": model_id, "passed": False, "error": str(error)})
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "framework": "scansci_html.research_agent.ResearchAgentRuntime.chat_stream",
        "results": results,
        "passed": all(bool(result.get("passed")) for result in results),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
