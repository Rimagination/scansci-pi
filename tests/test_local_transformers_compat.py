from functools import lru_cache
from types import ModuleType
import sys

from scansci_html import local_transformers_compat


def test_local_runtime_disables_audio_but_keeps_vision_backend(monkeypatch) -> None:
    import_utils = ModuleType("transformers.utils.import_utils")

    def package_available(name: str, return_version: bool = False) -> tuple[bool, str]:
        return True, "1.0.0"

    @lru_cache
    def torchvision_available() -> bool:
        return import_utils._is_package_available("torchvision")[0]

    @lru_cache
    def torchaudio_available() -> bool:
        return import_utils._is_package_available("torchaudio")[0]

    import_utils._is_package_available = package_available
    import_utils.is_torchvision_available = torchvision_available
    import_utils.is_torchvision_v2_available = torchvision_available
    import_utils.is_torchaudio_available = torchaudio_available

    utils = ModuleType("transformers.utils")
    utils.import_utils = import_utils
    transformers = ModuleType("transformers")
    transformers.utils = utils
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "transformers.utils", utils)
    monkeypatch.setitem(sys.modules, "transformers.utils.import_utils", import_utils)
    monkeypatch.setattr(local_transformers_compat, "_configured", False)

    local_transformers_compat.configure_text_only_transformers()

    assert import_utils._is_package_available("torchvision") == (True, "1.0.0")
    assert import_utils._is_package_available("torchaudio") == (False, "N/A")
    assert import_utils._is_package_available("torch") == (True, "1.0.0")
    assert import_utils.is_torchvision_available() is True
    assert import_utils.is_torchaudio_available() is False
