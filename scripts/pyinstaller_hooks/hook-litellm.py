"""Collect LiteLLM runtime data without shipping guardrail benchmark fixtures.

The upstream package contains a guardrail benchmark corpus intended for test
and evaluation workflows.  It is never loaded by ScanSci's desktop runtime,
but collecting every LiteLLM data file adds long nested paths that can make a
Windows installer build fail during PyInstaller's COLLECT phase.
"""

from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files(
    "litellm",
    excludes=[
        "**/guardrail_benchmarks/**",
    ],
)
