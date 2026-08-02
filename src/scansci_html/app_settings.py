"""Local, redacted configuration for the ScanSci desktop workbench.

The configuration file deliberately contains no credentials.  Provider API keys
are stored through the operating-system keyring and the web API exposes only a
boolean indicating whether a key is available.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .local_model_market import installed_models

from .builtin_skills import default_skill_records
from .artifact_plugins import default_plugin_records, enrich_builtin_plugins


_CONFIG_NAME = ".scansci-notebook.json"
_SERVICE_NAME = "scansci-html-notebook"
_SAFE_ID = re.compile(r"[^a-z0-9._-]+")
_MAX_ITEMS = 128
_MANAGED_GATEWAY_BASE_URL = "https://scansci-glm-gateway.932196440.workers.dev/v1"
_MANAGED_PROVIDER_ID = "scansci-managed"
_MANAGED_PROVIDER_NAME = "ScanSci"
_DEFAULT_CHAT_MODEL_ID = "glm-4.7-flash"


def _provider_preset(
    identifier: str,
    name: str,
    *,
    category: str,
    base_url: str = "",
    kind: str = "openai-compatible",
    summary: str = "填写 API 地址与密钥后可读取服务商的模型列表。",
    models: list[dict[str, Any]] | None = None,
    auth_mode: str = "key",
    model_listing: bool = True,
) -> dict[str, Any]:
    """Describe a credential-free provider card shown by Model Services.

    Endpoints are intentionally supplied only for broadly documented, stable
    OpenAI/Anthropic-compatible APIs.  Aggregators and account-linked services
    start blank so an outdated endpoint can never silently send a key to the
    wrong host.
    """

    return {
        "id": identifier,
        "name": name,
        "logo": identifier,
        "kind": kind,
        "base_url": base_url,
        "category": category,
        "summary": summary,
        "auth_mode": auth_mode,
        "model_listing": model_listing,
        "models": models or [_model_preset("chat-model", "通用对话模型", group=name, capabilities=["reasoning"])],
    }


def _model_preset(
    identifier: str,
    name: str,
    *,
    group: str,
    capabilities: list[str],
    context_window: str = "",
    readiness: str = "production",
    automatic_fallback: bool = False,
) -> dict[str, Any]:
    """Build a visible, editable model record without credentials."""

    return {
        "id": identifier,
        "name": name,
        "group": group,
        "context_window": context_window,
        "capabilities": capabilities,
        # A routed model is not automatically a production fallback.  The
        # release probe must verify its actual task quality before an operator
        # grants it that role.
        "readiness": readiness,
        "automatic_fallback": bool(automatic_fallback),
    }


# The catalog mirrors Cherry Studio's documented providers and the providers
# currently exposed in its desktop catalog.  It is a discovery/configuration
# catalog, never a list of bundled or shared credentials.
_MANAGED_MODEL_PRESETS = [
    _model_preset("glm-4.7-flash", "GLM-4.7 Flash", group="GLM", context_window="200K", capabilities=["reasoning", "tool", "coding"]),
    # The gateway can route this standby model, but its current scientific
    # writing probe is below ScanSci's release contract.  Keep the route
    # visible to operations and probe it, without silently serving it as a
    # replacement for the primary model.
    _model_preset(
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen2.5 7B Instruct（待质量验证）",
        group="Qwen",
        context_window="32K",
        capabilities=["reasoning", "tool", "coding"],
        readiness="standby",
    ),
]


def managed_model_ids() -> tuple[str, ...]:
    """Return every managed route shown in the product catalog."""

    return tuple(str(model["id"]) for model in _MANAGED_MODEL_PRESETS)


def managed_probe_model_ids() -> tuple[str, ...]:
    """Return production routes that must pass the release health probe.

    A route marked ``standby`` remains visible for operator evaluation, but it
    must not turn an otherwise healthy release into a failed build before it
    has passed ScanSci's scientific-writing acceptance contract.
    """

    return tuple(
        str(model["id"])
        for model in _MANAGED_MODEL_PRESETS
        if str(model.get("readiness", "production")) == "production"
    )


def _managed_production_model_ids() -> set[str]:
    """Return managed routes that may serve user-visible answers."""

    return {
        str(model["id"])
        for model in _MANAGED_MODEL_PRESETS
        if str(model.get("readiness", "production")) == "production"
    }


def managed_fallback_model_ids(model_id: str) -> tuple[str, ...]:
    """Return only release-approved automatic fallbacks.

    Merely being reachable through the Worker is deliberately insufficient:
    a fallback must also pass ScanSci's structured research-writing probe.
    """

    selected = str(model_id or "").strip()
    return tuple(
        str(model["id"])
        for model in _MANAGED_MODEL_PRESETS
        if bool(model.get("automatic_fallback")) and str(model["id"]) != selected
    )


_PROVIDER_PRESETS: list[dict[str, Any]] = [
    _provider_preset(_MANAGED_PROVIDER_ID, _MANAGED_PROVIDER_NAME, category="ScanSci", base_url=_MANAGED_GATEWAY_BASE_URL, summary="Built-in managed models. Upstream credentials are held only by ScanSci's gateway.", auth_mode="managed", model_listing=False, models=_MANAGED_MODEL_PRESETS),
    _provider_preset("openai", "OpenAI", category="国际模型", base_url="https://api.openai.com/v1", models=[_model_preset("gpt-5.2", "GPT-5.2", group="GPT", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("gpt-5.2-mini", "GPT-5.2 mini", group="GPT", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("text-embedding-3-large", "text-embedding-3-large", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("anthropic", "Anthropic", category="国际模型", kind="anthropic-compatible", base_url="https://api.anthropic.com/v1", models=[_model_preset("claude-sonnet-4-6", "Claude Sonnet 4.6", group="Claude", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("claude-opus-4-6", "Claude Opus 4.6", group="Claude", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("gemini", "Google Gemini", category="国际模型", base_url="https://generativelanguage.googleapis.com/v1beta/openai", models=[_model_preset("gemini-3.1-pro-preview", "Gemini 3.1 Pro", group="Gemini", capabilities=["reasoning", "vision", "tool", "coding", "audio"]), _model_preset("gemini-3.5-flash", "Gemini 3.5 Flash", group="Gemini", capabilities=["reasoning", "vision", "tool"]), _model_preset("gemini-embedding-001", "Gemini Embedding", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("vertex-ai", "Google Vertex AI", category="国际模型", summary="Vertex AI 通常需要网关或企业项目凭据；请粘贴其兼容 API 地址。", models=[_model_preset("gemini-3.1-pro-preview", "Gemini 3.1 Pro", group="Gemini", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("text-embedding-005", "Text Embedding", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("openrouter", "OpenRouter", category="模型聚合", base_url="https://openrouter.ai/api/v1", models=[_model_preset("openai/gpt-5.2", "OpenAI GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", group="Google", capabilities=["reasoning", "vision", "tool"]), _model_preset("deepseek/deepseek-r1", "DeepSeek R1", group="DeepSeek", capabilities=["reasoning", "coding"])]),
    _provider_preset("nvidia", "NVIDIA NIM", category="国际模型", base_url="https://integrate.api.nvidia.com/v1", models=[_model_preset("meta/llama-3.3-70b-instruct", "Llama 3.3 70B Instruct", group="Meta", capabilities=["reasoning", "tool", "coding"]), _model_preset("nvidia/llama-3.2-nv-embedqa-1b-v2", "NV-EmbedQA", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("deepseek", "DeepSeek", category="国内直连", base_url="https://api.deepseek.com", models=[_model_preset("deepseek-chat", "DeepSeek Chat", group="DeepSeek", capabilities=["reasoning", "tool", "coding"]), _model_preset("deepseek-reasoner", "DeepSeek Reasoner", group="DeepSeek", capabilities=["reasoning", "coding"])]),
    _provider_preset("dashscope", "阿里云百炼", category="国内直连", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", models=[_model_preset("qwen-plus", "Qwen Plus", group="Qwen", capabilities=["reasoning", "tool", "coding"]), _model_preset("qwen-vl-plus", "Qwen VL Plus", group="Qwen", capabilities=["reasoning", "vision"]), _model_preset("text-embedding-v3", "Text Embedding V3", group="Embeddings", capabilities=["embedding"]), _model_preset("gte-rerank-v2", "GTE Rerank V2", group="Rerankers", capabilities=["reranking"])]),
    _provider_preset("zai", "Z.ai", category="国内直连", base_url="https://api.z.ai/api/paas/v4", models=[_model_preset("glm-4.7", "GLM-4.7", group="GLM", capabilities=["reasoning", "tool", "coding"]), _model_preset("glm-4.6v", "GLM-4.6V", group="GLM", capabilities=["reasoning", "vision"]), _model_preset("embedding-3", "Embedding-3", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("zhipu", "智谱开放平台", category="国内直连", base_url="https://open.bigmodel.cn/api/paas/v4", models=[_model_preset("glm-4.7-flash", "GLM-4.7 Flash（免费）", group="GLM", context_window="200K", capabilities=["reasoning", "tool", "coding"]), _model_preset("glm-4-plus", "GLM-4 Plus", group="GLM", capabilities=["reasoning", "tool", "coding"]), _model_preset("glm-4v-plus", "GLM-4V Plus", group="GLM", capabilities=["reasoning", "vision"]), _model_preset("embedding-3", "Embedding-3", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("moonshot", "Kimi", category="国内直连", base_url="https://api.moonshot.ai/v1", models=[_model_preset("kimi-k2.5", "Kimi K2.5", group="Kimi", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("moonshot-v1-128k", "Moonshot 128K", group="Kimi", capabilities=["reasoning", "tool"])]),
    _provider_preset("minimax", "MiniMax", category="国内直连", base_url="https://api.minimaxi.com/v1", models=[_model_preset("MiniMax-M2.7", "MiniMax M2.7", group="MiniMax", capabilities=["reasoning", "tool", "coding"]), _model_preset("MiniMax-VL-01", "MiniMax VL", group="MiniMax", capabilities=["reasoning", "vision"])]),
    _provider_preset("xiaomi-mimo", "Xiaomi MiMo", category="国内直连", models=[_model_preset("mimo-v2-flash", "MiMo V2 Flash", group="MiMo", capabilities=["reasoning", "tool", "coding"])]),
    _provider_preset("siliconflow", "硅基流动", category="云端推理", base_url="https://api.siliconflow.cn/v1", models=[_model_preset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", group="DeepSeek", capabilities=["reasoning", "tool", "coding"]), _model_preset("Qwen/Qwen2.5-VL-72B-Instruct", "Qwen VL 72B", group="Qwen", capabilities=["reasoning", "vision"]), _model_preset("BAAI/bge-m3", "BGE-M3", group="BAAI", capabilities=["embedding"]), _model_preset("BAAI/bge-reranker-v2-m3", "BGE Reranker V2 M3", group="BAAI", capabilities=["reranking"])]),
    _provider_preset("modelscope", "ModelScope", category="云端推理", base_url="https://api-inference.modelscope.cn/v1", models=[_model_preset("Qwen/Qwen2.5-72B-Instruct", "Qwen 2.5 72B", group="Qwen", capabilities=["reasoning", "tool", "coding"]), _model_preset("Qwen/Qwen2.5-VL-72B-Instruct", "Qwen VL 72B", group="Qwen", capabilities=["reasoning", "vision"]), _model_preset("iic/nlp_gte-rerank", "GTE Rerank", group="Rerankers", capabilities=["reranking"])]),
    _provider_preset("ppio", "PPIO Cloud", category="云端推理", models=[_model_preset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", group="DeepSeek", capabilities=["reasoning", "tool", "coding"]), _model_preset("Qwen/Qwen2.5-72B-Instruct", "Qwen 2.5 72B", group="Qwen", capabilities=["reasoning", "tool", "coding"])]),
    _provider_preset("volcengine", "火山引擎", category="云端推理", base_url="https://ark.cn-beijing.volces.com/api/v3", models=[_model_preset("doubao-seed-1-6-thinking", "Doubao Seed Thinking", group="Doubao", capabilities=["reasoning", "tool", "coding"]), _model_preset("doubao-1-5-vision-pro", "Doubao Vision Pro", group="Doubao", capabilities=["reasoning", "vision"]), _model_preset("doubao-embedding-large", "Doubao Embedding", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("huawei-cloud", "华为云", category="云端推理", models=[_model_preset("DeepSeek-R1", "DeepSeek R1", group="DeepSeek", capabilities=["reasoning", "coding"]), _model_preset("bge-m3", "BGE-M3", group="Embeddings", capabilities=["embedding"])]),
    _provider_preset("infinigence", "无问芯穹", category="云端推理", models=[_model_preset("Qwen2.5-72B-Instruct", "Qwen 2.5 72B", group="Qwen", capabilities=["reasoning", "tool", "coding"]), _model_preset("DeepSeek-R1", "DeepSeek R1", group="DeepSeek", capabilities=["reasoning", "coding"])]),
    _provider_preset("qiniu-ai", "七牛云 AI 推理", category="云端推理", models=[_model_preset("DeepSeek-V3", "DeepSeek V3", group="DeepSeek", capabilities=["reasoning", "tool", "coding"]), _model_preset("Qwen2.5-VL-72B-Instruct", "Qwen VL", group="Qwen", capabilities=["reasoning", "vision"])]),
    _provider_preset("modal", "Modal", category="云端推理", models=[_model_preset("zai-org/GLM-5.1-FP8", "GLM-5.1-FP8", group="zai-org", capabilities=["reasoning", "tool", "coding"])]),
    _provider_preset("new-api", "NewAPI", category="模型聚合", summary="自建 NewAPI 实例；请填入管理员提供的 OpenAI 兼容地址。", models=[_model_preset("gpt-5.2", "GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("one-api", "OneAPI", category="模型聚合", summary="自建 OneAPI 实例；请填入管理员提供的 OpenAI 兼容地址。", models=[_model_preset("gpt-5.2", "GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("aihubmix", "AiHubMix", category="模型聚合", models=[_model_preset("gpt-5.2", "GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("deepseek-r1", "DeepSeek R1", group="DeepSeek", capabilities=["reasoning", "coding"])]),
    _provider_preset("ocoolai", "ocoolAI", category="模型聚合", models=[_model_preset("gpt-5.2", "GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"]), _model_preset("claude-sonnet-4-6", "Claude Sonnet", group="Anthropic", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("alaya", "Alaya NeW", category="模型聚合", models=[_model_preset("deepseek-chat", "DeepSeek Chat", group="DeepSeek", capabilities=["reasoning", "tool", "coding"])]),
    _provider_preset("dmxapi", "DMXAPI", category="模型聚合", models=[_model_preset("gemini-3.1-pro-preview", "Gemini 3.1 Pro", group="Google", capabilities=["reasoning", "vision", "tool"])]),
    _provider_preset("aionly", "唯一AI (AiOnly)", category="模型聚合", models=[_model_preset("deepseek-chat", "DeepSeek Chat", group="DeepSeek", capabilities=["reasoning", "tool", "coding"])]),
    _provider_preset("burncloud", "BurnCloud", category="模型聚合", models=[_model_preset("gpt-5.2", "GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("cherryai", "CherryAI", category="Cherry 生态", summary="Cherry Studio 的账户入口；在 ScanSci 中请填写该账户提供的兼容地址和密钥。", auth_mode="account_or_key", models=[_model_preset("cherry-model", "Cherry 模型", group="CherryAI", capabilities=["reasoning", "tool"])]),
    _provider_preset("cherryin", "CherryIN", category="Cherry 生态", models=[_model_preset("gpt-5.2", "GPT-5.2", group="OpenAI", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("github-copilot", "GitHub Copilot", category="Cherry 生态", summary="Copilot 通常使用账户授权或专用令牌；请填写可用的兼容网关地址。", auth_mode="account_or_token", models=[_model_preset("gpt-5.2", "GPT-5.2", group="Copilot", capabilities=["reasoning", "vision", "tool", "coding"])]),
    _provider_preset("wuwen", "无问", category="Cherry 生态", models=[_model_preset("deepseek-r1", "DeepSeek R1", group="DeepSeek", capabilities=["reasoning", "coding"])]),
]


_LOCAL_MODEL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "name": "Ollama",
        "runtime": "ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "model_id": "",
        "enabled": False,
    },
    {
        "id": "lm-studio",
        "name": "LM Studio",
        "runtime": "lm-studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "model_id": "",
        "enabled": False,
    },
    {
        "id": "llama-cpp",
        "name": "llama.cpp Server",
        "runtime": "llama.cpp",
        "base_url": "http://127.0.0.1:8080/v1",
        "model_id": "",
        "enabled": False,
    },
]


class SettingsError(ValueError):
    """Raised when a local workbench setting cannot be read or stored."""


_DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": 2,
    "active_model": {"provider_id": _MANAGED_PROVIDER_ID, "model_id": _DEFAULT_CHAT_MODEL_ID},
    "providers": [
        {
            "id": _MANAGED_PROVIDER_ID,
            "name": _MANAGED_PROVIDER_NAME,
            "kind": "openai-compatible",
            "base_url": _MANAGED_GATEWAY_BASE_URL,
            "enabled": True,
            "auth_mode": "managed",
            "models": [
                {"id": _DEFAULT_CHAT_MODEL_ID, "name": "GLM-4.7 Flash", "group": "GLM", "context_window": "200K", "capabilities": ["reasoning", "tool", "coding"]},
            ],
        },
        {
            "id": "local-evidence",
            "name": "离线基础检索（非模型）",
            "kind": "local",
            "base_url": "",
            "enabled": True,
            "models": [
                {"id": "evidence-retrieval", "name": "关键词检索与词法重排（非模型）", "group": "离线回退", "context_window": "本地", "capabilities": ["embedding", "reranking"]},
            ],
        },
    ],
    "local_models": [
        {
            "id": "builtin-evidence",
            "name": "离线基础检索（非模型）",
            "runtime": "builtin",
            "base_url": "",
            "model_id": "local-hash-v1 / local-lexical-v1",
            "enabled": True,
        }
    ],
    "model_roles": {
        "reasoning": "provider:scansci-managed:glm-4.7-flash",
        "writing": "provider:scansci-managed:glm-4.7-flash",
        "retrieval": "local:builtin-evidence",
        "embedding": "local:builtin-evidence",
        "reranking": "local:builtin-evidence",
        "vision": "",
        "slides": "provider:scansci-managed:glm-4.7-flash",
    },
    "document_processing": {
        "ocr": {
            "provider": "system",
            "base_url": "",
            "languages": ["zh", "en"],
            "enabled": True,
        },
        "mineru": {
            "provider": "mineru",
            "base_url": "https://mineru.net",
            "enabled": False,
        },
    },
    "onboarding": {
        "welcome_dismissed": False,
        "resource_setup_completed": False,
        # Kept separately from the optional model download.  A user can start
        # work without any local files, then resume the data-source walkthrough
        # from Settings when they are ready to connect private material.
        "data_setup_completed": False,
    },
    "appearance": {
        "locale": "zh-CN",
        "theme": "system",
        "accent": "jade",
    },
    "skills": default_skill_records(),
    "mcp_servers": [],
    "plugins": default_plugin_records(),
}


def provider_presets() -> list[dict[str, Any]]:
    """Return credential-free API provider presets for the settings UI."""

    return deepcopy(_PROVIDER_PRESETS)


def local_model_presets() -> list[dict[str, Any]]:
    """Return common loopback model runtime presets."""

    return deepcopy(_LOCAL_MODEL_PRESETS)


def settings_path(workspace: str | Path) -> Path:
    """Return the per-workspace config file path without creating it."""

    return Path(workspace).resolve().parent / _CONFIG_NAME


def load_settings(workspace: str | Path) -> dict[str, Any]:
    """Load a safe public configuration and redact all provider credentials."""

    path = settings_path(workspace)
    raw: object = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SettingsError(f"无法读取本地设置：{exc}") from exc
    normalized = _normalize_settings(raw)
    return _with_secret_status(normalized, workspace)


def save_settings(workspace: str | Path, payload: object) -> dict[str, Any]:
    """Validate and atomically persist public settings (never provider keys)."""

    normalized = _normalize_settings(payload)
    path = settings_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise SettingsError(f"无法保存本地设置：{exc}") from exc
    return _with_secret_status(normalized, workspace)


def configure_managed_glm_4_7_flash(workspace: str | Path) -> dict[str, Any]:
    """Enable ScanSci's zero-configuration GLM service for one workspace."""

    settings = _normalize_settings(_read_raw_settings(workspace))
    provider = next((item for item in settings["providers"] if item["id"] == _MANAGED_PROVIDER_ID), None)
    if provider is None:  # Defensive: the common catalog normally guarantees this.
        raise SettingsError("Managed ScanSci provider preset is unavailable")

    provider["kind"] = "openai-compatible"
    provider["base_url"] = _MANAGED_GATEWAY_BASE_URL
    provider["enabled"] = True
    provider["auth_mode"] = "managed"
    preset = next(item for item in _PROVIDER_PRESETS if item["id"] == _MANAGED_PROVIDER_ID)
    available_model_ids = {str(model.get("id", "")) for model in provider["models"]}
    for model in reversed(preset["models"]):
        if model["id"] not in available_model_ids:
            provider["models"].insert(0, deepcopy(model))

    # Keep the built-in service at the top of an existing workspace too, so
    # people upgrading ScanSci immediately see the ready-to-use default.
    settings["providers"] = [
        provider,
        *(item for item in settings["providers"] if item["id"] != _MANAGED_PROVIDER_ID),
    ]

    reference = f"provider:{_MANAGED_PROVIDER_ID}:{_DEFAULT_CHAT_MODEL_ID}"
    settings["active_model"] = {"provider_id": _MANAGED_PROVIDER_ID, "model_id": _DEFAULT_CHAT_MODEL_ID}
    settings["model_roles"].update({"reasoning": reference, "writing": reference, "slides": reference, "vision": ""})
    return save_settings(workspace, settings)


