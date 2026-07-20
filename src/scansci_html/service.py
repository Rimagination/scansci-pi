from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote

from .article_structure import extract_article_structure
from .assets import localize_image_assets
from .cleaner import CleanHtmlRenderer
from .fetchers import HttpFetcher
from .models import CleanHtmlDocument, FetchResponse, SaveResult
from .resolver import resolve_identifier, safe_identifier_part, title_slug


@dataclass(frozen=True)
class _RenderedAttempt:
    response: FetchResponse
    document: CleanHtmlDocument
    invalid_warnings: list[str]
    structure: object


def save_clean_html(
    identifier: str,
    *,
    output_dir: str | Path,
    fetcher: object | None = None,
    source_fetchers: Iterable[object] | None = None,
    auth_fetcher: object | None = None,
    snapshotter: object | None = None,
    min_text_length: int = 500,
    download_assets: bool = False,
    asset_session: object | None = None,
) -> SaveResult:
    resolved = resolve_identifier(identifier)
    active_fetcher = fetcher or HttpFetcher()

    for source_fetcher in source_fetchers or []:
        try:
            attempt = _fetch_and_render(
                source_fetcher,
                resolved.url,
                doi=resolved.doi,
                min_text_length=min_text_length,
            )
        except Exception:
            continue
        if _attempt_is_usable_fulltext(attempt):
            return _save_success(
                identifier,
                output_dir=output_dir,
                resolved_original=resolved.original,
                resolved_doi=resolved.doi,
                attempt=attempt,
                snapshotter=snapshotter,
                download_assets=download_assets,
                asset_session=asset_session or _asset_session(source_fetcher),
            )

    try:
        attempt = _fetch_and_render(
            active_fetcher,
            resolved.url,
            doi=resolved.doi,
            min_text_length=min_text_length,
        )
    except Exception as exc:
        return SaveResult(
            identifier=identifier,
            status="fetch_error",
            doi=resolved.doi,
            source_url=resolved.url,
            warnings=[],
            error=f"{type(exc).__name__}: {exc}",
        )

    if _attempt_is_usable_fulltext(attempt):
        return _save_success(
            identifier,
            output_dir=output_dir,
            resolved_original=resolved.original,
            resolved_doi=resolved.doi,
            attempt=attempt,
            snapshotter=snapshotter,
            download_assets=download_assets,
            asset_session=asset_session or _asset_session(active_fetcher),
        )

    if attempt.invalid_warnings and auth_fetcher is None:
        return SaveResult(
            identifier=identifier,
            status="auth_required",
            doi=resolved.doi,
            title=attempt.document.title,
            source_url=attempt.document.source_url,
            warnings=_combined_warnings(
                attempt.document.warnings,
                attempt.response.warnings,
                attempt.invalid_warnings,
            ),
            structure=attempt.structure.to_summary(),
        )

    if not attempt.document.has_fulltext and auth_fetcher is not None:
        return _retry_with_auth_fetcher(
            identifier,
            output_dir=output_dir,
            resolved_url=resolved.url,
            resolved_doi=resolved.doi,
            resolved_original=resolved.original,
            auth_fetcher=auth_fetcher,
            snapshotter=snapshotter,
            min_text_length=min_text_length,
            download_assets=download_assets,
            asset_session=asset_session,
        )

    if attempt.invalid_warnings and auth_fetcher is not None:
        return _retry_with_auth_fetcher(
            identifier,
            output_dir=output_dir,
            resolved_url=resolved.url,
            resolved_doi=resolved.doi,
            resolved_original=resolved.original,
            auth_fetcher=auth_fetcher,
            snapshotter=snapshotter,
            min_text_length=min_text_length,
            download_assets=download_assets,
            asset_session=asset_session,
        )

    if not attempt.document.has_fulltext:
        status = _missing_access_status(attempt.response.source, attempt.response.warnings)
        return SaveResult(
            identifier=identifier,
            status=status,
            doi=resolved.doi,
            title=attempt.document.title,
            source_url=attempt.document.source_url,
            warnings=_combined_warnings(attempt.document.warnings, attempt.response.warnings),
            structure=attempt.structure.to_summary(),
        )

    return SaveResult(
        identifier=identifier,
        status="auth_required",
        doi=resolved.doi,
        title=attempt.document.title,
        source_url=attempt.document.source_url,
        warnings=_combined_warnings(attempt.document.warnings, attempt.response.warnings),
        structure=attempt.structure.to_summary(),
    )


