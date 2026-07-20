"""PyInstaller entry point for the ScanSci desktop executable."""

from scansci_html.desktop import main


if __name__ == "__main__":
    raise SystemExit(main())
