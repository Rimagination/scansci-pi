"""Minimal PyTorch hook for ScanSci's Qwen retrieval/runtime bundle.

The upstream PyInstaller hook calls ``collect_submodules('torch')``.  That
walks PyTorch's training, benchmark, and test packages (including
``torch.testing._internal``) even though ScanSci only ships inference.  It
makes a clean Windows release build slow and, on some machines, effectively
non-terminating.  ScanSci declares the Qwen runtime imports explicitly in its
build scripts; this hook only preserves native libraries and run-time data.
"""

from PyInstaller import compat
from PyInstaller.utils.hooks import PY_DYLIB_PATTERNS, collect_data_files, collect_dynamic_libs


module_collection_mode = "pyz+py"
warn_on_missing_hiddenimports = False

datas = collect_data_files(
    "torch",
    excludes=[
        "**/testing/**",
        "**/test/**",
        "**/benchmark/**",
        "**/*.h",
        "**/*.hpp",
        "**/*.cuh",
        "**/*.lib",
        "**/*.cpp",
        "**/*.pyi",
        "**/*.cmake",
    ],
)
binaries = collect_dynamic_libs(
    "torch",
    search_patterns=PY_DYLIB_PATTERNS + ["*.so.*"],
)

# The official hook needs extra Linux CUDA-package inference.  ScanSci's
# release target is Windows and the Windows wheels carry their native DLLs in
# torch itself, collected above.
if not compat.is_win:  # pragma: no cover - Windows desktop release hook
    binaries = list(binaries)
