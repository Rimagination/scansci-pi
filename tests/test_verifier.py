import json
from pathlib import Path

from scansci_html import cli
from scansci_html.qa.verifier import (
    apply_verification_policy,
    verify_answer_claims,
    verify_answer_claims_with_llm,
)


def test_verify_answer_claims_marks_supported_unsupported_and_contradicted():
    answer = {
        "question": "question",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "Treatment increased biomass.",
                "quote_ids": ["q0001"],
            },
            {
                "claim_id": "c0002",
                "text": "Treatment improved survival.",
                "quote_ids": ["q0001"],
            },
            {
                "claim_id": "c0003",
                "text": "Treatment increased biomass.",
                "quote_ids": ["q0002"],
            },
        ],
        "limitations": [],
        "insufficient_evidence": False,
    }
    evidence_table = [
        {
            "quote_id": "q0001",
            "exact_quote": "Treatment increased biomass by 18%.",
        },
        {
            "quote_id": "q0002",
            "exact_quote": "Treatment did not increase biomass in the validation cohort.",
        },
    ]

    verified = verify_answer_claims(answer, evidence_table)

    assert [(claim["claim_id"], claim["support_status"], claim["verification_score"]) for claim in verified["answer"]] == [
        ("c0001", "supported", 1.0),
        ("c0002", "unsupported", 0.33),
        ("c0003", "contradicted", 0.0),
    ]
    assert verified["verification"]["unsupported_claims"] == ["c0002"]
    assert verified["verification"]["contradicted_claims"] == ["c0003"]


def test_verify_answer_claims_supports_chinese_claims_against_chinese_quotes():
    answer = {
        "answer": [
            {
                "claim_id": "c0001",
                "text": "光伏组件遮挡减少地表太阳辐射，并改变局地能量分配。",
                "quote_ids": ["q0001"],
            }
        ]
    }
    evidence_table = [
        {
            "quote_id": "q0001",
            "exact_quote": "光伏组件的遮挡使场区内地表接收到的太阳辐射减少，并改变了局地能量分配。",
        }
    ]

    verified = verify_answer_claims(answer, evidence_table)

    assert verified["answer"][0]["support_status"] in {"supported", "partially_supported"}
    assert verified["answer"][0]["verification_score"] >= 0.5


def test_verify_answer_claims_marks_missing_quote_as_not_enough_information():
    answer = {
        "question": "question",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "Treatment increased biomass.",
                "quote_ids": ["missing"],
            }
        ],
        "limitations": [],
        "insufficient_evidence": False,
    }

    verified = verify_answer_claims(answer, [])

    assert verified["answer"][0]["support_status"] == "not_enough_information"
    assert verified["verification"]["not_enough_information_claims"] == ["c0001"]


def test_verify_answer_claims_supports_acknowledged_conflict_claim():
    answer = {
        "question": "question",
        "answer": [
            {
                "claim_id": "c0001",
                "text": (
                    "One source reports that Treatment increased biomass by 18 percent in the greenhouse cohort; "
                    "another source reports that Treatment did not increase biomass in the validation cohort."
                ),
                "quote_ids": ["q0001", "q0002"],
            }
        ],
        "limitations": [],
        "insufficient_evidence": False,
    }
    evidence_table = [
        {
            "quote_id": "q0001",
            "exact_quote": "Treatment increased biomass by 18 percent in the greenhouse cohort.",
        },
        {
            "quote_id": "q0002",
            "exact_quote": "Treatment did not increase biomass in the validation cohort.",
        },
    ]

    verified = verify_answer_claims(answer, evidence_table)

    assert verified["answer"][0]["support_status"] == "partially_supported"
    assert verified["verification"]["partially_supported_claims"] == ["c0001"]
    assert verified["verification"]["contradicted_claims"] == []


def test_apply_verification_policy_abstains_when_no_claim_is_supported():
    verified = {
        "question": "question",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "Unsupported claim.",
                "quote_ids": ["q0001"],
                "support_status": "unsupported",
            }
        ],
        "limitations": [],
        "insufficient_evidence": False,
    }

    result = apply_verification_policy(verified)

    assert result["insufficient_evidence"] is True
    assert result["verification_policy"] == {
        "action": "abstain",
        "reason": "no supported or partially supported claims",
    }
    assert "No supported or partially supported claims remained after verification." in result["limitations"]


