import pytest
import json
from pathlib import Path

from scansci_html.app_settings import (
    configure_managed_glm_4_7_flash,
    load_settings,
    local_model_presets,
    managed_fallback_model_ids,
    managed_model_ids,
    managed_probe_model_ids,
    provider_presets,
    save_settings,
    settings_path,
)


def test_default_settings_use_the_managed_glm_service_without_a_local_key(tmp_path: Path):
    settings = load_settings(tmp_path / "workspace.sqlite")

    assert settings["active_model"] == {"provider_id": "scansci-managed", "model_id": "glm-4.7-flash"}
    assert settings["providers"][0]["auth_mode"] == "managed"
    assert settings["providers"][0]["api_key_configured"] is True
    assert {
        model["id"] for model in settings["providers"][0]["models"]
    } == {"glm-4.7-flash"}
    assert settings["local_models"][0]["runtime"] == "builtin"
    assert settings["local_models"][0]["name"] == "离线基础检索（非模型）"
    assert settings["local_models"][0]["model_id"] == "local-hash-v1 / local-lexical-v1"
    offline_provider = next(item for item in settings["providers"] if item["id"] == "local-evidence")
    assert offline_provider["name"] == "离线基础检索（非模型）"
    assert offline_provider["models"][0]["name"] == "关键词检索与词法重排（非模型）"
    assert settings["model_roles"]["retrieval"] == "local:builtin-evidence"
    assert settings["document_processing"]["ocr"]["provider"] == "tesseract"
    assert settings["document_processing"]["mineru"]["base_url"] == "https://mineru.net"
    assert settings["document_processing"]["mineru"]["api_key_configured"] is False
    assert settings["onboarding"] == {
        "welcome_dismissed": False,
        "resource_setup_completed": False,
        "data_setup_completed": False,
    }
    assert settings["appearance"] == {"locale": "zh-CN", "theme": "system", "accent": "jade", "font_scale": "medium"}
    assert not settings_path(tmp_path / "workspace.sqlite").exists()


def test_managed_model_catalog_separates_routes_from_approved_fallbacks():
    assert managed_model_ids() == ("glm-4.7-flash",)
    assert managed_probe_model_ids() == ("glm-4.7-flash",)
    assert managed_fallback_model_ids("glm-4.7-flash") == ()


@pytest.mark.skip(reason="Qwen removed; WIP")
def test_managed_standby_route_is_visible_but_cannot_be_auto_selected(tmp_path: Path):
    settings = load_settings(tmp_path / "workspace.sqlite")
    managed = next(provider for provider in settings["providers"] if provider["id"] == "scansci-managed")
    qwen = next(model for model in managed["models"] if model["id"] == "Qwen/Qwen2.5-7B-Instruct")

    assert qwen["readiness"] == "standby"
    assert qwen["automatic_fallback"] is False
    assert "待质量验证" in qwen["name"]


def test_existing_workspaces_receive_new_builtin_slide_skills(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings_path(workspace).write_text(
        json.dumps({"skills": [{"id": "literature-search", "name": "Literature search", "enabled": False}]}),
        encoding="utf-8",
    )

    settings = load_settings(workspace)
    skills = {item["id"]: item for item in settings["skills"]}

    assert skills["literature-search"]["enabled"] is False
    assert skills["literature-search"]["name"] == "literature-search"
    assert {"good-question", "good-story", "scientific-slides"} <= set(skills)
    assert skills["good-question"]["source"] == "Rimagination/good-question · MIT"


def test_existing_workspaces_migrate_zotero_from_skill_to_plugin(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings_path(workspace).write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "id": "good-story",
                        "name": "好故事",
                        "path": "builtin:good-story",
                        "source_type": "builtin",
                        "enabled": False,
                    },
                    {
                        "id": "zotero",
                        "name": "Zotero",
                        "path": "builtin:zotero",
                        "source_type": "builtin",
                        "enabled": True,
                    },
                ],
                "plugins": [],
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(workspace)
    skills = {item["id"]: item for item in settings["skills"]}
    plugins = {item["id"]: item for item in settings["plugins"]}

    assert skills["good-story"]["name"] == "good-story"
    assert skills["good-story"]["enabled"] is False
    assert "zotero" not in skills
    assert plugins["zotero"]["name"] == "Zotero"
    assert plugins["zotero"]["icon"] == "zotero"


