"""Host-owned routing for a free-form ScanSci composer.

The composer deliberately stays open ended.  This module only recognises a
small set of *explicit* requests that benefit from a durable product
workflow, such as public academic discovery or a multi-step evidence task.
Everything else remains a normal model conversation.

No model is involved in this decision: the result must be predictable,
inspectable, and safe to repeat on the server when a task is created.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


_SPACE = re.compile(r"\s+")
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
_ARXIV = re.compile(r"\b(?:arxiv\s*:\s*)?\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE)

_DEEP_RESEARCH = re.compile(
    r"(?:深度研究|深度调研|全面调研|系统(?:性)?(?:调研|研究|综述)|研究全景|"
    r"deep\s*research|systematic\s*review|research\s*landscape)",
    re.IGNORECASE,
)
_ACADEMIC_SEARCH = re.compile(
    r"(?:联网|在线|公开来源|web|学术|论文|文献|期刊|doi|arxiv|openalex|semantic\s*scholar|"
    r"academic|papers?|literature).{0,28}(?:检索|搜索|查找|找(?:到|出)?|推荐|"
    r"search|find|discover|recommend)"
    r"|(?:检索|搜索|查找|找(?:到|出)?|推荐|search|find|discover|recommend).{0,28}"
    r"(?:联网|在线|公开来源|web|学术|论文|文献|期刊|doi|arxiv|openalex|semantic\s*scholar|academic|papers?|literature)",
    re.IGNORECASE,
)
_DOWNLOAD = re.compile(
    r"(?:下载|获取全文|获取\s*pdf|下载\s*pdf|download|get\s+(?:the\s+)?(?:pdf|full\s*text))",
    re.IGNORECASE,
)
_LOCAL_PRODUCT_STATUS = re.compile(
    r"(?:"
    r"(?:当前|现在|刚才|已有|有一个|这个|后台|失败的?|未完成的?|卡住的?).{0,20}"
    r"(?:组件|资源|模型|运行时|下载|安装|任务).{0,20}"
    r"(?:是什么|是哪一个|哪个|什么|情况|状态|进度|到哪(?:一)?步|到哪里|原因|为什么|怎么回事|知道|看到|查看)"
    r"|(?:组件|资源|模型|运行时|下载|安装).{0,12}(?:任务|失败|错误|状态|进度|情况).{0,20}"
    r"(?:是什么|是哪一个|哪个|什么|情况|状态|进度|到哪(?:一)?步|到哪里|原因|为什么|怎么回事|知道|看到|查看)?"
    r"|(?:failed|stalled|current|active).{0,20}(?:component|resource|model|runtime|download|install|task)"
    r"|(?:component|resource|model|runtime|download|install).{0,20}(?:status|progress|failure|error|task)"
    r")",
    re.IGNORECASE,
)
_PRESENTATION = re.compile(r"(?:ppt|幻灯片|演示文稿|汇报(?:材料|幻灯片)?|presentation\s*(?:deck)?|slides?)", re.IGNORECASE)
_LOCAL_EVIDENCE = re.compile(
    r"(?:知识库|资料库|本地资料|本地文献|我的文献|原文证据|逐句引用|"
    r"local\s+(?:knowledge|library)|my\s+(?:library|papers?))",
    re.IGNORECASE,
)
_LONG_FORM_WRITING = re.compile(
    r"(?:写(?:一篇|成|个)?|撰写|起草|生成).{0,20}(?:综述|文献回顾|论文初稿|研究报告|"
    r"literature\s*review|review\s*paper|research\s*report)",
    re.IGNORECASE,
)
_EVIDENCE_REVIEW = re.compile(
    r"(?:证据综述|基于(?:原文)?证据.{0,20}(?:综述|回顾)|"
    r"(?:逐句|逐条)引用.{0,24}(?:综述|回顾)|notebooklm(?:式|风格)?(?:综述|回顾)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FreeformTaskRoute:
    """A conservative host decision for one free-form request."""

    route: str
    workflow_type: str = ""
    presentation_mode: str = "general"
    reason: str = ""
    scope: str = "conversation"
    input_payload: dict[str, Any] | None = None

    @property
    def durable(self) -> bool:
        return self.route == "durable_run"

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "durable": self.durable,
            "workflow_type": self.workflow_type,
            "presentation_mode": self.presentation_mode,
            "reason": self.reason,
            "scope": self.scope,
            "input": dict(self.input_payload or {}),
        }


def route_freeform_task(text: str, *, has_knowledge: bool) -> FreeformTaskRoute:
    """Return a minimal, deterministic route for explicit product requests.

    ``has_knowledge`` represents an actively selected, usable local library.
    We never turn a vague request into an evidence or writing workflow merely
    because a library happens to exist in the workspace.
    """

    request = _SPACE.sub(" ", str(text or "").strip())
    if not request:
        return FreeformTaskRoute(route="direct_chat", reason="empty_request")

    # Questions about ScanSci itself must reach the deterministic local-facts
    # responder.  In particular, the word "下载" in "失败的组件下载任务"
    # describes application state; it is not an instruction to find a paper.
    if _LOCAL_PRODUCT_STATUS.search(request):
        return FreeformTaskRoute(route="direct_chat", reason="local_product_status")

    identifiers = _paper_identifiers(request)
    if _DOWNLOAD.search(request):
        if len(identifiers) == 1:
            return FreeformTaskRoute(
                route="durable_run",
                workflow_type="paper_download",
                presentation_mode="download",
                reason="explicit_paper_download",
                scope="public_academic",
                input_payload={"identifier": identifiers[0], "strategy": "oa_first"},
            )
        if len(identifiers) > 1:
            return FreeformTaskRoute(
                route="durable_run",
                workflow_type="paper_download_batch",
                presentation_mode="download",
                reason="explicit_batch_download",
                scope="public_academic",
                input_payload={"identifiers": identifiers, "strategy": "oa_first"},
            )
        return FreeformTaskRoute(
            route="durable_run",
            workflow_type="paper_search_download",
            presentation_mode="download",
            reason="explicit_search_and_download",
            scope="public_academic",
            input_payload={"query": request, "limit": 12, "sort": "relevance", "strategy": "oa_first"},
        )

    # A user explicitly asking for their local evidence gets a durable,
    # citable evidence task.  Without an active usable library, keep the
    # request in general chat rather than presenting an artificial gate.
    if has_knowledge and (_EVIDENCE_REVIEW.search(request) or _LOCAL_EVIDENCE.search(request)):
        if _EVIDENCE_REVIEW.search(request) or _LONG_FORM_WRITING.search(request):
            return FreeformTaskRoute(
                route="durable_run",
                workflow_type="literature_review",
                presentation_mode="knowledge",
                reason="explicit_evidence_review",
                scope="selected_knowledge",
                input_payload={
                    "question": request,
                    "writing_brief": {
                        "audience": "researcher",
                        "tone": "academic",
                        "length": "long",
                    },
                },
            )
        return FreeformTaskRoute(
            route="durable_run",
            workflow_type="ask",
            presentation_mode="knowledge",
            reason="explicit_local_evidence",
            scope="selected_knowledge",
            input_payload={"question": request, "task_mode": "evidence"},
        )

    if _DEEP_RESEARCH.search(request):
        return FreeformTaskRoute(
            route="durable_run",
            workflow_type="deep_research",
            presentation_mode="deep-research",
            reason="explicit_deep_research",
            scope="public_academic",
            input_payload={"question": request, "limit": 36, "max_search_rounds": 2, "max_fulltext": 4},
        )

    if _ACADEMIC_SEARCH.search(request):
        return FreeformTaskRoute(
            route="durable_run",
            workflow_type="academic_search",
            presentation_mode="academic",
            reason="explicit_academic_search",
            scope="public_academic",
            input_payload={"query": request, "raw_query": request, "limit": 24, "per_source": 10},
        )

    # A deck is a durable file product only when its local evidence scope is
    # explicit and available.  Otherwise general chat remains free to draft an
    # outline without pretending a project was created.
    if has_knowledge and _PRESENTATION.search(request):
        return FreeformTaskRoute(
            route="durable_run",
            workflow_type="ppt_project",
            presentation_mode="slides",
            reason="explicit_presentation_project",
            scope="selected_knowledge",
            input_payload={"topic": request},
        )

    return FreeformTaskRoute(route="direct_chat", reason="open_conversation")


def _paper_identifiers(text: str) -> list[str]:
    values: list[str] = []
    for match in (*_DOI.finditer(text), *_ARXIV.finditer(text)):
        value = match.group(0).strip().rstrip(".,;:)]}，。；：）】")
        if value.lower().startswith("arxiv"):
            value = value.split(":", 1)[-1].strip()
        if value and value not in values:
            values.append(value)
    return values
