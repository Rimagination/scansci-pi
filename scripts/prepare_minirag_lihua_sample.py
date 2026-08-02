from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a small LiHua-World subset for official MiniRAG reproduction.")
    parser.add_argument("--official-root", default="external/minirag-official", help="Path to the cloned MiniRAG repo.")
    parser.add_argument("--questions", type=int, default=5, help="Number of QA rows to keep.")
    parser.add_argument("--distractors", type=int, default=10, help="Extra non-evidence txt files to copy.")
    parser.add_argument("--output-name", default="scansci-lihua-small", help="Output folder name under the MiniRAG repo.")
    args = parser.parse_args()

    root = Path(args.official_root)
    source_data = root / "dataset" / "LiHua-World" / "data" / "LiHua-World"
    source_queries = root / "dataset" / "LiHua-World" / "qa" / "query_set.csv"
    output_root = root / args.output_name
    output_data = output_root / "data"
    output_qa = output_root / "qa"

    rows = _read_rows(source_queries)[: max(args.questions, 0)]
    all_txt = sorted(source_data.rglob("*.txt"))
    by_stem = {path.stem: path for path in all_txt}

    required_stems: list[str] = []
    for row in rows:
        for evidence in _evidence_stems(row.get("Evidence", "")):
            if evidence not in required_stems:
                required_stems.append(evidence)

    selected: list[Path] = []
    missing: list[str] = []
    for stem in required_stems:
        path = by_stem.get(stem)
        if path is None:
            missing.append(stem)
            continue
        selected.append(path)

    selected_set = {path.resolve() for path in selected}
    for path in all_txt:
        if len(selected) >= len(selected_set) + max(args.distractors, 0):
            break
        if path.resolve() not in selected_set:
            selected.append(path)

    if output_root.exists():
        shutil.rmtree(output_root)
    output_data.mkdir(parents=True, exist_ok=True)
    output_qa.mkdir(parents=True, exist_ok=True)

    for path in selected:
        relative = path.relative_to(source_data)
        target = output_data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    _write_csv(output_qa / "query_set.csv", rows)
    (output_qa / "query_set.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "source_data": str(source_data),
        "source_queries": str(source_queries),
        "questions": len(rows),
        "evidence_documents_requested": len(required_stems),
        "evidence_documents_found": len(selected_set),
        "missing_evidence_stems": missing,
        "total_txt_copied": len(selected),
        "data_path": str(output_data),
        "query_path": str(output_qa / "query_set.csv"),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0]) if rows else ["Question", "Gold Answer", "Evidence", "Type"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _evidence_stems(raw_value: str) -> list[str]:
    stems: list[str] = []
    for part in str(raw_value or "").split("<and>"):
        cleaned = part.strip().replace(":", "").replace("-", "").replace(" ", "_")
        if cleaned:
            stems.append(cleaned)
    return stems


if __name__ == "__main__":
    raise SystemExit(main())