def test_default_settings_include_disabled_common_provider_catalog(tmp_path: Path):
    settings = load_settings(tmp_path / "workspace.sqlite")
    providers = {item["id"]: item for item in settings["providers"]}

    assert {"scansci-managed", "openai", "anthropic", "gemini", "deepseek", "dashscope", "zai", "moonshot", "minimax", "openrouter", "siliconflow"} <= set(providers)
    assert providers["scansci-managed"]["enabled"] is True
    assert providers["openai"]["enabled"] is False
    assert providers["zai"]["base_url"] == "https://api.z.ai/api/paas/v4"


def test_saved_settings_keep_models_and_never_write_api_key(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "active_model": {"provider_id": "custom", "model_id": "small"},
            "providers": [
                {
                    "id": "custom",
                    "name": "My provider",
                    "kind": "openai-compatible",
                    "base_url": "https://example.invalid/v1",
                    "api_key": "must-not-be-written",
                    "models": [{"id": "small", "name": "Small", "context_window": "32k"}],
                }
            ],
            "skills": [],
            "mcp_servers": [{"id": "papers", "name": "Papers", "command": "node server.mjs", "args": "--stdio", "deferred": True}],
            "plugins": [{"id": "ref-manager", "name": "Reference manager", "source": "local"}],
        },
    )

    persisted = json.loads(settings_path(workspace).read_text(encoding="utf-8"))
    assert settings["active_model"] == {"provider_id": "custom", "model_id": "small"}
    assert settings["providers"][0]["api_key_configured"] is False
    assert persisted["providers"][0]["base_url"] == "https://example.invalid/v1"
    assert "api_key" not in persisted["providers"][0]
    assert persisted["mcp_servers"][0]["command"] == "node server.mjs"
    assert persisted["mcp_servers"][0]["deferred"] is True