def set_provider_api_key(workspace: str | Path, provider_id: str, value: str) -> dict[str, Any]:
    """Store a provider key in the OS credential manager, not the JSON file."""

    settings = _normalize_settings(_read_raw_settings(workspace))
    provider = next((item for item in settings["providers"] if item["id"] == provider_id), None)
    if provider is None:
        raise SettingsError("找不到模型提供商")
    if provider["kind"] == "local":
        raise SettingsError("本地证据引擎不需要 API Key")
    if provider.get("auth_mode") == "managed":
        raise SettingsError("ScanSci 托管模型不接受本机 API Key")
    secret = str(value or "").strip()
    try:
        import keyring

        username = _provider_secret_name(workspace, provider_id)
        if secret:
            keyring.set_password(_SERVICE_NAME, username, secret)
        else:
            try:
                keyring.delete_password(_SERVICE_NAME, username)
            except Exception:
                pass
    except Exception as exc:  # pragma: no cover - desktop keyring differs by OS
        raise SettingsError(f"无法访问系统凭据管理器：{exc}") from exc
    return _with_secret_status(settings, workspace)


def get_provider_api_key(workspace: str | Path, provider_id: str) -> str:
    """Read one provider secret for an in-process request without exposing it to the UI."""

    try:
        import keyring

        return str(keyring.get_password(_SERVICE_NAME, _provider_secret_name(workspace, provider_id)) or "")
    except Exception:
        return ""


