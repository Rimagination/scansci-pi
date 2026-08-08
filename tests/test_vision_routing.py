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


def test_system_ocr_prefers_native_backend_before_tesseract(monkeypatch):
    monkeypatch.setattr(
        vision_routing,
        "_system_ocr_image_blocks",
        lambda *_args, **_kwargs: {
            "text": "Windows OCR text",
            "backend": "windows-ocr",
            "available": True,
            "message": "已使用 Windows 系统 OCR",
        },
    )
    monkeypatch.setattr(vision_routing, "_tesseract_path", lambda: "")

    result = vision_routing.ocr_image_blocks(
        [{"mime_type": "image/png", "data": "aGVsbG8="}],
        settings={"document_processing": {"ocr": {"provider": "system", "enabled": True}}},
    )

    assert result["backend"] == "windows-ocr"
    assert result["available"] is True
    assert result["text"] == "Windows OCR text"


def test_system_ocr_status_reports_installed_languages(monkeypatch):
    class FakeLanguage:
        def __init__(self, tag):
            self.language_tag = tag

    class FakeEngine:
        @staticmethod
        def get_available_recognizer_languages():
            return [FakeLanguage("zh-Hans-CN"), FakeLanguage("en-US")]

        @staticmethod
        def try_create_from_user_profile_languages():
            return object()

    monkeypatch.setattr(
        vision_routing,
        "_load_windows_ocr_runtime",
        lambda **_kwargs: {"available": True, "OcrEngine": FakeEngine},
    )

    result = vision_routing.system_ocr_status(["zh", "en"])

    assert result["available"] is True
    assert result["backend"] == "windows-ocr"
    assert result["selected_language"] == "zh-Hans-CN"
    assert result["requested_supported"] is True


def test_deepseek_ocr_uses_configured_siliconflow_endpoint(tmp_path: Path, monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "# 扫描页\n\n这是 OCR 结果。"}}]}

    class FakeSession:
        def post(self, url, *, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return FakeResponse()

    monkeypatch.setattr(vision_routing, "get_document_service_api_key", lambda *_args: "siliconflow-secret")
    result = vision_routing.ocr_image_blocks(
        [{"mime_type": "image/png", "data": "aGVsbG8="}],
        workspace=tmp_path,
        settings={
            "document_processing": {
                "ocr": {
                    "provider": "deepseek",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "enabled": True,
                }
            }
        },
        session=FakeSession(),
    )

    assert result["backend"] == "deepseek-ocr"
    assert result["available"] is True
    assert result["text"].startswith("# 扫描页")
    assert calls[0][0] == "https://api.siliconflow.cn/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer siliconflow-secret"
    body = calls[0][2]
    assert body["model"] == "deepseek-ai/DeepSeek-OCR"
    assert body["messages"][0]["content"][0]["type"] == "text"
    assert "<|grounding|>Convert the document to markdown." in body["messages"][0]["content"][0]["text"]
    assert body["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
