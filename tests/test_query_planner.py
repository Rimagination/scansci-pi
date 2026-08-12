from scansci_html.qa.query_planner import plan_query


def test_method_source_policy_does_not_turn_evidence_question_into_methods_only_search():
    question = (
        "在光伏生态文献中总结生态影响；只有论文明确讨论方法时才引用方法。"
    )

    assert plan_query(question)["filters"] == {}


def test_explicit_method_comparison_still_searches_methods():
    question = "比较不同研究方法的优缺点"

    assert plan_query(question)["filters"] == {"section_kinds": ["methods"]}
