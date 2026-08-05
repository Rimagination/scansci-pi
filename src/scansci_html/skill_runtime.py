"""Deterministic runtime selection for ScanSci's research Skills.

Skill files describe how a model should perform a task.  This module owns the
product-level decision about *which* contract is active.  Keeping that decision
outside prompts makes direct chat, route previews, and durable-run creation
agree without asking a model to route itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


_SKILL_MENTION = re.compile(r"(?<!\S)\$([a-zA-Z0-9._-]+)")
_MAX_SELECTED_SKILLS = 4

RESEARCH_SKILL_IDS = frozenset(
    {
        "scientific-brainstorming",
        "nature-academic-search",
        "literature-review",
        "academic-research-suite",
        "nature-statistics",
        "scientific-visualization",
        "nature-figure",
        "nature-writing",
        "nature-polishing",
        "nature-reviewer",
        "nature-response",
        "nature-data",
        "nature-paper2ppt",
    }
)
_SUITE_PHASE_SKILL_IDS = RESEARCH_SKILL_IDS | {
    "good-question",
    "good-story",
    "scientific-slides",
}


# Rules are ordered from the most specific downstream deliverable to broader
# research activities.  Only the first high-confidence rule is auto-selected;
# explicit $skill selections remain the way to request a deliberate composite.
_INFERENCE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "nature-response",
        re.compile(
            r"(?:回复|回应|答复|response|rebuttal).{0,24}(?:审稿|评审|reviewer)"
            r"|(?:审稿|评审|reviewer).{0,24}(?:意见|comments?).{0,24}(?:回复|回应|答复|response)",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-reviewer",
        re.compile(
            r"(?:审稿|同行评审|预投稿评审|稿件评审|peer\s*review|review\s+this\s+(?:paper|manuscript))",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-polishing",
        re.compile(
            r"(?:润色|学术英语修改|语言校对|英文校对|polish|proofread|copyedit)"
            r".{0,30}(?:论文|稿件|摘要|引言|方法|结果|讨论|manuscript|paper|abstract|academic)?",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-data",
        re.compile(
            r"(?:data\s*availability|数据可用性|数据共享声明|数据仓库|repository\s+plan|FAIR\s*(?:data|原则|审查))",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-paper2ppt",
        re.compile(
            r"(?:论文|paper|article).{0,24}(?:转|做成|制作|生成|汇报).{0,12}(?:pptx?|幻灯片|slides?|journal\s*club)"
            r"|(?:组会|文献汇报|journal\s*club).{0,24}(?:pptx?|幻灯片|slides?|论文|paper)",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-statistics",
        re.compile(
            r"(?:统计审查|统计审核|统计报告|统计分析方案|样本量|效应量|置信区间|多重比较|"
            r"p\s*(?:值|value)|statistical\s+(?:audit|review|reporting))",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-figure",
        re.compile(
            r"(?:Nature\s*风格|期刊投稿|publication[- ]ready|投稿).{0,20}(?:科研图|图表|配图|figure|schematic)"
            r"|(?:机制图|科研示意图|graphical\s+abstract)",
            re.IGNORECASE,
        ),
    ),
    (
        "scientific-visualization",
        re.compile(
            r"(?:科研绘图|科学可视化|数据可视化|图表设计|visuali[sz](?:e|ation)|plot|chart)"
            r".{0,24}(?:数据|结果|实验|论文|figure)?",
            re.IGNORECASE,
        ),
    ),
    (
        "literature-review",
        re.compile(
            r"(?:帮我|请|需要).{0,16}(?:写|做|整理|生成|完成)?(?:一篇|一个)?(?:文献综述|文献回顾|系统综述)"
            r"|(?:写|撰写|起草|整理|生成|完成).{0,20}(?:文献综述|文献回顾|系统综述|literature\s*review|review\s*paper)"
            r"|(?:write|draft|synthesi[sz]e).{0,20}(?:literature\s*review|review\s*paper)",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-academic-search",
        re.compile(
            r"(?:检索|搜索|查找|找|推荐).{0,24}(?:论文|文献|期刊|doi|arxiv)"
            r"|(?:论文|文献|papers?|literature).{0,24}(?:检索|搜索|查找|推荐|search|find|discover)",
            re.IGNORECASE,
        ),
    ),
    (
        "academic-research-suite",
        re.compile(
            r"(?:从选题到投稿|科研全流程|研究全流程|论文全流程|端到端科研|end[- ]to[- ]end\s+(?:research|paper))",
            re.IGNORECASE,
        ),
    ),
    (
        "scientific-brainstorming",
        re.compile(
            r"(?:科研|研究|课题|论文)?.{0,10}(?:头脑风暴|脑暴|选题|研究想法|研究方向|研究假设|"
            r"可检验假设|实验构思|study\s*design|research\s*idea|brainstorm)",
            re.IGNORECASE,
        ),
    ),
    (
        "nature-writing",
        re.compile(
            r"(?:写|撰写|起草|重写|draft|write|rewrite).{0,24}(?:论文|稿件|摘要|引言|方法|结果|讨论|"
            r"manuscript|paper|abstract|introduction|methods?|results?|discussion)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class SkillSelection:
    """Resolved Skill activation with inspectable provenance."""

    selected_ids: tuple[str, ...]
    explicit_ids: tuple[str, ...]
    inferred_ids: tuple[str, ...] = ()
    suppressed_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "selected": list(self.selected_ids),
            "explicit": list(self.explicit_ids),
            "inferred": list(self.inferred_ids),
            "suppressed": list(self.suppressed_ids),
        }


def normalize_skill_ids(values: Iterable[Any]) -> list[str]:
    """Normalize and de-duplicate identifiers while preserving user order."""

    normalized: list[str] = []
    for value in values:
        identifier = str(value or "").strip().lower()
        if identifier and identifier not in normalized:
            normalized.append(identifier)
    return normalized


def last_user_text(messages: list[dict[str, Any]] | None) -> str:
    """Return the final user turn used for Skill activation."""

    for message in reversed(list(messages or [])):
        if str(message.get("role", "")).strip().lower() == "user":
            return str(message.get("content", "") or "").strip()
    return ""


def explicit_skill_ids(payload: dict[str, Any], messages: list[dict[str, Any]] | None = None) -> list[str]:
    """Return only user-declared Skill identifiers from payload and $mentions."""

    requested = payload.get("skills", [])
    values = list(requested) if isinstance(requested, list) else []
    values.extend(match.group(1) for match in _SKILL_MENTION.finditer(last_user_text(messages)))
    return normalize_skill_ids(values)


def infer_research_skill(text: str) -> str:
    """Infer one high-confidence built-in research Skill, or return empty."""

    request = str(text or "").strip()
    if not request:
        return ""
    for identifier, pattern in _INFERENCE_RULES:
        if pattern.search(request):
            return identifier
    return ""


def resolve_skill_selection(
    payload: dict[str, Any],
    messages: list[dict[str, Any]] | None = None,
) -> SkillSelection:
    """Resolve explicit and conservative automatic Skill activation.

    Explicit selections always win over inference.  The suite is a routing
    layer, so a concrete research Skill suppresses it instead of spending model
    context on both the dispatcher and the selected phase contract.
    """

    explicit = explicit_skill_ids(payload, messages)
    inferred: list[str] = []
    if not explicit and payload.get("auto_select_skills", True) is not False:
        candidate = infer_research_skill(last_user_text(messages))
        if candidate:
            inferred.append(candidate)

    selected = [*explicit, *inferred]
    suppressed: list[str] = []
    concrete_research = [
        identifier
        for identifier in selected
        if identifier in _SUITE_PHASE_SKILL_IDS and identifier != "academic-research-suite"
    ]
    if concrete_research and "academic-research-suite" in selected:
        selected.remove("academic-research-suite")
        suppressed.append("academic-research-suite")

    if len(selected) > _MAX_SELECTED_SKILLS:
        suppressed.extend(selected[_MAX_SELECTED_SKILLS:])
        selected = selected[:_MAX_SELECTED_SKILLS]

    return SkillSelection(
        selected_ids=tuple(selected),
        explicit_ids=tuple(identifier for identifier in explicit if identifier in selected),
        inferred_ids=tuple(identifier for identifier in inferred if identifier in selected),
        suppressed_ids=tuple(normalize_skill_ids(suppressed)),
    )


__all__ = [
    "RESEARCH_SKILL_IDS",
    "SkillSelection",
    "explicit_skill_ids",
    "infer_research_skill",
    "last_user_text",
    "normalize_skill_ids",
    "resolve_skill_selection",
]