def set_document_service_api_key(workspace: str | Path, service_id: str, value: str) -> dict[str, Any]:
    """Store a document-service key in the OS credential manager.

    The public settings file contains the selected provider, endpoint, and
    language preferences only.  OCR and MinerU keys follow the exact same
    redaction boundary as chat-model credentials.
    """

    service = _document_service_id(service_id)
    settings = _normalize_settings(_read_raw_settings(workspace))
    secret = str(value or "").strip()
    try:
        import keyring

        username = _document_service_secret_name(workspace, service)
        if secret:
            keyring.set_password(_SERVICE_NAME, username, secret)
        else:
            try:
                keyring.delete_password(_SERVICE_NAME, username)
            except Exception:
                pass
    except Exception as exc:  # pragma: no cover - desktop keyring differs by OS
        raise SettingsError(f"无法访问系统凭据管理器：{exc}") from exc
    return _with_secret_status(settings, workspace)


def get_document_service_api_key(workspace: str | Path, service_id: str) -> str:
    """Read one document-service secret for in-process parsing only."""

    try:
        import keyring

        return str(keyring.get_password(_SERVICE_NAME, _document_service_secret_name(workspace, _document_service_id(service_id))) or "")
    except Exception:
        return ""


def set_notion_api_token(workspace: str | Path, value: str) -> dict[str, Any]:
    """Store the Notion integration token in the OS credential manager."""

    secret = str(value or "").strip()
    try:
        import keyring

        username = _notion_secret_name(workspace)
        if secret:
            keyring.set_password(_SERVICE_NAME, username, secret)
        else:
            try:
                keyring.delete_password(_SERVICE_NAME, username)
            except Exception:
                pass
    except Exception as exc:  # pragma: no cover - desktop keyring differs by OS
        raise SettingsError(f"无法访问系统凭据管理器：{exc}") from exc
    return load_settings(workspace)