def batch_save_clean_html(
    identifiers: Iterable[str],
    *,
    output_dir: str | Path,
    fetcher: object | None = None,
    source_fetchers: Iterable[object] | None = None,
    auth_fetcher: object | None = None,
    snapshotter: object | None = None,
    min_text_length: int = 500,
    download_assets: bool = False,
    asset_session: object | None = None,
    retry_incomplete_rounds: int = 0,
) -> list[SaveResult]:
    active_fetcher = fetcher or HttpFetcher()
    active_source_fetchers = list(source_fetchers or [])
    identifier_list = list(identifiers)
    results = [
        save_clean_html(
            identifier,
            output_dir=output_dir,
            fetcher=active_fetcher,
            source_fetchers=active_source_fetchers,
            auth_fetcher=auth_fetcher,
            snapshotter=snapshotter,
            min_text_length=min_text_length,
            download_assets=download_assets,
            asset_session=asset_session,
        )
        for identifier in identifier_list
    ]
    for _round in range(max(0, int(retry_incomplete_rounds))):
        retry_indexes = [index for index, result in enumerate(results) if _should_retry_batch_result(result)]
        if not retry_indexes:
            break
        for index in retry_indexes:
            original_result = results[index]
            retry_identifier = _batch_retry_identifier(original_result)
            retry_result = save_clean_html(
                retry_identifier,
                output_dir=output_dir,
                fetcher=active_fetcher,
                source_fetchers=active_source_fetchers,
                auth_fetcher=auth_fetcher,
                snapshotter=snapshotter,
                min_text_length=min_text_length,
                download_assets=download_assets,
                asset_session=asset_session,
            )
            if retry_result.status == "success":
                results[index] = replace(
                    retry_result,
                    identifier=identifier_list[index],
                    doi=original_result.doi or retry_result.doi,
                )
    return results


def _should_retry_batch_result(result: SaveResult) -> bool:
    return result.status in {"auth_required", "fetch_error"}


def _batch_retry_identifier(result: SaveResult) -> str:
    normalized_doi = _normalize_doi(result.doi or result.identifier)
    if normalized_doi.startswith("10.1126/"):
        return f"https://www.science.org/doi/{normalized_doi}"
    return result.identifier


def _retry_with_auth_fetcher(
    identifier: str,
    *,
    output_dir: str | Path,
    resolved_url: str,
    resolved_doi: str | None,
    resolved_original: str,
    auth_fetcher: object,
    snapshotter: object | None,
    min_text_length: int,
    download_assets: bool,
    asset_session: object | None,
) -> SaveResult:
    try:
        attempt = _fetch_and_render(
            auth_fetcher,
            resolved_url,
            doi=resolved_doi,
            min_text_length=min_text_length,
        )
    except Exception as exc:
        return SaveResult(
            identifier=identifier,
            status="fetch_error",
            doi=resolved_doi,
            source_url=resolved_url,
            warnings=[],
            error=f"{type(exc).__name__}: {exc}",
        )

    if attempt.invalid_warnings:
        return SaveResult(
            identifier=identifier,
            status="auth_required",
            doi=resolved_doi,
            title=attempt.document.title,
            source_url=attempt.document.source_url,
            warnings=_combined_warnings(
                attempt.document.warnings,
                attempt.response.warnings,
                attempt.invalid_warnings,
            ),
            structure=attempt.structure.to_summary(),
        )
    if not attempt.document.has_fulltext:
        return SaveResult(
            identifier=identifier,
            status=_missing_access_status(attempt.response.source, attempt.response.warnings),
            doi=resolved_doi,
            title=attempt.document.title,
            source_url=attempt.document.source_url,
            warnings=_combined_warnings(attempt.document.warnings, attempt.response.warnings),
            structure=attempt.structure.to_summary(),
        )

    return _save_success(
        identifier,
        output_dir=output_dir,
        resolved_original=resolved_original,
        resolved_doi=resolved_doi,
        attempt=attempt,
        snapshotter=snapshotter,
        download_assets=download_assets,
        asset_session=asset_session or _asset_session(auth_fetcher),
    )


def _fetch_and_render(
    fetcher: object,
    url: str,
    *,
    doi: str | None,
    min_text_length: int,
) -> _RenderedAttempt:
    response = fetcher.fetch(url)
    source_url = response.final_url or url
    structure = extract_article_structure(response.html, source_url=source_url, doi=doi)
    document = CleanHtmlRenderer(min_text_length=min_text_length).render(
        response.html,
        source_url=source_url,
        doi=doi,
    )
    invalid_warnings = [
        warning
        for warning in (
            _science_identifier_mismatch_warning(
                doi=doi,
                source_url=source_url,
                html=response.html,
            ),
            _science_home_redirect_warning(
                doi=doi,
                title=document.title,
                html=response.html,
            ),
            _wiley_abstract_page_warning(source_url=source_url),
            *structure.blocking_warnings(),
            *_blocking_browser_access_warnings(response.warnings),
        )
        if warning
    ]
    return _RenderedAttempt(
        response=response,
        document=document,
        invalid_warnings=invalid_warnings,
        structure=structure,
    )


