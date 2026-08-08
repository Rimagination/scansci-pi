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
    runtime = local_asr.LocalASRRuntime()
    runtime._model_id = record["id"]
    runtime._model_path = model_path.resolve()
    runtime._loaded = local_asr._LoadedASR(
        processor=_Processor(), model=_Model(), torch=_Torch(), device="cpu"
    )

    assert runtime.transcribe(record["id"], audio) == "这是一段本地语音转写"


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