def get_notion_api_token(workspace: str | Path) -> str:
    """Read the Notion token for an in-process API request only."""

    try:
        import keyring

        return str(keyring.get_password(_SERVICE_NAME, _notion_secret_name(workspace)) or "")
    except Exception:
        return ""


def notion_api_token_configured(workspace: str | Path) -> bool:
    return bool(get_notion_api_token(workspace))


def _read_raw_settings(workspace: str | Path) -> object:
    path = settings_path(workspace)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"无法读取本地设置：{exc}") from exc


def _normalize_settings(payload: object) -> dict[str, Any]:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise SettingsError("设置必须是一个对象")
    defaults = deepcopy(_DEFAULT_SETTINGS)
    providers = _with_local_huggingface_provider(
        _with_common_provider_catalog(_normalize_providers(payload.get("providers", defaults["providers"])))
    )
    local_models = _normalize_local_models(payload.get("local_models", defaults["local_models"]))
    document_processing = _normalize_document_processing(payload.get("document_processing", defaults["document_processing"]))
    onboarding = _normalize_onboarding(payload.get("onboarding", defaults["onboarding"]))
    appearance = _normalize_appearance(payload.get("appearance", defaults["appearance"]))
    skills = _with_builtin_skills(_normalize_records(payload.get("skills", defaults["skills"]), kind="skill"))
    mcp_servers = _normalize_records(payload.get("mcp_servers", defaults["mcp_servers"]), kind="mcp")
    plugins = _with_builtin_plugins(_normalize_records(payload.get("plugins", defaults["plugins"]), kind="plugin"))
    active = payload.get("active_model", defaults["active_model"])
    if not isinstance(active, dict):
        active = {}
    provider_id = _safe_id(active.get("provider_id"), fallback=providers[0]["id"])
    provider = next((item for item in providers if item["id"] == provider_id), providers[0])
    model_id = _model_id(active.get("model_id"), fallback=provider["models"][0]["id"])
    if not any(model["id"] == model_id for model in provider["models"]):
        model_id = provider["models"][0]["id"]
    # Managed standby routes remain visible for diagnostics, but they are not
    # release-approved conversation models.  Migrate stale workspace choices
    # to the production default every time settings are loaded or saved so an
    # old selection cannot silently serve a user-visible answer.
    if provider["id"] == _MANAGED_PROVIDER_ID and model_id not in _managed_production_model_ids():
        model_id = _DEFAULT_CHAT_MODEL_ID
    model_roles = _normalize_model_roles(payload.get("model_roles", defaults["model_roles"]))
    for role, reference in list(model_roles.items()):
        prefix = f"provider:{_MANAGED_PROVIDER_ID}:"
        if reference.startswith(prefix) and reference.removeprefix(prefix) not in _managed_production_model_ids():
            model_roles[role] = f"{prefix}{_DEFAULT_CHAT_MODEL_ID}"
    return {
        "schema_version": 2,
        "active_model": {"provider_id": provider["id"], "model_id": model_id},
        "providers": providers,
        "local_models": local_models,
        "model_roles": model_roles,
        "document_processing": document_processing,
        "onboarding": onboarding,
        "appearance": appearance,
        "skills": skills,
        "mcp_servers": mcp_servers,
        "plugins": plugins,
    }


