from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


AccessStatus = Literal["fulltext", "no_access", "unknown"]
SaveStatus = Literal["success", "auth_required", "no_access", "fetch_error"]


@dataclass(frozen=True)
class FetchResponse:
    url: str
    final_url: str
    html: str
    status_code: int | None = None
    source: str = "http"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedIdentifier:
    original: str
    url: str
    doi: str | None = None


@dataclass(frozen=True)
class CleanHtmlDocument:
    title: str
    html: str
    text_length: int
    has_fulltext: bool
    access_status: AccessStatus
    source_url: str
    doi: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SaveResult:
    identifier: str
    status: SaveStatus
    output_path: Path | None = None
    snapshot_path: Path | None = None
    title: str = ""
    doi: str | None = None
    source_url: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    structure: dict[str, object] = field(default_factory=dict)
