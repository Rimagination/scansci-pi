from scansci_html.research_agent import ResearchAgentRuntime


def test_verified_fallback_prefers_chinese_sources_for_chinese_requests() -> None:
    citations = [
        {
            "citation_id": "1",
            "paper": "中文光伏生态研究",
            "exact_quote": "光伏板下植物群落的物种丰富度发生变化。",
        },
        {
            "citation_id": "2",
            "paper": "Solar farm ecology",
            "exact_quote": "Solar farms alter vegetation and soil conditions.",
        },
    ]

    answer = ResearchAgentRuntime._verified_evidence_fallback(
        citations,
        "请用中文回答光伏电站对植物多样性的影响。",
    )

    assert "中文光伏生态研究" in answer
    assert "Solar farm ecology" not in answer


def test_verified_fallback_keeps_english_when_no_chinese_source_exists() -> None:
    citations = [
        {
            "citation_id": "1",
            "paper": "Solar farm ecology",
            "exact_quote": "Solar farms alter vegetation and soil conditions.",
        },
    ]

    answer = ResearchAgentRuntime._verified_evidence_fallback(
        citations,
        "请用中文回答光伏电站对植物多样性的影响。",
    )

    assert "Solar farm ecology" in answer
