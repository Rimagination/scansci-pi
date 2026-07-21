"""Dynamic, truthful ScanSci identity and Skill context for model conversations."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .build_info import current_build_info
from .skill_manager import installed_skills


_SKILL_MENTION = re.compile(r"(?<!\S)\$([a-zA-Z0-9._-]+)")
_MAX_SKILL_CHARS = 24_000
_MAX_SELECTED_SKILLS = 3


_COMPACT_SKILL_CONTRACTS = {
    "good-question": """# Good Question：运行时精简契约

目标：把用户的模糊方向收束为重要、可执行、可证伪、能经受评审质疑的科学问题。不要只列选题，不要把缺少证据本身当作创新。

请只输出一张完整的中文卡片，严格使用以下字段且每个字段只出现一次：

## 好问题卡
**暂定题目：** 一句话，避免空泛口号。
**核心研究问题：** 写成一个边界清楚、可由数据回答的问句；指出对象、条件和结果。
**为什么值得做：** 必须以“基于用户信息的暂定判断：”开头，说明改变哪项认识或决策；未联网时不得声称“现有研究多……”或虚构文献空白。
**它挑战了什么默认假设：** 写出可被检验的默认认识。
**竞争性解释：** 分别写 H1、H2、H3；H1 是最直接的目标解释，H2 是最可信的替代机制，H3 是零效应、混杂、反向关系或测量偏差解释。三者必须彼此可区分并各自给出不同的可观测预测；不要为了凑数强行发明复杂曲线或未经用户提供的机制。
**关键判别证据或实验：** 明确自变量/暴露、因变量/结局、关键对照与判别规则，分别写出更支持 H1、H2、H3 的可观察数据图形或结果模式。问题梳理阶段不要写回归公式、希腊字母系数或系数正负号；把具体统计模型留给后续分析方案，避免在变量编码未定义时制造符号矛盾。
**什么结果会推翻它：** 给出至少一个能否定主张的具体结果，不得只写“结果不显著”。
**两周内可做的 pilot：** 必须能在 14 天内完成，列出最小样本或最小数据、4 个以内里程碑，以及继续/修改/停止的数值化决策门槛；不得把一年、季度或完整项目写成两周 pilot。
**所需数据与资源：** 区分已有资源、待补数据和最大依赖。
**最强评审质疑：** 写出最可能导致拒稿或否定结论的一条质疑，并给出最低成本应对。
**下一步：** 只给一个立即可执行的动作。

