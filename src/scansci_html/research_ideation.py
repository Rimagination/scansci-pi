"""Evidence-first research ideation with explicit quality gates.

The workflow produces one candidate, not a list of brainstorms.  Literature
claims must cite indexed full-text evidence.  Coherence and implementability
are kept separate from novelty: a plausible idea is not called novel until it
passes the independent ``novelty_check`` workflow.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .text_tokenization import lexical_tokens


def plan_research_idea(
    direction: str,
    *,
    constraints: str = "",
    chat_client: Any | None = None,
    max_queries: int = 5,
) -> dict[str, Any]:
    clean_direction = " ".join(str(direction).split())
    clean_constraints = " ".join(str(constraints).split())
    if not clean_direction:
        raise ValueError("direction is required")
    fallback = _fallback_plan(clean_direction, clean_constraints, max_queries=max_queries)
    if chat_client is None:
        return fallback
    messages = [
        {
            "role": "system",
            "content": (
                "你是研究构思的证据检索规划器。只定义问题边界和检索方向，不生成研究方案，不列举记忆中的论文。"
                "返回 JSON：{problem_statement,success_criterion,search_queries:[...],perspectives:["
                "{title,question,keywords:[...]}],constraints:[...]}。检索式 3 到 6 条。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"research_direction": clean_direction, "constraints": clean_constraints}, ensure_ascii=False),
        },
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="research_idea_plan") or {}
        return _normalize_plan(clean_direction, clean_constraints, raw, fallback=fallback, max_queries=max_queries)
    except Exception as error:
        return {**fallback, "planning_error": f"{type(error).__name__}: {error}"[:500]}


def diagnose_research_bottleneck(
    plan: dict[str, Any],
    research: dict[str, Any],
    *,
    chat_client: Any | None,
) -> dict[str, Any]:
    known = _known_evidence(research)
    adequacy = _evidence_adequacy(known)
    base = {"phase": "bottleneck_diagnosis", "evidence_adequacy": adequacy}
    if not adequacy["sufficient"]:
        return {**base, "status": "insufficient_evidence", "reason": "瓶颈诊断至少需要 2 篇文献和 3 条全文证据。"}
    if chat_client is None:
        return {**base, "status": "model_required", "reason": "需要正式写作模型执行证据约束的瓶颈诊断。"}
    messages = [
        {
            "role": "system",
            "content": (
                "你是严格的研究瓶颈诊断员。只能使用给定全文引文，不得引用模型记忆。"
                "选择一个最承重、可被研究方案直接作用的瓶颈；不能把‘数据少’或‘效果不够好’当作未经解释的瓶颈。"
                "返回 JSON：{bottleneck_statement,why_load_bearing,evidence_claims:[{text,citation_ids:[...]}],"
                "competing_explanations:[...],success_condition,scope_limits:[...]}。"
            ),
        },
        {"role": "user", "content": json.dumps({"plan": plan, "fulltext_evidence": _compact_evidence(known)}, ensure_ascii=False)},
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="research_bottleneck_diagnosis") or {}
    except Exception as error:
        return {**base, "status": "model_failed", "reason": f"{type(error).__name__}: {error}"[:500]}
    claims = _normalize_cited_claims(raw.get("evidence_claims"), known)
    used_ids = _unique(citation_id for claim in claims for citation_id in claim["citation_ids"])
    document_count = len({str(known[citation_id].get("doc_id", "")) for citation_id in used_ids})
    statement = _clean(raw.get("bottleneck_statement"))
    why = _clean(raw.get("why_load_bearing"))
    if not statement or not why or len(claims) < 2 or document_count < 2:
        return {
            **base,
            "status": "invalid_model_output",
            "reason": "瓶颈陈述未被至少两篇文献中的两条可回跳证据共同支持。",
        }
    return {
        **base,
        "status": "grounded",
        "bottleneck_statement": statement,
        "why_load_bearing": why,
        "evidence_claims": claims,
        "citation_ids": used_ids,
        "competing_explanations": _clean_list(raw.get("competing_explanations"), limit=6),
        "success_condition": _clean(raw.get("success_condition")),
        "scope_limits": _clean_list(raw.get("scope_limits"), limit=6),
    }


def generate_research_candidate(
    plan: dict[str, Any],
    bottleneck: dict[str, Any],
    research: dict[str, Any],
    *,
    chat_client: Any | None,
) -> dict[str, Any]:
    if str(bottleneck.get("status", "")) != "grounded":
        return {"phase": "candidate_generation", "status": "blocked", "reason": "缺少已证据化的研究瓶颈。"}
    if chat_client is None:
        return {"phase": "candidate_generation", "status": "model_required", "reason": "需要正式模型生成单一研究候选。"}
    known = _known_evidence(research)
    messages = [
        {
            "role": "system",
            "content": (
                "你是研究方案设计者。只生成一个候选，不生成备选列表。方案必须直接作用于已诊断瓶颈，"
                "并明确方法步骤、承重假设、最朴素基线、资源预算和可证伪预测。"
                "文献事实必须引用输入 citation_ids；不得声称方案已经新颖，独立查新将在后续完成。"
                "返回 JSON：{title,hook,core_mechanism,mechanism_steps:[{id,action,input,output}],"
                "expected_contribution,assumptions:[...],naive_baseline,why_baseline_insufficient,"
                "evidence_basis:[{text,citation_ids:[...]}],falsification:{experiment,outcome_metric,expected_direction,"
                "load_bearing_variable,negative_control,failure_condition},compute_budget:{hardware,time,api_cost},"
                "claim_strength,open_risks:[...]}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"plan": plan, "grounded_bottleneck": bottleneck, "fulltext_evidence": _compact_evidence(known)},
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="research_candidate") or {}
    except Exception as error:
        return {"phase": "candidate_generation", "status": "model_failed", "reason": f"{type(error).__name__}: {error}"[:500]}
    steps = _normalize_steps(raw.get("mechanism_steps"))
    evidence_basis = _normalize_cited_claims(raw.get("evidence_basis"), known)
    citations = _unique(citation_id for claim in evidence_basis for citation_id in claim["citation_ids"])
    falsification = _string_fields(
        raw.get("falsification"),
        ("experiment", "outcome_metric", "expected_direction", "load_bearing_variable", "negative_control", "failure_condition"),
    )
    budget = _string_fields(raw.get("compute_budget"), ("hardware", "time", "api_cost"))
    candidate = {
        "phase": "candidate_generation",
        "status": "candidate",
        "title": _clean(raw.get("title")),
        "hook": _clean(raw.get("hook")),
        "core_mechanism": _clean(raw.get("core_mechanism")),
        "mechanism_steps": steps,
        "expected_contribution": _clean(raw.get("expected_contribution")),
        "assumptions": _clean_list(raw.get("assumptions"), limit=10),
        "naive_baseline": _clean(raw.get("naive_baseline")),
        "why_baseline_insufficient": _clean(raw.get("why_baseline_insufficient")),
        "evidence_basis": evidence_basis,
        "citation_ids": citations,
        "falsification": falsification,
        "compute_budget": budget,
        "claim_strength": _clean(raw.get("claim_strength")),
        "open_risks": _clean_list(raw.get("open_risks"), limit=10),
        "novelty_status": "not_checked",
    }
    required = (
        candidate["title"],
        candidate["core_mechanism"],
        candidate["expected_contribution"],
        candidate["naive_baseline"],
        candidate["why_baseline_insufficient"],
    )
    if not all(required) or len(steps) < 2 or len(citations) < 2:
        return {
            "phase": "candidate_generation",
            "status": "invalid_model_output",
            "reason": "候选方案缺少核心字段、至少两个方法步骤或至少两条全文依据。",
        }
    return candidate


def audit_candidate_coherence(candidate: dict[str, Any], *, chat_client: Any | None) -> dict[str, Any]:
    base = {"phase": "coherence_audit"}
    if str(candidate.get("status", "")) != "candidate":
        return {**base, "status": "blocked", "verdict": "block", "reason": "没有可审查的候选方案。"}
    if chat_client is None:
        return {
            **base,
            "status": "model_required",
            "verdict": "unverified",
            "reason": "需要隔离的正式模型上下文执行连贯性演算。",
        }
    messages = [
        {
            "role": "system",
            "content": (
                "你是与方案生成者隔离的怀疑型方法审查员。不要重写方案。"
                "依次检查数据流、一个小型具体例子的逐步演算、空输入/并列/边界条件、主张到步骤的映射、"
                "以及同一例子上的朴素基线。这里是模型执行的结构化演算，不得标为真实代码运行。"
                "返回 JSON：{dataflow:[{step_id,inputs,outputs,missing}],dry_run:{example,step_trace:[...],result,"
                "execution_status:'model_simulated'},degenerate_cases:[{case,result}],claim_step_map:[{claim,step_ids,status}],"
                "naive_baseline_comparison,findings:[{severity,step_id,problem,repair}],verdict:'pass|needs_revision|block'}。"
            ),
        },
        {"role": "user", "content": json.dumps({"candidate": candidate}, ensure_ascii=False)},
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="research_candidate_coherence") or {}
    except Exception as error:
        return {**base, "status": "model_failed", "verdict": "unverified", "reason": f"{type(error).__name__}: {error}"[:500]}
    step_ids = {str(step.get("id", "")) for step in list(candidate.get("mechanism_steps", []) or [])}
    dataflow = []
    for value in list(raw.get("dataflow", []) or []):
        if not isinstance(value, dict) or str(value.get("step_id", "")) not in step_ids:
            continue
        dataflow.append(
            {
                "step_id": str(value.get("step_id")),
                "inputs": _clean_list(value.get("inputs"), limit=10),
                "outputs": _clean_list(value.get("outputs"), limit=10),
                "missing": _clean_list(value.get("missing"), limit=10),
            }
        )
    verdict = str(raw.get("verdict", "unverified"))
    if verdict not in {"pass", "needs_revision", "block"}:
        verdict = "unverified"
    dry_run = dict(raw.get("dry_run") or {})
    dry_run["execution_status"] = "model_simulated"
    findings = _normalize_findings(raw.get("findings"), step_ids)
    if len(dataflow) != len(step_ids) or not _clean(dry_run.get("example")) or not list(dry_run.get("step_trace", []) or []):
        verdict = "unverified"
    return {
        **base,
        "status": "audited" if verdict != "unverified" else "invalid_model_output",
        "verdict": verdict,
        "dataflow": dataflow,
        "dry_run": dry_run,
        "degenerate_cases": list(raw.get("degenerate_cases", []) or [])[:8],
        "claim_step_map": list(raw.get("claim_step_map", []) or [])[:12],
        "naive_baseline_comparison": _clean(raw.get("naive_baseline_comparison")),
        "findings": findings,
    }


def audit_candidate_falsifiability(candidate: dict[str, Any]) -> dict[str, Any]:
    fields = dict(candidate.get("falsification") or {})
    required = ("experiment", "outcome_metric", "expected_direction", "load_bearing_variable", "negative_control", "failure_condition")
    missing = [key for key in required if not _clean(fields.get(key))]
    control = _clean(fields.get("negative_control")).casefold()
    variable = _clean(fields.get("load_bearing_variable")).casefold()
    metric = _clean(fields.get("outcome_metric")).casefold()
    issues: list[str] = []
    if control and control in {variable, metric}:
        issues.append("负对照不能只是承重变量或结果指标的同义重复。")
    passed = not missing and not issues
    return {
        "phase": "falsifiability_audit",
        "status": "audited",
        "passed": passed,
        "missing_fields": missing,
        "issues": issues,
        "kill_switch": _clean(fields.get("failure_condition")),
    }


def audit_candidate_implementability(candidate: dict[str, Any], *, chat_client: Any | None) -> dict[str, Any]:
    base = {"phase": "implementability_audit"}
    if str(candidate.get("status", "")) != "candidate":
        return {**base, "status": "blocked", "verdict": "block", "reason": "没有可审查的候选方案。"}
    if chat_client is None:
        return {**base, "status": "model_required", "verdict": "unverified", "reason": "需要正式模型执行可实现性审查。"}
    messages = [
        {
            "role": "system",
            "content": (
                "你是独立的科研工程审查员。保持步骤 ID 和顺序，不得新增研究主张。"
                "把每步改写成可构建规格，列出输入、操作、输出、依赖和未解决空洞。"
                "返回 JSON：{enriched_steps:[{step_id,implementation,dependencies:[...],acceptance_check}],"
                "underspecified_points:[{step_id,hole,fill,severity:'filled|open'}],resource_assessment,"
                "verdict:'ready|needs_work|block'}。"
            ),
        },
        {"role": "user", "content": json.dumps({"candidate": candidate}, ensure_ascii=False)},
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="research_candidate_implementability") or {}
    except Exception as error:
        return {**base, "status": "model_failed", "verdict": "unverified", "reason": f"{type(error).__name__}: {error}"[:500]}
    expected_ids = [str(step.get("id", "")) for step in list(candidate.get("mechanism_steps", []) or [])]
    enriched = []
    for value in list(raw.get("enriched_steps", []) or []):
        if not isinstance(value, dict):
            continue
        step_id = str(value.get("step_id", ""))
        if step_id not in expected_ids:
            continue
        enriched.append(
            {
                "step_id": step_id,
                "implementation": _clean(value.get("implementation")),
                "dependencies": _clean_list(value.get("dependencies"), limit=12),
                "acceptance_check": _clean(value.get("acceptance_check")),
            }
        )
    verdict = str(raw.get("verdict", "unverified"))
    if verdict not in {"ready", "needs_work", "block"}:
        verdict = "unverified"
    if [item["step_id"] for item in enriched] != expected_ids or any(
        not item["implementation"] or not item["acceptance_check"] for item in enriched
    ):
        verdict = "unverified"
    return {
        **base,
        "status": "audited" if verdict != "unverified" else "invalid_model_output",
        "verdict": verdict,
        "enriched_steps": enriched,
        "underspecified_points": list(raw.get("underspecified_points", []) or [])[:20],
        "resource_assessment": _clean(raw.get("resource_assessment")),
    }


def assemble_research_idea_card(
    plan: dict[str, Any],
    research: dict[str, Any],
    bottleneck: dict[str, Any],
    candidate: dict[str, Any],
    coherence: dict[str, Any],
    falsifiability: dict[str, Any],
    implementability: dict[str, Any],
) -> dict[str, Any]:
    known = _known_evidence(research)
    citation_ids = _unique([*list(bottleneck.get("citation_ids", []) or []), *list(candidate.get("citation_ids", []) or [])])
    citation_ids = [citation_id for citation_id in citation_ids if citation_id in known]
    citations = [_citation_payload(known[citation_id]) for citation_id in citation_ids]
    gates = {
        "grounded_bottleneck": str(bottleneck.get("status", "")) == "grounded",
        "single_candidate": str(candidate.get("status", "")) == "candidate",
        "coherence": str(coherence.get("verdict", "")) == "pass",
        "falsifiability": bool(falsifiability.get("passed", False)),
        "implementability": str(implementability.get("verdict", "")) == "ready",
        "citation_integrity": bool(citations),
        "novelty": False,
    }
    ready_except_novelty = all(value for key, value in gates.items() if key != "novelty")
    title = str(candidate.get("title") or plan.get("direction") or "研究构思")
    summary = (
        "候选方案已通过证据、连贯性、可证伪性与可实现性门控；仍需运行独立查新。"
        if ready_except_novelty
        else "候选方案尚有未通过的质量门，不能作为成熟研究方案交付。"
    )
    return {
        "phase": "research_idea_card",
        "status": "ready_for_novelty_check" if ready_except_novelty else "needs_revision",
        "title": title,
        "direction": str(plan.get("direction", "")),
        "constraints": list(plan.get("constraints", []) or []),
        "bottleneck": bottleneck,
        "candidate": candidate,
        "quality_gates": gates,
        "coherence_audit": coherence,
        "falsifiability_audit": falsifiability,
        "implementability_audit": implementability,
        "required_next_gate": {
            "workflow_type": "novelty_check",
            "problem": str(plan.get("problem_statement") or plan.get("direction") or ""),
            "novelty": str(candidate.get("core_mechanism", "")),
        },
        "limitations": [
            "该产物是证据约束的研究候选，不是新颖性证明。",
            "连贯性演算由隔离模型完成结构化模拟，不等于真实代码执行或实验复现。",
        ],
        "reader_answer": {"text": summary, "citation_count": len(citations), "citations": citations},
        "citation_verification": {
            "passed": bool(citations) and all(str(item.get("evidence_id", "")) for item in citations),
            "claim_count": len(list(bottleneck.get("evidence_claims", []) or [])) + len(list(candidate.get("evidence_basis", []) or [])),
            "supported_claim_count": len(list(bottleneck.get("evidence_claims", []) or [])) + len(list(candidate.get("evidence_basis", []) or [])),
            "unsupported_claim_count": 0,
            "used_citation_ids": citation_ids,
        },
    }


def _fallback_plan(direction: str, constraints: str, *, max_queries: int) -> dict[str, Any]:
    terms = _terms(direction)
    constraints_list = [constraints] if constraints else []
    queries = _unique(
        [
            direction,
            f"{direction} limitations failure modes",
            f"{direction} methods benchmark dataset",
            f"{direction} systematic review open problems",
            f"{direction} negative results ablation",
        ]
    )[: max(3, min(6, int(max_queries)))]
    perspectives = [
        {"title": "现有方法", "question": f"现有方法如何处理 {direction}？", "keywords": terms + ["method"]},
        {"title": "承重瓶颈", "question": f"什么限制了 {direction}？", "keywords": terms + ["limitation", "failure"]},
        {"title": "评价与反例", "question": f"哪些证据能证伪 {direction} 的改进？", "keywords": terms + ["evaluation", "negative"]},
    ]
    return {
        "direction": direction,
        "constraints": constraints_list,
        "problem_statement": direction,
        "success_criterion": "提出一个由全文证据支持、可证伪且可实现的单一候选方案。",
        "search_queries": queries,
        "perspectives": perspectives,
        "planner": "deterministic",
    }


def _normalize_plan(
    direction: str,
    constraints: str,
    raw: Any,
    *,
    fallback: dict[str, Any],
    max_queries: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return fallback
    queries = _clean_list(raw.get("search_queries"), limit=max(3, min(6, int(max_queries))))
    perspectives = []
    for value in list(raw.get("perspectives", []) or [])[:5]:
        if not isinstance(value, dict):
            continue
        title = _clean(value.get("title"))
        question = _clean(value.get("question"))
        keywords = _clean_list(value.get("keywords"), limit=10)
        if title and (question or keywords):
            perspectives.append({"title": title, "question": question or title, "keywords": keywords})
    if len(queries) < 3 or len(perspectives) < 2:
        return fallback
    return {
        "direction": direction,
        "constraints": _clean_list(raw.get("constraints"), limit=10) or ([constraints] if constraints else []),
        "problem_statement": _clean(raw.get("problem_statement")) or direction,
        "success_criterion": _clean(raw.get("success_criterion")) or fallback["success_criterion"],
        "search_queries": queries,
        "perspectives": perspectives,
        "planner": "llm",
    }


def _known_evidence(research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("citation_id")): dict(row)
        for row in list(research.get("evidence", []) or [])
        if str(row.get("citation_id", "")).strip() and str(row.get("exact_quote", "")).strip()
    }


def _evidence_adequacy(known: dict[str, dict[str, Any]]) -> dict[str, Any]:
    docs = {str(row.get("doc_id", "")) for row in known.values() if str(row.get("doc_id", ""))}
    return {"sufficient": len(known) >= 3 and len(docs) >= 2, "citation_count": len(known), "document_count": len(docs)}


def _compact_evidence(known: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "citation_id": citation_id,
            "paper": str(row.get("paper", "")),
            "doc_id": str(row.get("doc_id", "")),
            "section": str(row.get("section", "")),
            "exact_quote": str(row.get("exact_quote", ""))[:1200],
        }
        for citation_id, row in list(known.items())[:50]
    ]


def _normalize_cited_claims(value: Any, known: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for item in list(value or [])[:12]:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        citation_ids = [citation_id for citation_id in _clean_list(item.get("citation_ids"), limit=8) if citation_id in known]
        if text and citation_ids:
            claims.append({"text": text, "citation_ids": citation_ids})
    return claims


def _normalize_steps(value: Any) -> list[dict[str, str]]:
    steps = []
    seen: set[str] = set()
    for index, item in enumerate(list(value or [])[:10], start=1):
        if not isinstance(item, dict):
            continue
        step_id = _clean(item.get("id")) or f"s{index}"
        if step_id in seen:
            continue
        seen.add(step_id)
        step = {key: _clean(item.get(key)) for key in ("action", "input", "output")}
        if all(step.values()):
            steps.append({"id": step_id, **step})
    return steps


def _normalize_findings(value: Any, step_ids: set[str]) -> list[dict[str, str]]:
    findings = []
    for item in list(value or [])[:15]:
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("step_id", ""))
        if step_id and step_id not in step_ids:
            continue
        severity = str(item.get("severity", "warning"))
        if severity not in {"info", "warning", "blocking"}:
            severity = "warning"
        findings.append(
            {
                "severity": severity,
                "step_id": step_id,
                "problem": _clean(item.get("problem")),
                "repair": _clean(item.get("repair")),
            }
        )
    return findings


def _citation_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key, "")
        for key in ("citation_id", "evidence_id", "doc_id", "paper", "section", "exact_quote", "html_path", "html_anchor", "reader_url", "doi")
    }


def _string_fields(value: Any, fields: Iterable[str]) -> dict[str, str]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    return {field: _clean(source.get(field)) for field in fields}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return _unique(list(value or []))[:limit]


def _terms(value: str) -> list[str]:
    return _unique(token for token in lexical_tokens(value) if len(token) > 1)[:20]


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value)
        folded = clean.casefold()
        if not clean or folded in seen:
            continue
        seen.add(folded)
        result.append(clean)
    return result
