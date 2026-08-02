from __future__ import annotations

from scansci_html.agent_contract import classify_task_profile, compile_task_contract


def test_plain_conversation_gets_no_tool_authority() -> None:
    contract = compile_task_contract(
        task_mode="general",
        user_text="解释一下什么是置信区间",
    )

    assert contract["autonomy"] == "direct"
    assert contract["risk_level"] == "none"
    assert contract["allowed_tools"] == []
    assert contract["requires_plan"] is False
    assert contract["task_profile"]["route"] == "direct_chat"
    assert contract["task_profile"]["execution_complexity"] == "none"


def test_research_download_is_reversible_and_progress_budgeted() -> None:
    contract = compile_task_contract(
        task_mode="research",
        user_text="下载这三篇论文，建立全文索引，然后比较研究方法",
        required_tool_groups=[
            {"download_and_index"},
            {"summarize_documents"},
            {"check_task_completion"},
        ],
    )

    assert contract["autonomy"] == "reversible"
    assert contract["risk_level"] == "reversible"
    assert contract["requires_plan"] is False
    assert "download_and_index" in contract["allowed_tools"]
    assert contract["initial_tool_budget"] == 6
    assert contract["max_tool_budget"] == 12
    assert contract["model_token_budget"] == 48_000
    assert contract["required_tool_groups"] == [
        ["download_and_index"],
        ["summarize_documents"],
        ["check_task_completion"],
    ]


def test_external_or_destructive_request_requires_plan() -> None:
    contract = compile_task_contract(
        task_mode="general",
        user_text="把结果公开发布到网站并覆盖现有数据库",
    )

    assert contract["autonomy"] == "approval_required"
    assert contract["risk_level"] == "high"
    assert contract["requires_plan"] is True
    assert contract["allow_external_write"] is True


def test_large_reversible_batch_requires_plan_without_becoming_high_risk() -> None:
    contract = compile_task_contract(
        task_mode="research",
        user_text="下载并索引 50 篇论文",
    )

    assert contract["risk_level"] == "reversible"
    assert contract["requires_plan"] is True
    assert contract["allow_external_write"] is False


def test_plain_knowledge_chat_does_not_receive_research_run_tools() -> None:
    contract = compile_task_contract(
        task_mode="knowledge",
        user_text="只使用选中的知识库比较两篇论文",
    )

    assert "search_local_evidence" in contract["allowed_tools"]
    assert "build_verified_answer" in contract["allowed_tools"]
    assert "summarize_documents" not in contract["allowed_tools"]
    assert "check_task_completion" not in contract["allowed_tools"]


def test_auto_web_toggle_does_not_grant_tools_to_an_ordinary_turn() -> None:
    contract = compile_task_contract(
        task_mode="web-auto",
        user_text="解释一下什么是向量",
    )

    assert contract["task_profile"]["route"] == "direct_chat"
    assert contract["autonomy"] == "direct"
    assert contract["allowed_tools"] == []


def test_explicit_current_search_is_a_bounded_tool_turn() -> None:
    profile = classify_task_profile(
        task_mode="web-auto",
        user_text="联网检索今天的科技新闻",
        required_tool_groups=[{"search_web", "discover_papers"}],
    )

    assert profile.route == "tool_agent"
    assert profile.execution_complexity == "tool"
    assert profile.evidence_policy == "assist"
    assert profile.requires_tools is True


def test_multi_stage_research_is_a_resumable_workflow() -> None:
    profile = classify_task_profile(
        task_mode="research",
        user_text="下载三篇论文，建立全文索引，然后比较研究方法",
        required_tool_groups=[
            {"download_and_index"},
            {"summarize_documents"},
            {"check_task_completion"},
        ],
    )

    assert profile.route == "resumable_workflow"
    assert profile.cognitive_complexity == "high"
    assert profile.execution_complexity == "workflow"
    assert profile.risk_level == "reversible"


def test_social_follow_up_never_inherits_a_knowledge_tool_lease() -> None:
    contract = compile_task_contract(
        task_mode="knowledge",
        user_text="谢谢",
    )

    assert contract["task_profile"]["route"] == "direct_chat"
    assert contract["task_profile"]["evidence_policy"] == "off"
    assert contract["allowed_tools"] == []


def test_catalog_availability_can_only_reduce_a_task_lease() -> None:
    contract = compile_task_contract(
        task_mode="research",
        user_text="Search and verify papers",
        available_tool_ids=["search_web", "discover_papers"],
        allowed_mcp_servers=["papers"],
        capability_lease={"schema_version": "scansci.capability-lease.v1"},
    )

    assert contract["allowed_tools"] == ["discover_papers", "search_web"]
    assert "build_verified_answer" in contract["unavailable_tools"]
    assert contract["allowed_mcp_servers"] == ["papers"]
    assert contract["capability_lease"]["schema_version"] == "scansci.capability-lease.v1"
