import json
from pathlib import Path

from scansci_html import cli
from scansci_html.ie_model_candidates import extract_ie_model_candidates_from_jsonl


def test_extract_ie_model_candidates_from_jsonl_writes_ie_bench_compatible_rows(tmp_path: Path):
    input_path = tmp_path / "gold.jsonl"
    output_path = tmp_path / "predictions.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "record_id": "scienceie:S001",
                "source_text": "Graph neural networks improve citation classification.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = extract_ie_model_candidates_from_jsonl(
        input_path,
        output_path=output_path,
        pipeline_factory=_fake_pipeline_factory,
        model_name="fake-keyphrase-model",
        batch_size=2,
    )

    assert summary["source_rows"] == 1
    assert summary["predicted_entities"] == 2
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "record_id": "scienceie:S001",
            "source": "transformers-token-classification",
            "model_name": "fake-keyphrase-model",
            "entities": [
                {
                    "text": "Graph neural networks",
                    "type": "Keyphrase",
                    "model_label": "KEY",
                    "score": 0.91,
                    "start_char": 0,
                    "end_char": 21,
                },
                {
                    "text": "citation classification",
                    "type": "Keyphrase",
                    "model_label": "KEY",
                    "score": 0.88,
                    "start_char": 30,
                    "end_char": 53,
                },
            ],
        }
    ]


def test_cli_ie_model_candidates_emits_summary(tmp_path: Path, monkeypatch, capsys):
    input_path = tmp_path / "gold.jsonl"
    output_path = tmp_path / "predictions.jsonl"
    input_path.write_text(json.dumps({"record_id": "r1", "source_text": "text"}) + "\n", encoding="utf-8")

    def fake_extract(input_path, **kwargs):
        Path(kwargs["output_path"]).write_text(json.dumps({"entities": []}) + "\n", encoding="utf-8")
        return {"input_path": str(input_path), "output_path": str(kwargs["output_path"]), "predicted_entities": 0}

    monkeypatch.setattr(cli, "extract_ie_model_candidates_from_jsonl", fake_extract)

    exit_code = cli.main(
        [
            "ie-model-candidates",
            "--input-jsonl",
            str(input_path),
            "--output",
            str(output_path),
            "--model",
            "fake-keyphrase-model",
            "--cache-dir",
            str(tmp_path / "hf-cache"),
            "--max-rows",
            "1",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["predicted_entities"] == 0
    assert output_path.exists()


def _fake_pipeline_factory(**kwargs):
    assert kwargs["task"] == "token-classification"
    assert kwargs["model"] == "fake-keyphrase-model"
    return _FakeTokenClassifier()


class _FakeTokenClassifier:
    def __call__(self, texts, **kwargs):
        assert kwargs["batch_size"] == 2
        outputs = []
        for text in texts:
            if "Graph neural networks" in text:
                outputs.append(
                    [
                        {"word": "Graph neural networks", "entity_group": "KEY", "score": 0.91, "start": 0, "end": 21},
                        {"word": "citation classification", "entity_group": "KEY", "score": 0.88, "start": 30, "end": 53},
                    ]
                )
            else:
                outputs.append([])
        return outputs