def test_verify_answer_claims_with_llm_updates_claim_statuses_and_summary():
    captured = {}

    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            captured["messages"] = messages
            return {
                "claims": [
                    {
                        "claim_id": "c0001",
                        "support_status": "supported",
                        "verification_score": 0.95,
                    },
                    {
                        "claim_id": "c0002",
                        "support_status": "unsupported",
                        "verification_score": 0.2,
                    },
                ]
            }

    answer = {
        "question": "question",
        "answer": [
            {"claim_id": "c0001", "text": "Supported claim.", "quote_ids": ["q0001"]},
            {"claim_id": "c0002", "text": "Unsupported claim.", "quote_ids": ["q0001"]},
        ],
        "limitations": [],
        "insufficient_evidence": False,
    }
    evidence_table = [{"quote_id": "q0001", "exact_quote": "Supported claim."}]

    verified = verify_answer_claims_with_llm(answer, evidence_table, chat_client=FakeChatClient())

    assert [(claim["claim_id"], claim["support_status"], claim["verification_score"]) for claim in verified["answer"]] == [
        ("c0001", "supported", 0.95),
        ("c0002", "unsupported", 0.2),
    ]
    assert verified["verification"]["supported_claims"] == ["c0001"]
    assert verified["verification"]["unsupported_claims"] == ["c0002"]
    request_body = json.loads(captured["messages"][1]["content"])
    assert request_body["answer"] == {
        "claims": [
            {"claim_id": "c0001", "text": "Supported claim.", "quote_ids": ["q0001"]},
            {"claim_id": "c0002", "text": "Unsupported claim.", "quote_ids": ["q0001"]},
        ]
    }
    assert request_body["evidence_table"] == [
        {"quote_id": "q0001", "exact_quote": "Supported claim.", "paper": "", "section": ""}
    ]
    assert "different languages" in captured["messages"][0]["content"]


def test_llm_verification_cannot_support_a_model_name_missing_from_its_quote():
    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            return {
                "claims": [
                    {"claim_id": "c0001", "support_status": "supported", "verification_score": 0.99}
                ]
            }

    answer = {
        "answer": [
            {
                "claim_id": "c0001",
                "text": "GPT-3 使用零样本学习。",
                "quote_ids": ["q0001"],
            }
        ]
    }
    evidence = [{"quote_id": "q0001", "exact_quote": "OpenAI GPT uses a left-to-right Transformer LM."}]

    verified = verify_answer_claims_with_llm(answer, evidence, chat_client=FakeChatClient())

    assert verified["answer"][0]["support_status"] == "unsupported"
    assert verified["answer"][0]["verification_score"] == 0.0


def test_cli_verify_writes_verified_report_json(tmp_path: Path, capsys):
    report = {
        "question": "question",
        "answer": {
            "question": "question",
            "answer": [
                {
                    "claim_id": "c0001",
                    "text": "Treatment increased biomass.",
                    "quote_ids": ["q0001"],
                }
            ],
            "limitations": [],
            "insufficient_evidence": False,
        },
        "quotes": [],
        "evidence_table": [
            {
                "quote_id": "q0001",
                "exact_quote": "Treatment increased biomass by 18%.",
            }
        ],
    }
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "verified.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    exit_code = cli.main(["verify", "--report", str(report_path), "--output", str(output_path)])

    payload = json.loads(capsys.readouterr().out)
    verified = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload == {
        "claims": 1,
        "supported": 1,
        "partially_supported": 0,
        "contradicted": 0,
        "unsupported": 0,
        "not_enough_information": 0,
        "output_path": str(output_path),
    }
    assert verified["answer"]["answer"][0]["support_status"] == "supported"


def test_cli_verify_can_use_llm_verification_provider(tmp_path: Path, monkeypatch, capsys):
    report = {
        "question": "question",
        "answer": {
            "question": "question",
            "answer": [
                {
                    "claim_id": "c9000",
                    "text": "Treatment increased biomass.",
                    "quote_ids": ["q9000"],
                }
            ],
            "limitations": [],
            "insufficient_evidence": False,
        },
        "quotes": [],
        "evidence_table": [
            {
                "quote_id": "q9000",
                "exact_quote": "Treatment increased biomass by 18%.",
            }
        ],
    }
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "verified.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    calls: list[str] = []

    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            calls.append(schema_name)
            return {
                "claims": [
                    {
                        "claim_id": "c9000",
                        "support_status": "supported",
                        "verification_score": 0.94,
                    }
                ]
            }

    monkeypatch.setattr(cli, "build_chat_json_client", lambda *args, **kwargs: FakeChatClient())

    exit_code = cli.main(
        [
            "verify",
            "--report",
            str(report_path),
            "--output",
            str(output_path),
            "--verification-provider",
            "llm",
            "--chat-provider",
            "openai-compatible",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    verified = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert calls == ["claim_verification"]
    assert payload["supported"] == 1
    assert verified["answer"]["answer"][0]["verification_score"] == 0.94
