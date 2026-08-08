from pathlib import Path

from scansci_html import vision_routing


def _provider(provider_id, *, kind="openai-compatible", auth_mode="managed", logo="", models=None):
    return {
        "id": provider_id,
        "name": provider_id,
        "kind": kind,
        "auth_mode": auth_mode,
        "logo": logo,
        "base_url": "http://127.0.0.1:11434/v1" if logo == "ollama" else "https://example.invalid/v1",
        "enabled": True,
        "models": models or [],
    }


def test_selected_vision_model_is_honoured(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vision_routing, "get_provider_api_key", lambda *_args: "secret")
    provider = _provider(
        "cloud",
        models=[{"id": "vision-model", "capabilities": ["vision"]}],
    )
    route = vision_routing.select_vision_route(
        tmp_path,
        {"active_model": {"provider_id": "cloud", "model_id": "vision-model"}, "providers": [provider]},
        active_provider_id="cloud",
        active_model_id="vision-model",
    )

    assert route is not None
    assert route["mode"] == "selected"
    assert route["model_id"] == "vision-model"


def test_ready_local_vision_model_is_preferred_over_cloud(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vision_routing, "get_provider_api_key", lambda *_args: "local")
    monkeypatch.setattr(
        vision_routing,
        "ollama_status",
        lambda *_args: {"reachable": True, "model_ready": True},
    )
    local = _provider(
        "local-runtime-vision",
        auth_mode="local",
        logo="ollama",
        models=[{"id": "minicpm-v4.6", "capabilities": ["vision"]}],
    )
    cloud = _provider(
        "cloud",
        models=[{"id": "cloud-vision", "capabilities": ["vision"]}],
    )
    route = vision_routing.select_vision_route(
        tmp_path,
        {"active_model": {"provider_id": "cloud", "model_id": "text"}, "providers": [cloud, local]},
        active_provider_id="cloud",
        active_model_id="text",
    )

    assert route is not None
    assert route["mode"] == "local"
    assert route["provider_id"] == "local-runtime-vision"


def test_cloud_vision_is_used_when_no_local_runtime_is_ready(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vision_routing, "get_provider_api_key", lambda *_args: "secret")
    monkeypatch.setattr(
        vision_routing,
        "ollama_status",
        lambda *_args: {"reachable": False, "model_ready": False},
    )
    local = _provider(
        "local-runtime-vision",
        auth_mode="local",
        logo="ollama",
        models=[{"id": "minicpm-v4.6", "capabilities": ["vision"]}],
    )
    cloud = _provider(
        "cloud",
        models=[{"id": "cloud-vision", "capabilities": ["vision"]}],
    )
    route = vision_routing.select_vision_route(
        tmp_path,
        {"providers": [local, cloud]},
        active_provider_id="text",
        active_model_id="text-model",
    )

    assert route is not None
    assert route["mode"] == "cloud"
    assert route["provider_id"] == "cloud"


def test_ocr_fallback_reports_unavailable_without_raising(monkeypatch):
    monkeypatch.setattr(vision_routing, "_tesseract_path", lambda: "")

    result = vision_routing.ocr_image_blocks(
        [{"mime_type": "image/png", "data": "aGVsbG8="}],
    )

    assert result["available"] is False
    assert result["backend"] == "unavailable"
    assert "Tesseract" in result["message"]
