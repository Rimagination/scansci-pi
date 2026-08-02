from __future__ import annotations

from types import SimpleNamespace

import pytest

from scansci_html.local_model_inference import choose_local_model_plan


class FakeCuda:
    def __init__(self, *, available: bool, vram_gib: float = 0, bf16: bool = True) -> None:
        self.available = available
        self.vram_gib = vram_gib
        self.bf16 = bf16

    def is_available(self) -> bool:
        return self.available

    def get_device_properties(self, _index: int) -> SimpleNamespace:
        return SimpleNamespace(total_memory=int(self.vram_gib * 1024**3), name="Fake RTX")

    def get_device_name(self, _index: int) -> str:
        return "Fake RTX"

    def is_bf16_supported(self) -> bool:
        return self.bf16


def fake_torch(*, available: bool, vram_gib: float = 0, bf16: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        __version__="2.13.0+cu130" if available else "2.13.0+cpu",
        version=SimpleNamespace(cuda="13.0" if available else None),
        cuda=FakeCuda(available=available, vram_gib=vram_gib, bf16=bf16),
    )


def test_eight_gib_gpu_uses_four_bit_cuda() -> None:
    plan = choose_local_model_plan(
        fake_torch(available=True, vram_gib=8),
        model_weight_gib=8.7,
    )

    assert plan.device == "cuda:0"
    assert plan.quantization == "4bit"
    assert plan.compute_dtype == "bfloat16"
    assert plan.gpu_name == "Fake RTX"


def test_large_gpu_uses_native_precision() -> None:
    plan = choose_local_model_plan(
        fake_torch(available=True, vram_gib=24, bf16=False),
        model_weight_gib=8.7,
    )

    assert plan.device == "cuda:0"
    assert plan.quantization == "none"
    assert plan.compute_dtype == "float16"


def test_small_model_uses_native_bf16_on_eight_gib_gpu() -> None:
    plan = choose_local_model_plan(
        fake_torch(available=True, vram_gib=8),
        model_weight_gib=4.2,
    )

    assert plan.device == "cuda:0"
    assert plan.quantization == "none"
    assert plan.compute_dtype == "bfloat16"


def test_explicit_cuda_does_not_silently_fall_back_to_cpu() -> None:
    with pytest.raises(RuntimeError, match="无法使用 CUDA"):
        choose_local_model_plan(fake_torch(available=False), device_preference="cuda")


def test_cpu_mode_is_still_available_when_explicitly_selected() -> None:
    plan = choose_local_model_plan(
        fake_torch(available=True, vram_gib=8),
        device_preference="cpu",
    )

    assert plan.device == "cpu"
    assert plan.quantization == "none"