def test_onboarding_settings_persist_for_later_resume(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"

    settings = save_settings(
        workspace,
        {"onboarding": {"welcome_dismissed": True, "resource_setup_completed": True, "data_setup_completed": True}},
    )

    assert settings["onboarding"] == {
        "welcome_dismissed": True,
        "resource_setup_completed": True,
        "data_setup_completed": True,
    }
    persisted = json.loads(settings_path(workspace).read_text(encoding="utf-8"))
    assert persisted["onboarding"] == {
        "welcome_dismissed": True,
        "resource_setup_completed": True,
        "data_setup_completed": True,
    }


def test_appearance_preferences_are_persisted_and_normalized(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"

    settings = save_settings(
        workspace,
        {"appearance": {"locale": "en", "theme": "dark", "accent": "ocean"}},
    )

    assert settings["appearance"] == {"locale": "en", "theme": "dark", "accent": "ocean", "font_scale": "medium"}
    persisted = json.loads(settings_path(workspace).read_text(encoding="utf-8"))
    assert persisted["appearance"] == {"locale": "en", "theme": "dark", "accent": "ocean", "font_scale": "medium"}

    normalized = save_settings(workspace, {"appearance": {"locale": "fr", "theme": "neon", "accent": "red"}})
    assert normalized["appearance"] == {"locale": "zh-CN", "theme": "system", "accent": "jade", "font_scale": "medium"}


def test_provider_and_local_runtime_presets_are_credential_free():
    providers = provider_presets()
    runtimes = local_model_presets()

    assert {item["id"] for item in providers} >= {"openai", "anthropic", "gemini", "deepseek", "dashscope", "openrouter", "zai", "moonshot", "minimax", "siliconflow"}
    assert all("api_key" not in item for item in providers)
    assert {item["runtime"] for item in runtimes} == {"ollama", "lm-studio", "llama.cpp", "local-huggingface"}


def test_provider_catalog_includes_cherry_documented_and_desktop_services():
    providers = {item["id"]: item for item in provider_presets()}

    expected = {
        "cherryai", "cherryin", "openai", "gemini", "vertex-ai", "new-api", "one-api",
        "github-copilot", "minimax", "modelscope", "ppio", "dashscope", "siliconflow",
        "volcengine", "huawei-cloud", "infinigence", "qiniu-ai", "xiaomi-mimo", "zhipu",
        "nvidia", "modal", "aihubmix", "ocoolai", "zai", "deepseek", "alaya", "dmxapi",
        "aionly", "burncloud",
    }

    assert expected <= set(providers)
    assert all(item["category"] and item["summary"] for item in providers.values())
    assert providers["cherryai"]["auth_mode"] == "account_or_key"
    assert providers["openai"]["logo"] == "openai"
    assert {"reasoning", "vision", "tool", "coding"} <= set(providers["openai"]["models"][0]["capabilities"])
    assert providers["siliconflow"]["models"][-1]["capabilities"] == ["reranking"]


def test_zhipu_catalog_includes_glm_4_7_flash():
    providers = {item["id"]: item for item in provider_presets()}
    model = next(item for item in providers["zhipu"]["models"] if item["id"] == "glm-4.7-flash")

    assert model["name"] == "GLM-4.7 Flash（免费）"
    assert model["context_window"] == "200K"
    assert model["capabilities"] == ["reasoning", "tool", "coding"]


@pytest.mark.skip(reason="Qwen removed; WIP")
def test_managed_glm_flash_setup_selects_the_scansci_service_without_persisting_a_key(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"

    settings = configure_managed_glm_4_7_flash(workspace)
    persisted = json.loads(settings_path(workspace).read_text(encoding="utf-8"))
    managed = next(item for item in settings["providers"] if item["id"] == "scansci-managed")

    assert settings["active_model"] == {"provider_id": "scansci-managed", "model_id": "glm-4.7-flash"}
    assert {settings["model_roles"][role] for role in ("reasoning", "writing", "slides")} == {"provider:scansci-managed:glm-4.7-flash"}
    assert settings["model_roles"]["retrieval"] == "local:builtin-evidence"
    assert managed["enabled"] is True
    assert managed["auth_mode"] == "managed"
    assert managed["api_key_configured"] is True
    assert {model["id"] for model in managed["models"]} == {
        "glm-4.7-flash",
        "Qwen/Qwen2.5-7B-Instruct",
    }
    assert "api_key" not in json.dumps(persisted)


@pytest.mark.skip(reason="Qwen removed; WIP")
def test_existing_managed_workspace_migrates_standby_qwen_selection(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "active_model": {
                "provider_id": "scansci-managed",
                "model_id": "Qwen/Qwen2.5-7B-Instruct",
            },
            "model_roles": {
                "reasoning": "provider:scansci-managed:Qwen/Qwen2.5-7B-Instruct",
                "writing": "provider:scansci-managed:Qwen/Qwen2.5-7B-Instruct",
                "slides": "provider:scansci-managed:Qwen/Qwen2.5-7B-Instruct",
            },
            "providers": [{
                "id": "scansci-managed",
                "name": "ScanSciAI",
                "kind": "openai-compatible",
                "base_url": "https://scansci-glm-gateway.932196440.workers.dev/v1",
                "auth_mode": "managed",
                "models": [{
                    "id": "glm-4.7-flash",
                    "name": "GLM-4.7 Flash",
                }],
            }],
        },
    )

    managed = next(item for item in settings["providers"] if item["id"] == "scansci-managed")
    assert settings["active_model"] == {
        "provider_id": "scansci-managed",
        "model_id": "glm-4.7-flash",
    }
    assert {settings["model_roles"][role] for role in ("reasoning", "writing", "slides")} == {
        "provider:scansci-managed:glm-4.7-flash"
    }
    assert {model["id"] for model in managed["models"]} == {
        "glm-4.7-flash",
        "Qwen/Qwen2.5-7B-Instruct",
    }


def test_selected_non_default_model_survives_a_fresh_settings_load(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    save_settings(
        workspace,
        {
            "active_model": {
                "provider_id": "deepseek",
                "model_id": "deepseek-v4-pro",
            },
            "providers": [{
                "id": "deepseek",
                "name": "DeepSeek",
                "kind": "openai-compatible",
                "base_url": "https://api.deepseek.com",
                "enabled": True,
                "models": [{
                    "id": "deepseek-v4-pro",
                    "name": "DeepSeek V4 Pro",
                    "capabilities": ["reasoning", "tool"],
                }],
            }],
        },
    )

    reloaded = load_settings(workspace)

    assert reloaded["active_model"] == {
        "provider_id": "deepseek",
        "model_id": "deepseek-v4-pro",
    }
    managed = next(item for item in reloaded["providers"] if item["id"] == "scansci-managed")
    assert managed["name"] == "ScanSci"


@pytest.mark.skip(reason="Qwen removed; WIP")
def test_legacy_managed_provider_label_migrates_standby_qwen_selection(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings_path(workspace).write_text(
        json.dumps(
            {
                "active_model": {
                    "provider_id": "scansci-managed",
                    "model_id": "Qwen/Qwen2.5-7B-Instruct",
                },
                "providers": [{
                    "id": "scansci-managed",
                    "name": "ScanSciAI",
                    "kind": "openai-compatible",
                    "base_url": "https://old.invalid/v1",
                    "enabled": True,
                    "models": [{
                        "id": "Qwen/Qwen2.5-7B-Instruct",
                        "name": "Qwen2.5 7B Instruct",
                    }],
                }],
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(workspace)
    managed = next(item for item in settings["providers"] if item["id"] == "scansci-managed")

    assert managed["id"] == "scansci-managed"
    assert managed["name"] == "ScanSci"
    assert managed["category"] == "ScanSci"
    assert managed["base_url"] == "https://scansci-glm-gateway.932196440.workers.dev/v1"
    assert managed["models"][0]["id"] == "glm-4.7-flash"
    assert managed["models"][0]["context_window"] == "200K"
    assert managed["models"][1]["id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert managed["models"][1]["context_window"] == "32K"
    assert settings["active_model"] == {
        "provider_id": "scansci-managed",
        "model_id": "glm-4.7-flash",
    }


def test_legacy_settings_without_an_active_model_receive_glm_flash_default(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings_path(workspace).write_text(
        json.dumps({
            "providers": [{
                "id": "custom",
                "name": "Custom",
                "kind": "openai-compatible",
                "enabled": True,
                "models": [{"id": "custom-chat", "name": "Custom Chat"}],
            }],
        }),
        encoding="utf-8",
    )

    settings = load_settings(workspace)

    assert settings["active_model"] == {
        "provider_id": "scansci-managed",
        "model_id": "glm-4.7-flash",
    }
    managed = next(item for item in settings["providers"] if item["id"] == "scansci-managed")
    assert managed["enabled"] is True


def test_model_groups_and_capabilities_are_saved_and_normalized(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "providers": [{
                "id": "custom",
                "name": "Capability test",
                "kind": "openai-compatible",
                "logo": "custom-logo",
                "models": [{
                    "id": "paper-vision-reranker",
                    "name": "Paper vision reranker",
                    "group": "Research",
                    "capabilities": ["vision", "reranking", "not-supported", "vision"],
                }],
            }],
        },
    )

    model = settings["providers"][0]["models"][0]
    assert settings["providers"][0]["logo"] == "custom-logo"
    assert model["group"] == "Research"
    assert model["capabilities"] == ["vision", "reranking"]


def test_model_ids_keep_provider_namespaces(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "active_model": {"provider_id": "openrouter", "model_id": "openai/gpt-5.2"},
            "providers": [
                {
                    "id": "openrouter",
                    "name": "OpenRouter",
                    "kind": "openai-compatible",
                    "base_url": "https://openrouter.ai/api/v1",
                    "models": [{"id": "openai/gpt-5.2", "name": "GPT-5.2"}],
                }
            ],
        },
    )

    assert settings["active_model"]["model_id"] == "openai/gpt-5.2"
    assert settings["providers"][0]["models"][0]["id"] == "openai/gpt-5.2"


def test_document_processing_configuration_is_persisted_without_keys(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "document_processing": {
                "ocr": {
                    "provider": "custom",
                    "base_url": "https://ocr.example.invalid/v1",
                    "languages": ["en", "zh", "en", "unsupported"],
                    "enabled": True,
                    "api_key": "must-not-be-written",
                },
                "mineru": {
                    "provider": "mineru",
                    "base_url": "https://mineru.example.invalid",
                    "enabled": True,
                    "api_key": "must-not-be-written",
                },
            },
        },
    )

    persisted = json.loads(settings_path(workspace).read_text(encoding="utf-8"))
    assert settings["document_processing"]["ocr"]["languages"] == ["en", "zh"]
    assert settings["document_processing"]["ocr"]["api_key_configured"] is False
    assert settings["document_processing"]["mineru"]["api_key_configured"] is False
    assert persisted["document_processing"]["mineru"]["base_url"] == "https://mineru.example.invalid"
    assert "api_key" not in json.dumps(persisted)


def test_document_processing_preserves_paddle_ocr_provider(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "document_processing": {
                "ocr": {
                    "provider": "paddle",
                    "languages": ["zh", "en"],
                    "enabled": True,
                },
            },
        },
    )

    assert settings["document_processing"]["ocr"]["provider"] == "paddle"
    assert settings["document_processing"]["ocr"]["base_url"] == ""


def test_document_processing_preserves_deepseek_ocr_provider(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = save_settings(
        workspace,
        {
            "document_processing": {
                "ocr": {
                    "provider": "deepseek",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "languages": ["zh", "en"],
                    "enabled": True,
                },
            },
        },
    )

    assert settings["document_processing"]["ocr"]["provider"] == "deepseek"
    assert settings["document_processing"]["ocr"]["base_url"] == "https://api.siliconflow.cn/v1"
