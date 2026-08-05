"""Print the optional Agent harness capability matrix without importing them."""

from __future__ import annotations

import json

from scansci_html.harness_adapters import probe_optional_harnesses


def main() -> int:
    print(json.dumps([probe.to_dict() for probe in probe_optional_harnesses()], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