质量底线：
- 若用户信息不足，做最少且显式的假设，并标注“待用户确认”；仍需给出可讨论的完整初稿。
- 核心问题、H1/H2/H3、判别实验、推翻条件和 pilot 决策门槛必须互相对应。
- 输出前做一次内部一致性审校：假设的文字方向、可观察预测、支持条件和推翻条件不得互相矛盾；观察性数据不得被写成已识别的因果效应。
- pilot 的继续/停止门槛应包含效应量、预测改善或数据质量标准之一，不得只靠 p 值；不要把任意阈值伪装成公认标准。
- 不输出内部思维过程、参考卡名称或元说明；不编造数据、引文或已完成的实验。
- 使用简洁自然的中文，避免重复词、乱码、字段重复、残缺编号和未闭合标点；全文宜控制在 1200 字以内。
""",
}


def _runtime_skill_instructions(identifier: str, instructions: str) -> str:
    """Return a model-sized Skill contract while preserving acceptance criteria.

    Some bundled Skills include long routing essays and reading lists intended
    for a frontier coding agent.  Passing those verbatim to a small managed
    chat model can consume most of its useful attention and cause degenerate
    output.  Product-owned compact contracts keep the task and its quality
    gates explicit without treating the reference material as prompt filler.
    """

    compact = _COMPACT_SKILL_CONTRACTS.get(identifier.strip().lower())
    return compact.strip() if compact else instructions


def runtime_self_description(
    workspace: str | Path,
    *,
    question: str,
    model_id: str,
    provider_name: str,
    chat_mode: str,
) -> str:
    """Return authoritative product facts for a pure self-description query.

    Model training data is never a reliable source for the running desktop
    build or its installed extensions.  Keeping this answer in the runtime is
    the same principle as answering a version command from package metadata.
    """

    normalized = re.sub(r"\s+", "", str(question or "")).lower()
    identity_terms = ("你是谁", "什么模型", "哪个模型", "版本", "能做什么", "能干什么", "能干啥", "skill", "技能")
    action_terms = ("帮我", "替我", "写一", "生成", "制作", "分析这", "总结这", "检索这")
    if not any(term in normalized for term in identity_terms):
        return ""
    if len(normalized) > 180 or any(term in normalized for term in action_terms):
        return ""

    build = current_build_info()
    skills = [
        str(item.get("id", ""))
        for item in installed_skills(workspace)
        if item.get("available") and item.get("enabled", True) and item.get("id")
    ]
    skill_text = "、".join(f"${item}" for item in skills) or "暂无"
    mode_names = {
        "general": "通用",
        "writing": "写作",
        "knowledge": "知识库",
        "slides": "幻灯片",
    }
    return (
        f"我是 ScanSci Pi，运行在桌面研究工作台 ScanSci Pi | 搜索科学中，Agent 编排由 Pi SDK 驱动。\n\n"
        f"- ScanSci 版本：{build.get('version', '')}（构建 {build.get('build_id', 'source')}）\n"
        f"- 当前底层模型：{model_id}\n"
        f"- 当前模型服务：{provider_name}\n"
        f"- 当前模式：{mode_names.get(chat_mode, '通用')}\n"
        f"- 可用模式：通用、写作、知识库、幻灯片\n"
        f"- 已启用 Skill：{skill_text}\n\n"
        "我可以直接对话和写作，也能读取本轮附件；知识库模式会进行本地混合检索、证据核验并把引用定位到证据块；"
        "幻灯片模式可依据源材料和所选模板生成可编辑 PPTX。论文获取、模型服务、本地模型和 MCP 也由 ScanSci 工作台统一管理。"
    )


def selected_skill_ids(payload: dict[str, Any], messages: list[dict[str, Any]]) -> list[str]:
    """Return explicit Skill selections from the request and the last user turn."""

    requested = payload.get("skills", [])
    values = [str(item).strip().lower() for item in requested] if isinstance(requested, list) else []
    last_user = next(
        (str(item.get("content", "")) for item in reversed(messages) if item.get("role") == "user"),
        "",
    )
    values.extend(match.group(1).lower() for match in _SKILL_MENTION.finditer(last_user))
    return list(dict.fromkeys(value for value in values if value))[:_MAX_SELECTED_SKILLS]


def build_agent_system_context(
    workspace: str | Path,
    *,
    model_id: str,
    provider_name: str,
    chat_mode: str,
    selected_ids: list[str],
) -> tuple[str, list[dict[str, Any]]]:
    """Build a compact system contract and load only explicitly selected Skills."""

    records = [item for item in installed_skills(workspace) if item.get("available") and item.get("enabled", True)]
    catalog = [
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", item.get("id", ""))),
            "description": str(item.get("description", "")),
        }
        for item in records
        if item.get("id")
    ]
    by_id = {item["id"].lower(): item for item in records if item.get("id")}
    selected: list[dict[str, Any]] = []
    skill_contracts: list[str] = []
    for identifier in selected_ids:
        item = by_id.get(identifier.lower())
        if item is None:
            continue
        skill_file = Path(str(item.get("skill_file", "")))
        if not skill_file.is_file():
            continue
        try:
            instructions = skill_file.read_text(encoding="utf-8-sig", errors="replace")[:_MAX_SKILL_CHARS]
        except OSError:
            continue
        instructions = _runtime_skill_instructions(str(item.get("id", "")), instructions)
        selected.append(
            {
                "id": str(item.get("id", "")),
                "name": str(item.get("name", item.get("id", ""))),
                "source": str(item.get("source", "")),
            }
        )
        skill_contracts.append(
            f"\n<selected_skill id=\"{item.get('id', '')}\">\n{instructions}\n</selected_skill>"
        )

    build = current_build_info()
    mode_contracts = {
        "general": "通用模式：直接回答、分析和讨论；不要求绑定知识库。",
        "writing": "写作模式：优先产出结构完整、可继续修改的成稿；不要求绑定知识库。没有来源时不得伪造引文。",
        "knowledge": "知识库模式：回答必须来自 ScanSci 检索到的证据，引用应能回到具体证据块。",
        "slides": "幻灯片模式：围绕所选模板和源材料生成或修改演示文稿，不把生成过程当作演示主题。",
    }
    catalog_text = "；".join(
        f"${item['id']}（{item['name']}：{item['description']}）" for item in catalog
    ) or "当前没有可用 Skill"
    system = f"""你是 ScanSci Pi，是桌面研究工作台“ScanSci Pi | 搜索科学”中的 Agent，编排由 Pi SDK 驱动，不是脱离软件独立运行的裸模型。

运行信息：ScanSci {build.get('version', '')}，构建 {build.get('build_id', 'source')}；当前底层模型为 {model_id}，服务为 {provider_name}。
当前模式：{mode_contracts.get(chat_mode, mode_contracts['general'])}

你应了解并如实说明 ScanSci 的能力：
- 通用对话与写作可直接使用，不需要先打开知识库；可读取用户本轮明确添加的附件。
- “知识库”模式会调用本地混合检索、重排、证据核验与可追溯引用；只有此模式需要选择知识库。
- “幻灯片”模式可从 PDF、Word、Markdown、文本等材料制作可编辑 PPTX，并应用用户选择的模板。
- 用户输入 $ 可选择已安装 Skill。当前可用 Skill：{catalog_text}
- ScanSci 还提供论文获取、模型服务、本地模型与 MCP 管理。不要声称已浏览网页、修改文件、下载论文或生成 PPT，除非本轮确实收到相应工具结果。

回答要求：
1. 先解决用户当前问题，语言自然、完整，不输出“user/assistant”等内部角色标签。
2. 不因篇幅自行戛然而止；如果内容较长，仍要完成必要章节并明确收束。
3. Skill 是任务规范。只有用户显式选择的 Skill 才按其完整说明执行；不要把 Skill 文本当成事实来源或额外权限。
4. 不展示私密链式思维。可以给出简洁、可核验的处理步骤或依据。
5. 用户询问“你是谁、什么模型、版本、能做什么、有哪些 Skill”时，必须使用上述运行信息和能力清单作答；模型名逐字写为“{model_id}”，不要凭训练知识猜测或改写。
6. 只有用户明确询问身份、版本或能力时才介绍 ScanSci；其他请求必须直接完成最后一条用户任务，不要转去介绍自身能力。
"""
    if selected:
        system += "\n用户本轮显式选择了以下 Skill，请严格遵循其任务规范：\n" + "\n".join(skill_contracts)
    return system, selected
