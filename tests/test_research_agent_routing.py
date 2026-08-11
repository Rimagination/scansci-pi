from scansci_html.research_agent import ResearchAgentRuntime


def test_selected_library_routes_evidence_request_to_local_knowledge() -> None:
    mode = ResearchAgentRuntime._direct_pi_task_mode(
        "general",
        "off",
        messages=[
            {
                "role": "user",
                "content": "基于当前选择的光伏生态文献，找出光伏电站与植物多样性的一条可靠证据。",
            }
        ],
        selected_knowledge=True,
    )

    assert "knowledge" in mode.split("+")
    assert "web" not in mode.split("+")


def test_selected_library_does_not_change_plain_greeting_route() -> None:
    mode = ResearchAgentRuntime._direct_pi_task_mode(
        "general",
        "off",
        messages=[{"role": "user", "content": "你好"}],
        selected_knowledge=True,
    )

    assert mode == "general"
