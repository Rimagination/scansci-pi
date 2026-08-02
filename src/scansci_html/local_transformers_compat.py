"""Runtime compatibility switches for ScanSci's text-only Transformers sidecar."""

from __future__ import annotations

from typing import Any, Callable


_DISABLED_OPTIONAL_PACKAGES = frozenset({"torchaudio", "torchvision"})
_configured = False


def configure_text_only_transformers() -> None:
    """Prevent frozen text inference from probing excluded media backends.

    Recent Transformers releases import generic loss and image helpers while
    resolving ``PreTrainedModel``.  In a frozen application, distribution
    metadata for torchvision can remain discoverable even when the package was
    deliberately excluded.  That makes Transformers try to import a backend
    the text-only runtime neither needs nor ships.

    Patch the package-availability probe before Sentence Transformers or model
    classes are imported.  Normal text, embedding, reranking, and causal-LM
    code paths remain available.
    """

    global _configured
    if _configured:
        return

    from transformers.utils import import_utils

    original: Callable[..., tuple[bool, str]] = import_utils._is_package_available

    def text_only_package_available(
        package_name: str,
        return_version: bool = False,
    ) -> tuple[bool, str]:
        if str(package_name).casefold() in _DISABLED_OPTIONAL_PACKAGES:
            return False, "N/A"
        return original(package_name, return_version=return_version)

    import_utils._is_package_available = text_only_package_available
    for name in (
        "is_torchaudio_available",
        "is_torchvision_available",
        "is_torchvision_v2_available",
    ):
        probe: Any = getattr(import_utils, name, None)
        cache_clear = getattr(probe, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
    _configured = True
