"""Validate that source, tests, scripts and documentation are UTF-8.

The repository contains a few deliberate replacement-character fixtures used
by output-quality guards.  They are allow-listed by their complete source
line; any new replacement character remains a hard failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".toml",
    ".ts",
    ".txt",
    ".yml",
    ".yaml",
}
DEFAULT_PATHS = ("src", "tests", "scripts", "docs", "config", "README.md", "pyproject.toml")
INTENTIONAL_REPLACEMENT_LINES = {
    "literature_review.py": ('marker in value for marker in ("\ufffd"',),
    "research_agent.py": ('if "\ufffd" in text:',),
    "test_literature_review.py": ('1B \ufffd',),
    "compare_paperqa2_scansci_retrieval.py": ('replace("\ufffd", " ")',),
}


def iter_files(root: Path, paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for value in paths:
        candidate = (root / value).resolve()
        if candidate.is_file():
            if candidate.suffix.lower() in TEXT_SUFFIXES:
                files.append(candidate)
            continue
        if not candidate.is_dir():
            continue
        files.extend(
            path
            for path in candidate.rglob("*")
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
        )
    return sorted(set(files))


def check(root: Path, paths: list[str]) -> dict[str, object]:
    invalid: list[dict[str, object]] = []
    replacements: list[dict[str, object]] = []
    files = iter_files(root, paths)
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            invalid.append({"path": relative, "error": str(error)})
            continue
        allowed_fragments = INTENTIONAL_REPLACEMENT_LINES.get(path.name, ())
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "\ufffd" not in line:
                continue
            if not any(fragment in line for fragment in allowed_fragments):
                replacements.append({"path": relative, "line": line_number})
    return {
        "encoding": "utf-8",
        "files_checked": len(files),
        "invalid_utf8": invalid,
        "unexpected_replacement_markers": replacements,
        "passed": not invalid and not replacements,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="relative files or directories; defaults to the source tree")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print a machine-readable report")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    report = check(root, list(args.paths) or list(DEFAULT_PATHS))
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"UTF-8 files checked: {report['files_checked']}")
        print(f"invalid UTF-8: {len(report['invalid_utf8'])}")
        print(f"unexpected replacement markers: {len(report['unexpected_replacement_markers'])}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