def _attempt_is_usable_fulltext(attempt: _RenderedAttempt) -> bool:
    return attempt.document.has_fulltext and not attempt.invalid_warnings


def _save_success(
    identifier: str,
    *,
    output_dir: str | Path,
    resolved_original: str,
    resolved_doi: str | None,
    attempt: _RenderedAttempt,
    snapshotter: object | None,
    download_assets: bool,
    asset_session: object | None,
) -> SaveResult:
    output_path = _output_path(output_dir, resolved_doi or resolved_original, attempt.document.title)
    html = attempt.document.html
    asset_warnings: list[str] = []
    if download_assets:
        try:
            html, asset_warnings = localize_image_assets(
                html,
                output_path=output_path,
                source_url=attempt.document.source_url,
                session=asset_session,
            )
        except Exception as exc:
            asset_warnings = [f"image asset localization failed: {type(exc).__name__}: {exc}"]
    structure = extract_article_structure(
        html,
        source_url=attempt.document.source_url,
        doi=resolved_doi,
    )
    _write_text_atomic(output_path, html)
    warnings = _combined_warnings(attempt.document.warnings, attempt.response.warnings, asset_warnings)
    snapshot_path = None
    if snapshotter is not None:
        try:
            snapshot_path = snapshotter.save(
                attempt.response,
                output_path=output_path,
                identifier=identifier,
                doi=resolved_doi,
                title=attempt.document.title,
            )
        except Exception as exc:
            warnings = _combined_warnings(warnings, [f"snapshot failed: {type(exc).__name__}: {exc}"])
    return SaveResult(
        identifier=identifier,
        status="success",
        output_path=output_path,
        snapshot_path=snapshot_path,
        title=attempt.document.title,
        doi=resolved_doi,
        source_url=attempt.document.source_url,
        warnings=warnings,
        structure=structure.to_summary(),
    )


def _missing_access_status(source: str, warnings: list[str] | None = None) -> str:
    if warnings and any(
        warning
        in {
            "browser access state: access_entry",
            "browser access state: institution_picker",
            "browser access state: human_login",
            "browser access state: security_challenge",
        }
        for warning in warnings
    ):
        return "auth_required"
    return "auth_required" if source in {"http", "static"} else "no_access"


def _combined_warnings(*warning_lists: list[str]) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for warnings in warning_lists:
        for warning in warnings:
            if warning and warning not in seen:
                combined.append(warning)
                seen.add(warning)
    return combined


def _asset_session(candidate: object | None) -> object | None:
    return candidate if callable(getattr(candidate, "get", None)) else None


def _science_identifier_mismatch_warning(
    *,
    doi: str | None,
    source_url: str,
    html: str,
) -> str:
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi or not normalized_doi.startswith("10.1126/"):
        return ""
    haystack = _normalize_doi_haystack(html)
    if normalized_doi in haystack:
        return ""
    return "science HTML does not contain the requested DOI; likely login/home redirect, not article full text"


def _science_home_redirect_warning(
    *,
    doi: str | None,
    title: str,
    html: str,
) -> str:
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi or not normalized_doi.startswith("10.1126/"):
        return ""
    title_normalized = " ".join(str(title or "").lower().split())
    text = _normalize_doi_haystack(html)
    home_markers = (
        "latest news",
        "first release",
        "science translational medicine",
        "science advances",
        "science immunology",
        "science robotics",
    )
    if title_normalized in {"science | aaas", "science | science | aaas"} and sum(
        1 for marker in home_markers if marker in text
    ) >= 2:
        return "science channel/home page detected instead of requested article full text"
    return ""


def _wiley_abstract_page_warning(*, source_url: str) -> str:
    normalized = unquote(str(source_url or "")).lower()
    if "onlinelibrary.wiley.com/doi/abs/" in normalized:
        return "wiley abstract page detected instead of full article HTML"
    return ""


def _blocking_browser_access_warnings(warnings: list[str] | None) -> list[str]:
    blocking_states = {
        "browser access state: access_entry",
        "browser access state: institution_picker",
        "browser access state: human_login",
        "browser access state: subscription_preview",
        "browser access state: security_challenge",
    }
    return [warning for warning in warnings or [] if warning in blocking_states]


def _normalize_doi(value: str | None) -> str:
    value = unquote(str(value or "")).lower().strip()
    value = value.removeprefix("https://doi.org/")
    value = value.removeprefix("http://doi.org/")
    value = value.removeprefix("doi:")
    return value


def _normalize_doi_haystack(value: str) -> str:
    return unquote(value).lower()


def _output_path(output_dir: str | Path, identifier: str, title: str) -> Path:
    identifier_part = safe_identifier_part(identifier)
    title_part = title_slug(title)
    return Path(output_dir) / f"{identifier_part}_{title_part}.html"


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".part")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
