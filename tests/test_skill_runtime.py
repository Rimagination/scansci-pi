from scansci_html.agent_context import selected_skill_ids
from scansci_html.skill_runtime import infer_research_skill, resolve_skill_selection


def test_runtime_infers_one_most_specific_research_skill() -> None:
    messages = [{"role": "user", "content": "请逐条回复审稿人的意见，并标出每项修改"}]

    selection = resolve_skill_selection({}, messages)

    assert selection.selected_ids == ("nature-response",)
    assert selection.inferred_ids == ("nature-response",)
    assert selection.explicit_ids == ()
    assert selected_skill_ids({}, messages) == ["nature-response"]


def test_explicit_selection_wins_and_concrete_skill_suppresses_suite() -> None:
    payload = {"skills": ["academic-research-suite", "nature-writing"]}
    messages = [{"role": "user", "content": "$nature-statistics 请检查结果段"}]

    selection = resolve_skill_selection(payload, messages)

    assert selection.selected_ids == ("nature-writing", "nature-statistics")
    assert selection.explicit_ids == ("nature-writing", "nature-statistics")
    assert selection.inferred_ids == ()
    assert selection.suppressed_ids == ("academic-research-suite",)


def test_existing_scan_sci_phase_skill_also_suppresses_the_suite_router() -> None:
    selection = resolve_skill_selection(
        {"skills": ["academic-research-suite", "good-question"]},
        [{"role": "user", "content": "帮我收束研究问题"}],
    )

    assert selection.selected_ids == ("good-question",)
    assert selection.suppressed_ids == ("academic-research-suite",)


def test_explicit_skill_prevents_a_second_automatic_contract() -> None:
    selection = resolve_skill_selection(
        {"skills": ["nature-writing"]},
        [{"role": "user", "content": "请润色这段论文讨论"}],
    )

    assert selection.selected_ids == ("nature-writing",)
    assert "nature-polishing" not in selection.selected_ids


def test_automatic_selection_can_be_disabled_per_request() -> None:
    selection = resolve_skill_selection(
        {"auto_select_skills": False},
        [{"role": "user", "content": "请润色这段英文摘要"}],
    )

    assert selection.selected_ids == ()


def test_inference_covers_research_pipeline_entrypoints() -> None:
    assert infer_research_skill("帮我检索近五年的土壤微生物论文") == "nature-academic-search"
    assert infer_research_skill("请写一篇关于城市热岛的文献综述") == "literature-review"
    assert infer_research_skill("从选题到投稿，帮我规划科研全流程") == "academic-research-suite"
