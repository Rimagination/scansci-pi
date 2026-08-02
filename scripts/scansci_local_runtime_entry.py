"""PyInstaller entry point for the optional ScanSci local-model runtime."""

from scansci_html.local_transformers_compat import configure_text_only_transformers

configure_text_only_transformers()

from scansci_html.local_runtime_server import main


if __name__ == "__main__":
    raise SystemExit(main())
