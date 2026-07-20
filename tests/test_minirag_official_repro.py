from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def test_minirag_model_aliases_prefer_qwen35_by_default():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_minirag_official_repro.py"
    spec = spec_from_file_location("run_minirag_official_repro", script_path)
    assert spec is not None
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.MODEL_ALIASES["qwen"] == "Qwen/Qwen3.5-2B"
    assert module.MODEL_ALIASES["qwen35"] == "Qwen/Qwen3.5-2B"
    assert module.MODEL_ALIASES["qwen35tiny"] == "Qwen/Qwen3.5-0.8B"
    assert module.MODEL_ALIASES["qwen25"] == "Qwen/Qwen2.5-3B-Instruct"
