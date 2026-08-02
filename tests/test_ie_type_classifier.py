import json
from pathlib import Path

from scansci_html import cli
from scansci_html.ie_type_classifier import apply_text_type_classifier


def test_apply_text_type_classifier_writes_typed_prediction_rows(tmp_path: Path):
    train_gold = tmp_path / "train.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    output = tmp_path / "typed.jsonl"
    train_gold.write_text(
        "\n".join(
            [
                json.dumps({"entities": [{"text": "citation classification", "type": "Task"}]}),
                json.dumps({"entities": [{"text": "graph neural network", "type": "Process"}]}),
                json.dumps({"entities": [{"text": "polymer material", "type": "Material"}]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    predictions.write_text(
        json.dumps(
            {
                "record_id": "scienceie:S001",
                "entities": [{"text": "citation classification", "type": "Keyphrase"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = apply_text_type_classifier(train_gold, predictions, output_path=output)

    assert summary["train_entities"] == 3
    assert summary["typed_predictions"] == 1
    row = json.loads(output.read_text(encoding="utf-8").strip())
    assert row["entities"][0]["type"] == "Task"
    assert row["entities"][0]["type_classifier"] == "char-logreg"


def test_cli_ie_type_classify_emits_summary(tmp_path: Path, capsys):
    train_gold = tmp_path / "train.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    output = tmp_path / "typed.jsonl"
    train_gold.write_text(
        "\n".join(
            [
                json.dumps({"entities": [{"text": "citation classification", "type": "Task"}]}),
                json.dumps({"entities": [{"text": "graph neural network", "type": "Process"}]}),
                json.dumps({"entities": [{"text": "polymer material", "type": "Material"}]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    predictions.write_text(json.dumps({"entities": [{"text": "polymer material"}]}) + "\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "ie-type-classify",
            "--train-gold",
            str(train_gold),
            "--predictions",
            str(predictions),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["typed_predictions"] == 1
    assert output.exists()
