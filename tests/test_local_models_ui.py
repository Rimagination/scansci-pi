from pathlib import Path


APP_JS = Path(__file__).parents[1] / "src" / "scansci_html" / "web" / "app.js"


def test_local_models_page_does_not_duplicate_default_capability_routing():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'state.activeSettings === "local-models") settingsMarkup = renderLocalModelsSettingsPage();' in app_js
    assert "function renderLocalModelsSettingsPage()" in app_js
    assert '.replace(/<section class="local-agent-routing-card">' in app_js
    assert 'class="local-model-detection-note"' in app_js
    assert "一个模型可以同时拥有多项能力" in app_js
    assert 'class="composer-model-note"' in app_js
    assert "function renderDefaultCapabilitiesSettings()" in app_js