def _normalize_local_models(value: object) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(source[:_MAX_ITEMS]):
        if not isinstance(item, dict):
            continue
        identifier = _unique_id(_safe_id(item.get("id"), fallback=f"local-model-{index + 1}"), used)
        runtime = _text(item.get("runtime"), fallback="openai-compatible", limit=40).lower()
        if runtime not in {"builtin", "ollama", "lm-studio", "llama.cpp", "openai-compatible"}:
            runtime = "openai-compatible"
        if identifier == "builtin-evidence" and runtime == "builtin":
            name = "离线基础检索（非模型）"
            model_id = "local-hash-v1 / local-lexical-v1"
        else:
            name = _text(item.get("name"), fallback=identifier, limit=100)
            model_id = _text(item.get("model_id"), limit=160)
        rows.append(
            {
                "id": identifier,
                "name": name,
                "runtime": runtime,
                "base_url": _text(item.get("base_url"), limit=500),
                "model_id": model_id,
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return rows or deepcopy(_DEFAULT_SETTINGS["local_models"])


def _with_local_huggingface_provider(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose complete, text-generating HF snapshots as a selectable local provider.

    This row is derived from the local cache each time settings are normalized.
    It intentionally contains no token, endpoint configuration or duplicated
    download metadata: the runtime is loopback-only and starts lazily when a
    user actually sends a message.
    """

    def is_chat_model(item: dict[str, Any]) -> bool:
        marker = " ".join(
            [
                str(item.get("id", "")),
                str(item.get("model_type", "")),
            ]
        ).casefold()
        architecture = str(item.get("architecture", "")).casefold()
        is_generation_architecture = "forcausallm" in architecture or "forconditionalgeneration" in architecture
        return (
            bool(item.get("ready"))
            and str(item.get("format", "")) == "transformers"
            and is_generation_architecture
            and not any(word in marker for word in ("embedding", "reranker", "asr", "whisper", "reward"))
        )

    models = [
        {
            "id": str(item["id"]),
            "name": str(item.get("name") or item["id"]),
            "group": "本地 Hugging Face",
            "context_window": "本机",
            "capabilities": ["reasoning", "coding"],
        }
        for item in installed_models()
        if is_chat_model(item)
    ]
    rows = [item for item in providers if str(item.get("id", "")) != "local-huggingface"]
    if models:
        rows.append(
            {
                "id": "local-huggingface",
                "name": "本地 Hugging Face",
                "kind": "local",
                "base_url": "http://127.0.0.1:17863/v1",
                "enabled": True,
                "logo": "local-huggingface",
                "category": "本地模型",
                "summary": "由 ScanSci 在本机按需启动；模型权重始终保留在本地。",
                "auth_mode": "local",
                "model_listing": False,
                "models": models,
            }
        )
    return rows


def _normalize_model_roles(value: object) -> dict[str, str]:
    defaults = deepcopy(_DEFAULT_SETTINGS["model_roles"])
    if not isinstance(value, dict):
        return defaults
    return {
        role: _text(value.get(role), fallback=str(default), limit=240)
        for role, default in defaults.items()
    }


def _normalize_onboarding(value: object) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {
        "welcome_dismissed": bool(source.get("welcome_dismissed", False)),
        "resource_setup_completed": bool(source.get("resource_setup_completed", False)),
        "data_setup_completed": bool(source.get("data_setup_completed", False)),
    }


def _normalize_appearance(value: object) -> dict[str, str]:
    """Keep desktop presentation preferences small, portable, and predictable."""

    source = value if isinstance(value, dict) else {}
    locale = _text(source.get("locale"), fallback="zh-CN", limit=16)
    theme = _text(source.get("theme"), fallback="system", limit=16).lower()
    accent = _text(source.get("accent"), fallback="jade", limit=16).lower()
    return {
        "locale": locale if locale in {"zh-CN", "en"} else "zh-CN",
        "theme": theme if theme in {"system", "light", "dark"} else "system",
        "accent": accent if accent in {"jade", "ocean", "plum", "amber"} else "jade",
    }


def _normalize_document_processing(value: object) -> dict[str, Any]:
    """Validate the small public surface for OCR and scientific PDF parsing."""

    defaults = deepcopy(_DEFAULT_SETTINGS["document_processing"])
    source = value if isinstance(value, dict) else {}
    ocr_source = source.get("ocr") if isinstance(source.get("ocr"), dict) else {}
    mineru_source = source.get("mineru") if isinstance(source.get("mineru"), dict) else {}

    ocr_provider = _text(ocr_source.get("provider"), fallback=defaults["ocr"]["provider"], limit=32).lower()
    if ocr_provider not in {"system", "paddle", "custom"}:
        ocr_provider = "system"
    language_source = ocr_source.get("languages") if isinstance(ocr_source.get("languages"), list) else []
    languages = [
        code
        for code in (_text(item, limit=12).lower() for item in language_source)
        if code in {"zh", "en"}
    ]
    if not languages:
        languages = list(defaults["ocr"]["languages"])

    mineru_provider = _text(mineru_source.get("provider"), fallback=defaults["mineru"]["provider"], limit=32).lower()
    if mineru_provider not in {"mineru", "custom"}:
        mineru_provider = "mineru"
    mineru_base_url = _text(mineru_source.get("base_url"), fallback=defaults["mineru"]["base_url"], limit=500)

    return {
        "ocr": {
            "provider": ocr_provider,
            "base_url": _text(ocr_source.get("base_url"), limit=500),
            "languages": list(dict.fromkeys(languages)),
            "enabled": bool(ocr_source.get("enabled", defaults["ocr"]["enabled"])),
        },
        "mineru": {
            "provider": mineru_provider,
            "base_url": mineru_base_url,
            "enabled": bool(mineru_source.get("enabled", defaults["mineru"]["enabled"])),
        },
    }


def _normalize_providers(value: object) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(source[:_MAX_ITEMS]):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "openai-compatible") or "openai-compatible").strip().lower()
        if kind not in {"local", "openai-compatible", "anthropic-compatible"}:
            kind = "openai-compatible"
        fallback = "local-evidence" if kind == "local" else f"provider-{index + 1}"
        identifier = _unique_id(_safe_id(item.get("id"), fallback=fallback), used)
        models_source = item.get("models") if isinstance(item.get("models"), list) else []
        models = _normalize_models(models_source, fallback="evidence-retrieval" if kind == "local" else "model")
        if identifier == "local-evidence" and kind == "local":
            name = "离线基础检索（非模型）"
            models = [
                {
                    **model,
                    "name": "关键词检索与词法重排（非模型）",
                    "group": "离线回退",
                }
                if str(model.get("id", "")) == "evidence-retrieval"
                else model
                for model in models
            ]
        else:
            name = _text(item.get("name"), fallback="本地证据引擎" if kind == "local" else "未命名提供商", limit=80)
        rows.append(
            {
                "id": identifier,
                "name": name,
                "kind": kind,
                "base_url": _text(item.get("base_url"), limit=500),
                "enabled": bool(item.get("enabled", True)),
                "logo": _text(item.get("logo"), fallback=identifier, limit=80),
                "category": _text(item.get("category"), fallback="自定义提供商", limit=48),
                "summary": _text(item.get("summary"), limit=280),
                "auth_mode": _text(item.get("auth_mode"), fallback="key", limit=32).lower().replace("api_key", "key"),
                "model_listing": bool(item.get("model_listing", True)),
                "models": models,
            }
        )
    if rows:
        return rows
    return deepcopy(_DEFAULT_SETTINGS["providers"])


def _with_common_provider_catalog(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the common cloud catalog visible without enabling unconfigured APIs.

    Existing user records win over a preset with the same id.  New catalog rows
    are deliberately disabled until a user saves an API key or explicitly turns
    the provider on, so they never appear as accidentally selectable models.
    """

    rows = list(providers)
    catalog = {preset["id"]: preset for preset in _PROVIDER_PRESETS}
    for index, row in enumerate(rows):
        preset = catalog.get(str(row.get("id", "")))
        if not preset:
            continue
        # Preserve the user's endpoint, enablement, and selected models while
        # refreshing presentation and adapter metadata from the catalog.
        refreshed = {
            **row,
            "category": preset["category"],
            "logo": preset["logo"],
            "summary": preset["summary"],
            "auth_mode": preset["auth_mode"],
            "model_listing": preset["model_listing"],
        }
        if row.get("id") == _MANAGED_PROVIDER_ID:
            # ScanSci is product-owned catalog data rather than a user-named
            # custom provider. Refresh stale labels and model metadata from
            # earlier workspaces without touching their active-model choice.
            refreshed["name"] = _MANAGED_PROVIDER_NAME
            refreshed["kind"] = preset["kind"]
            refreshed["base_url"] = preset["base_url"]
            existing_models = {
                str(model.get("id", "")): model
                for model in refreshed["models"]
                if str(model.get("id", ""))
            }
            canonical_ids = {str(model.get("id", "")) for model in preset["models"]}
            refreshed["models"] = [
                {
                    **existing_models.get(str(model["id"]), {}),
                    **deepcopy(model),
                }
                for model in preset["models"]
            ] + [
                model
                for model in refreshed["models"]
                if str(model.get("id", "")) not in canonical_ids
            ]
        rows[index] = refreshed
    known_ids = {str(provider.get("id", "")) for provider in rows}
    for preset in _PROVIDER_PRESETS:
        if preset["id"] in known_ids:
            continue
        row = deepcopy(preset)
        row["enabled"] = preset["id"] == _MANAGED_PROVIDER_ID
        rows.append(row)
    return rows


_MODEL_CAPABILITIES = frozenset({"reasoning", "vision", "embedding", "reranking", "tool", "coding", "image", "audio"})


def _infer_model_capabilities(identifier: str) -> list[str]:
    """Give imported OpenAI-compatible model IDs a useful initial profile."""

    value = identifier.lower()
    capabilities: list[str] = []
    if any(token in value for token in ("embed", "bge-", "gte-")):
        capabilities.append("embedding")
    if any(token in value for token in ("rerank", "reranker")):
        capabilities.append("reranking")
    if any(token in value for token in ("vision", "-vl", "4v", "omni", "image")):
        capabilities.append("vision")
    if any(token in value for token in ("reasoner", "-r1", "thinking", "o1")):
        capabilities.append("reasoning")
    if "code" in value:
        capabilities.append("coding")
    if "audio" in value or "tts" in value:
        capabilities.append("audio")
    return capabilities or ["reasoning"]


def _normalize_capabilities(value: object, *, fallback: str) -> list[str]:
    source = value if isinstance(value, list) else []
    capabilities = [
        _text(item, limit=24).lower()
        for item in source[:16]
        if _text(item, limit=24).lower() in _MODEL_CAPABILITIES
    ]
    return list(dict.fromkeys(capabilities)) or _infer_model_capabilities(fallback)


def _normalize_models(value: object, *, fallback: str) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(source[:_MAX_ITEMS]):
        if not isinstance(item, dict):
            continue
        identifier = _unique_id(_model_id(item.get("id"), fallback=f"model-{index + 1}"), used)
        rows.append(
            {
                "id": identifier,
                "name": _text(item.get("name"), fallback=identifier, limit=120),
                "group": _text(item.get("group"), fallback="默认模型", limit=80),
                "context_window": _text(item.get("context_window"), fallback="", limit=40),
                "capabilities": _normalize_capabilities(item.get("capabilities"), fallback=identifier),
                "readiness": _text(item.get("readiness"), fallback="production", limit=24)
                if _text(item.get("readiness"), fallback="production", limit=24) in {"production", "standby"}
                else "production",
                "automatic_fallback": bool(item.get("automatic_fallback")),
            }
        )
    if rows:
        return rows
    return [{
        "id": fallback,
        "name": "证据检索" if fallback == "evidence-retrieval" else fallback,
        "group": "ScanSci" if fallback == "evidence-retrieval" else "默认模型",
        "context_window": "本地" if fallback == "evidence-retrieval" else "",
        "capabilities": ["embedding", "reranking"] if fallback == "evidence-retrieval" else ["reasoning"],
    }]


def _normalize_records(value: object, *, kind: str) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else []
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(source[:_MAX_ITEMS]):
        if not isinstance(item, dict):
            continue
        identifier = _unique_id(_safe_id(item.get("id"), fallback=f"{kind}-{index + 1}"), used)
        row = {
            "id": identifier,
            "name": _text(item.get("name"), fallback=f"未命名{kind}", limit=100),
            "description": _text(item.get("description"), limit=400),
            "enabled": bool(item.get("enabled", True)),
            "uninstalled": bool(item.get("uninstalled", False)),
        }
        if kind == "skill":
            row["path"] = _text(item.get("path"), limit=500)
            # Installed Skill packages carry their provenance so the extension
            # hub can distinguish built-ins from local, Git, archive, and
            # marketplace imports.  These fields are deliberately metadata
            # only: no executable command is persisted or launched here.
            row["source_type"] = _text(item.get("source_type"), limit=32)
            row["source"] = _text(item.get("source"), limit=1_000)
            row["installed_at"] = _text(item.get("installed_at"), limit=48)
        elif kind == "mcp":
            row["command"] = _text(item.get("command"), limit=500)
            row["args"] = _text(item.get("args"), limit=1_000)
            # Marketplace imports add provenance and connection metadata.  It
            # remains configuration only: persisting a server never executes
            # its command or contacts its endpoint.
            row["catalog_id"] = _text(item.get("catalog_id"), limit=200)
            row["source"] = _text(item.get("source"), limit=120)
            row["source_url"] = _text(item.get("source_url"), limit=500)
            row["discipline"] = _text(item.get("discipline"), limit=48)
            row["transport"] = _text(item.get("transport"), fallback="stdio", limit=40).lower()
            if row["transport"] not in {"stdio", "streamable-http", "sse"}:
                row["transport"] = "stdio"
            row["endpoint"] = _text(item.get("endpoint"), limit=500)
            row["version"] = _text(item.get("version"), limit=80)
            connector_kind = _text(item.get("connector_kind"), limit=32).lower()
            row["connector_kind"] = connector_kind if connector_kind in {"", "zotero", "obsidian", "general"} else "general"
            # Read-only is the product default.  A saved MCP cannot expose
            # write-like tools to Pi until the user explicitly opts in.
            row["allow_write"] = bool(item.get("allow_write", False))
            # Deferred servers expose a compact search/call surface and only
            # start the MCP process when the agent actually needs a tool.
            # Keep direct mode as the migration-safe default for existing
            # workspaces and connector integrations.
            row["deferred"] = bool(item.get("deferred", False))
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            row["tags"] = list(dict.fromkeys(_text(tag, limit=48) for tag in tags if _text(tag, limit=48)))[:12]
        elif kind == "plugin":
            row["source"] = _text(item.get("source"), limit=500)
            row["builtin"] = bool(item.get("builtin", False))
            row["icon"] = _text(item.get("icon"), limit=40)
            skills = item.get("skills") if isinstance(item.get("skills"), list) else []
            row["skills"] = list(dict.fromkeys(_text(value, limit=80) for value in skills if _text(value, limit=80)))[:12]
            tool_names = item.get("tool_names") if isinstance(item.get("tool_names"), list) else []
            row["tool_names"] = list(dict.fromkeys(_text(value, limit=80) for value in tool_names if _text(value, limit=80)))[:12]
        rows.append(row)
    if rows or kind not in {"skill"}:
        return rows
    return deepcopy(_DEFAULT_SETTINGS["skills"])


def _with_builtin_skills(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Refresh shipped Skill metadata without overriding user choices.

    The desktop app has already written settings files for earlier releases.
    Canonical metadata therefore needs to replace stale translated labels while
    preserving per-workspace enablement.  Zotero used to be misclassified as a
    Skill and is removed only when the record is the retired built-in package.
    """

    canonical = {record["id"]: record for record in default_skill_records()}
    refreshed: list[dict[str, Any]] = []
    for record in records:
        identifier = str(record.get("id", ""))
        is_builtin = str(record.get("path", "")).startswith("builtin:") or record.get("source_type") == "builtin"
        if identifier == "zotero" and is_builtin:
            continue
        shipped = canonical.get(identifier)
        if shipped:
            refreshed.append({**shipped, "enabled": bool(record.get("enabled", shipped["enabled"])), "uninstalled": bool(record.get("uninstalled", False))})
        else:
            refreshed.append(record)
    known = {str(record.get("id", "")) for record in refreshed}
    return [*refreshed, *(record for record in default_skill_records() if record["id"] not in known)]


def _with_builtin_plugins(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Refresh built-in plugin metadata while retaining user enablement."""

    canonical = {record["id"]: record for record in default_plugin_records()}
    refreshed: list[dict[str, Any]] = []
    for record in records:
        identifier = str(record.get("id", ""))
        shipped = canonical.get(identifier)
        if shipped and record.get("builtin"):
            refreshed.append({**shipped, "enabled": bool(record.get("enabled", shipped["enabled"])), "uninstalled": bool(record.get("uninstalled", False))})
        else:
            refreshed.append(record)
    known = {str(record.get("id", "")) for record in refreshed}
    return [*refreshed, *(record for record in default_plugin_records() if record["id"] not in known)]


def _with_secret_status(settings: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
    public = deepcopy(settings)
    public["plugins"] = enrich_builtin_plugins(list(public.get("plugins", []) or []))
    for provider in public["providers"]:
        provider["api_key_configured"] = provider.get("auth_mode") == "managed" or (provider["kind"] != "local" and _has_provider_api_key(workspace, provider["id"]))
    document_processing = public["document_processing"]
    document_processing["ocr"]["api_key_configured"] = _has_document_service_api_key(workspace, "ocr")
    document_processing["mineru"]["api_key_configured"] = _has_document_service_api_key(workspace, "mineru")
    return public


def _has_provider_api_key(workspace: str | Path, provider_id: str) -> bool:
    try:
        import keyring

        return bool(keyring.get_password(_SERVICE_NAME, _provider_secret_name(workspace, provider_id)))
    except Exception:
        return False


def _provider_secret_name(workspace: str | Path, provider_id: str) -> str:
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    return f"model-provider:{digest}:{provider_id}"


def _document_service_id(value: object) -> str:
    identifier = _safe_id(value, fallback="")
    if identifier not in {"ocr", "mineru"}:
        raise SettingsError("不支持的文档处理服务")
    return identifier


def _document_service_secret_name(workspace: str | Path, service_id: str) -> str:
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    return f"document-service:{digest}:{service_id}"


def _notion_secret_name(workspace: str | Path) -> str:
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    return f"notion-integration:{digest}"


def _has_document_service_api_key(workspace: str | Path, service_id: str) -> bool:
    try:
        import keyring

        return bool(keyring.get_password(_SERVICE_NAME, _document_service_secret_name(workspace, service_id)))
    except Exception:
        return False


def _text(value: object, *, fallback: str = "", limit: int = 200) -> str:
    text = str(value or "").strip()
    return (text[:limit] or fallback).strip()


def _safe_id(value: object, *, fallback: str) -> str:
    text = _SAFE_ID.sub("-", str(value or "").strip().lower()).strip(".-_")
    return text[:64] or fallback


def _model_id(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    text = "".join(character for character in text if character.isprintable() and not character.isspace())
    return text[:160] or fallback


def _unique_id(identifier: str, used: set[str]) -> str:
    candidate = identifier
    suffix = 2
    while candidate in used:
        candidate = f"{identifier[:56]}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
