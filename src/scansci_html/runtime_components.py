"""Managed runtime components for the Pi Node sidecar and Tectonic LaTeX.

The desktop core can be built without bundling ``node.exe`` or
``tectonic.exe``.  Like the local-Transformers sidecar, these binaries live in
independently versioned components under
``%LOCALAPPDATA%\\ScanSci\\runtimes\\<id>\\versions\\<version>``, are verified
by SHA256 from a manifest, and are only downloaded after the user confirms the
install.  Later ScanSci releases reuse the already-installed component instead
of re-downloading it with every update.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_runtime_component import LocalRuntimeComponent


NODE_COMPONENT_ID = "node"
NODE_EXECUTABLE_NAME = "node.exe"
NODE_MANIFEST_ENV = "SCANSCI_NODE_COMPONENT_MANIFEST_URL"
NODE_MANIFEST_FALLBACKS_ENV = "SCANSCI_NODE_COMPONENT_MANIFEST_FALLBACKS"
NODE_EXECUTABLE_ENV = "SCANSCI_NODE_COMPONENT_EXECUTABLE"
NODE_DEFAULT_MANIFEST_URL = (
    "https://github.com/Rimagination/scansci-portal/releases/download/runtime-components-v1/node.json"
)
NODE_DEFAULT_RELEASE_URL = (
    "https://github.com/Rimagination/scansci-portal/releases/tag/runtime-components-v1"
)

TECTONIC_COMPONENT_ID = "tectonic"
TECTONIC_EXECUTABLE_NAME = "tectonic.exe"
TECTONIC_MANIFEST_ENV = "SCANSCI_TECTONIC_COMPONENT_MANIFEST_URL"
TECTONIC_MANIFEST_FALLBACKS_ENV = "SCANSCI_TECTONIC_COMPONENT_MANIFEST_FALLBACKS"
TECTONIC_EXECUTABLE_ENV = "SCANSCI_TECTONIC_COMPONENT_EXECUTABLE"
TECTONIC_DEFAULT_MANIFEST_URL = (
    "https://github.com/Rimagination/scansci-portal/releases/download/runtime-components-v1/tectonic.json"
)
TECTONIC_DEFAULT_RELEASE_URL = (
    "https://github.com/Rimagination/scansci-portal/releases/tag/runtime-components-v1"
)


class NodeRuntimeComponent(LocalRuntimeComponent):
    """Manage the optional Node.js runtime used by the Pi sidecar."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        manifest_url: str | None = None,
        fallback_manifest_url: str | None = None,
    ) -> None:
        super().__init__(
            root=root,
            manifest_url=manifest_url,
            fallback_manifest_url=fallback_manifest_url,
            component_id=NODE_COMPONENT_ID,
            executable_name=NODE_EXECUTABLE_NAME,
            default_manifest_url=NODE_DEFAULT_MANIFEST_URL,
            default_release_url=NODE_DEFAULT_RELEASE_URL,
            manifest_env=NODE_MANIFEST_ENV,
            fallbacks_env=NODE_MANIFEST_FALLBACKS_ENV,
            executable_env=NODE_EXECUTABLE_ENV,
            build_manifest_key="node_component_manifest_url",
            display_name="Agent 运行组件",
            system_executable_names=("node.exe", "node"),
            source_dependency_modules=(),
        )


class TectonicRuntimeComponent(LocalRuntimeComponent):
    """Manage the optional Tectonic LaTeX engine used by slide rendering."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        manifest_url: str | None = None,
        fallback_manifest_url: str | None = None,
    ) -> None:
        super().__init__(
            root=root,
            manifest_url=manifest_url,
            fallback_manifest_url=fallback_manifest_url,
            component_id=TECTONIC_COMPONENT_ID,
            executable_name=TECTONIC_EXECUTABLE_NAME,
            default_manifest_url=TECTONIC_DEFAULT_MANIFEST_URL,
            default_release_url=TECTONIC_DEFAULT_RELEASE_URL,
            manifest_env=TECTONIC_MANIFEST_ENV,
            fallbacks_env=TECTONIC_MANIFEST_FALLBACKS_ENV,
            executable_env=TECTONIC_EXECUTABLE_ENV,
            build_manifest_key="tectonic_component_manifest_url",
            display_name="LaTeX 排版组件",
            system_executable_names=("tectonic.exe", "tectonic"),
            source_dependency_modules=(),
        )


_NODE_COMPONENT: NodeRuntimeComponent | None = None
_TECTONIC_COMPONENT: TectonicRuntimeComponent | None = None


def default_node_component() -> NodeRuntimeComponent:
    """Return the process-wide Node component manager."""

    global _NODE_COMPONENT
    if _NODE_COMPONENT is None:
        _NODE_COMPONENT = NodeRuntimeComponent()
    return _NODE_COMPONENT


def default_tectonic_component() -> TectonicRuntimeComponent:
    """Return the process-wide Tectonic component manager."""

    global _TECTONIC_COMPONENT
    if _TECTONIC_COMPONENT is None:
        _TECTONIC_COMPONENT = TectonicRuntimeComponent()
    return _TECTONIC_COMPONENT


def runtime_components_status() -> dict[str, Any]:
    """Report the status of all managed runtime components for the settings UI."""

    return {
        "node": default_node_component().status(),
        "tectonic": default_tectonic_component().status(),
    }


__all__ = [
    "NODE_COMPONENT_ID",
    "NODE_EXECUTABLE_NAME",
    "NODE_DEFAULT_MANIFEST_URL",
    "NODE_DEFAULT_RELEASE_URL",
    "NODE_EXECUTABLE_ENV",
    "NodeRuntimeComponent",
    "TECTONIC_COMPONENT_ID",
    "TECTONIC_EXECUTABLE_NAME",
    "TECTONIC_DEFAULT_MANIFEST_URL",
    "TECTONIC_DEFAULT_RELEASE_URL",
    "TECTONIC_EXECUTABLE_ENV",
    "TectonicRuntimeComponent",
    "default_node_component",
    "default_tectonic_component",
    "runtime_components_status",
]
