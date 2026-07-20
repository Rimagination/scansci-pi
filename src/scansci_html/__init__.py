"""HTML-only paper capture utilities."""

from .app_update import APP_VERSION

from .article_structure import ArticleSection, ArticleStructure, extract_article_structure
from .cnki_reader import cnki_reader_counts, download_cnki_reader_images, render_cnki_reader_json
from .models import CleanHtmlDocument, FetchResponse, SaveResult
from .service import batch_save_clean_html, save_clean_html

__all__ = [
    "APP_VERSION",
    "ArticleSection",
    "ArticleStructure",
    "CleanHtmlDocument",
    "FetchResponse",
    "SaveResult",
    "batch_save_clean_html",
    "cnki_reader_counts",
    "download_cnki_reader_images",
    "extract_article_structure",
    "render_cnki_reader_json",
    "save_clean_html",
]
