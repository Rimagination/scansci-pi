from contextlib import nullcontext
from pathlib import Path

import pytest

from scansci_html import local_asr
from scansci_html.local_model_market import QWEN3_ASR_LEGACY_MODEL_ID, QWEN3_ASR_NATIVE_MODEL_ID


class _Tensor:
    ndim = 2
    shape = (1, 2)

    def to(self, _device):
        return self

    def __getitem__(self, _key):
        return self


class _Torch:
    def inference_mode(self):
        return nullcontext()


class _Processor:
    def apply_transcription_request(self, **kwargs):
        assert kwargs["audio"]
        return {"input_ids": _Tensor()}

    def decode(self, _output_ids, *, return_format):
        assert return_format == "transcription_only"
        return "这是一段本地语音转写"


class _Model:
    def generate(self, **_kwargs):
        return _Tensor()


class _FloatingTensor:
    def __init__(self):
        self.moves = []

    def to(self, *args, **kwargs):
        self.moves.append((args, kwargs))
        return self

    def is_floating_point(self):
        return True


def test_local_asr_transcribes_a_ready_snapshot_without_reloading(monkeypatch, tmp_path: Path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")
    model_path = tmp_path / "model"
    model_path.mkdir()
    record = {
        "id": QWEN3_ASR_NATIVE_MODEL_ID,
        "path": str(model_path),
        "ready": True,
        "kind": "audio",
        "format": "transformers",
    }
    monkeypatch.setattr(local_asr, "installed_models", lambda: [record])
    monkeypatch.setattr(local_asr, "_installed_runtime_component_available", lambda: False)
    runtime = local_asr.LocalASRRuntime()
    runtime._model_id = record["id"]
    runtime._model_path = model_path.resolve()
    runtime._loaded = local_asr._LoadedASR(
        processor=_Processor(), model=_Model(), torch=_Torch(), device="cpu"
    )

    assert runtime.transcribe(record["id"], audio) == "这是一段本地语音转写"


def test_local_asr_prefers_installed_isolated_runtime_over_in_process_weights(
    monkeypatch, tmp_path: Path
):
    """The desktop process must not map the 1.5 GB ASR checkpoint itself."""

    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")
    record = {
        "id": QWEN3_ASR_NATIVE_MODEL_ID,
        "path": str(tmp_path / "model"),
        "ready": True,
        "kind": "audio",
        "format": "transformers",
    }
    component_executable = tmp_path / "ScanSciLocalRuntime.exe"
    component_executable.write_bytes(b"runtime")

    class _Component:
        def executable(self):
            return component_executable

    calls = []
    monkeypatch.setattr(local_asr, "installed_models", lambda: [record])
    monkeypatch.setattr(local_asr, "default_local_runtime_component", lambda: _Component())
    monkeypatch.setattr(local_asr, "_in_process_dependencies_available", lambda: True)
    monkeypatch.setattr(
        local_asr,
        "_transcribe_with_component",
        lambda model_id, audio_path, *, language="": calls.append(
            (model_id, audio_path, language)
        ) or "component transcript",
    )

    runtime = local_asr.LocalASRRuntime()
    monkeypatch.setattr(
        runtime,
        "_ensure_model",
        lambda *_args: pytest.fail("must not load ASR weights in the web process"),
    )

    assert runtime.transcribe(record["id"], audio, language="zh") == "component transcript"
    assert calls == [(record["id"], audio.resolve(), "zh")]


def test_move_inputs_casts_floating_features_to_model_dtype():
    tensor = _FloatingTensor()

    moved = local_asr._move_inputs({"input_features": tensor}, "cuda:0", floating_dtype="bfloat16")

    assert moved["input_features"] is tensor
    assert tensor.moves == [(("cuda:0",), {}), ((), {"dtype": "bfloat16"})]


def test_local_asr_requires_a_complete_transformers_snapshot(monkeypatch, tmp_path: Path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(
        local_asr,
        "installed_models",
        lambda: [{"id": QWEN3_ASR_NATIVE_MODEL_ID, "ready": False, "kind": "audio"}],
    )
    with pytest.raises(RuntimeError, match="尚未完整下载"):
        local_asr.LocalASRRuntime().transcribe(QWEN3_ASR_NATIVE_MODEL_ID, audio)


def test_local_asr_rejects_the_legacy_qwen_checkpoint_before_loading(monkeypatch, tmp_path: Path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(
        local_asr,
        "installed_models",
        lambda: [{
            "id": QWEN3_ASR_LEGACY_MODEL_ID,
            "ready": True,
            "kind": "audio",
            "format": "transformers",
            "runtime_compatible": False,
            "runtime_message": "请下载 Qwen3-ASR-0.6B-hf",
        }],
    )
    with pytest.raises(RuntimeError, match="Qwen3-ASR-0.6B-hf"):
        local_asr.LocalASRRuntime().transcribe(QWEN3_ASR_LEGACY_MODEL_ID, audio)
