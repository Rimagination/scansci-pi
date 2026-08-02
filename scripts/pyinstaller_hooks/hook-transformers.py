"""Lean metadata hook for ScanSci's optional Transformers runtime.

The upstream PyInstaller hook copies every dependency's complete ``.dist-info``
directory.  Recent PyTorch wheels include a deeply nested third-party license
tree there; copying that tree can exceed Windows' legacy path limit during
``COLLECT`` even though Transformers only needs distribution metadata for
version checks.

Keep the metadata directory discoverable by ``importlib.metadata`` while
copying only its shallow runtime files.  Third-party license notices are
shipped separately in ``LOCAL_RUNTIME_THIRD_PARTY_NOTICES.md``.
"""

from importlib import metadata
from pathlib import Path

from PyInstaller.utils.hooks import get_module_attribute, is_module_satisfies, logger


datas = []
_METADATA_FILES = {
    "INSTALLER",
    "METADATA",
    "WHEEL",
    "direct_url.json",
    "entry_points.txt",
    "top_level.txt",
}

try:
    dependencies = get_module_attribute(
        "transformers.dependency_versions_table",
        "deps",
    )
except Exception:
    logger.warning(
        "hook-transformers: failed to query the Transformers dependency table.",
        exc_info=True,
    )
    dependencies = {}

for dependency_name, dependency_requirement in dependencies.items():
    if not is_module_satisfies(dependency_requirement):
        continue
    try:
        distribution = metadata.distribution(dependency_name)
        metadata_dir = Path(distribution._path)  # importlib.metadata has no public path accessor.
        if not metadata_dir.is_dir():
            continue
        destination = metadata_dir.name
        for source in metadata_dir.iterdir():
            if source.is_file() and source.name in _METADATA_FILES:
                datas.append((str(source), destination))
    except Exception:
        # Match the upstream hook's best-effort behavior. An optional
        # dependency that disappears during collection must not abort a build.
        continue

module_collection_mode = "pyz+py"
