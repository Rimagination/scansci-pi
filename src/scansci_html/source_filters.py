"""Shared filters for source folders selected as ScanSci knowledge libraries.

The importers intentionally index files in place.  A linked research folder can
also contain a software project, however, and dependency trees such as
``node_modules`` must never become research documents just because they contain
HTML or Markdown files.
"""

from __future__ import annotations

from pathlib import Path


# Keep this list deliberately narrow.  These names are dependency, virtual
# environment, cache, or version-control directories rather than legitimate
# research source folders.  More general content choices remain the user's.
IGNORED_LIBRARY_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)


def is_ignored_library_path(path: Path, library_root: Path) -> bool:
    """Return whether ``path`` is below a known non-source directory.

    The filename itself is deliberately not considered: a researcher may name
    a real document after any of these words.  Only parent directories are
    filtered, which keeps the policy predictable and reversible.
    """

    try:
        relative_parts = path.relative_to(library_root).parts
    except ValueError:
        relative_parts = path.parts
    directory_parts = relative_parts[:-1] if relative_parts else ()
    return any(part.casefold() in IGNORED_LIBRARY_DIRECTORY_NAMES for part in directory_parts)
