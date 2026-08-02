"""Run a deterministic browser-level regression check for ScanSci's composer.

The check substitutes only the model stream. The browser still loads ScanSci's
real server, app.js, routing preview, form event handlers and SSE parser. It
catches async submit regressions that mocked HTTP clients cannot, including an
event handler reading Event.currentTarget after an await.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scansci_html.research_agent import ResearchAgentRuntime  # noqa: E402
from scansci_html.webapp import create_notebook_server  # noqa: E402


def _fake_chat_stream(_self: ResearchAgentRuntime, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    messages = list(payload.get("messages", []) or [])
    question = str(messages[-1].get("content", "")) if messages else ""
    reply = f"frontend submit regression passed: {question}"
    yield {"type": "RUN_STARTED", "run_id": "frontend-submit-regression"}
    yield {"type": "TEXT_MESSAGE_CONTENT", "content": reply}
    yield {
        "type": "RUN_FINISHED",
        "result": {
            "message": {
                "role": "assistant",
                "content": reply,
                "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
            },
            "model": {"provider_id": "scansci-managed", "model_id": "glm-4.7-flash"},
        },
    }


def verify() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover - release machines must provide this dependency.
        raise RuntimeError("Playwright Python is required for the release browser regression check") from error

    original_stream = ResearchAgentRuntime.chat_stream
    ResearchAgentRuntime.chat_stream = _fake_chat_stream
    server = None
    thread = None
    try:
        with TemporaryDirectory(prefix="scansci-frontend-release-") as temporary:
            root = Path(temporary)
            server = create_notebook_server(workspace=root / "workspace.sqlite", evidence_db=root / "evidence.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True, name="scansci-frontend-release")
            thread.start()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                console_errors: list[str] = []
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="networkidle")
                page.locator("#homeQuestionInput").wait_for(state="visible", timeout=8_000)

                # Fresh temporary workspaces may show onboarding. Dismiss it only
                # when it is actually visible; failures must not be swallowed.
                onboarding = page.locator("#resourceOnboarding")
                if onboarding.count() and onboarding.is_visible():
                    page.locator('[data-action="skip-resource-onboarding"]').click()
                    onboarding.wait_for(state="hidden", timeout=3_000)

                click_question = "explain knowledge graph RAG"
                page.locator("#homeQuestionInput").fill(click_question)
                page.locator("#homeAskForm button[type=submit]").click()
                page.get_by_text(f"frontend submit regression passed: {click_question}").wait_for(timeout=8_000)
                conversation = page.locator('section[data-view="conversation"]')
                if not conversation.is_visible():
                    raise AssertionError("Click submission did not transition the application into the conversation view")
                if page.locator("#chatQuestionInput").input_value() != "":
                    raise AssertionError("The click-submitted text remained in the chat composer")

                enter_question = "explain evidence citation anchors"
                page.locator("#chatQuestionInput").fill(enter_question)
                page.locator("#chatQuestionInput").press("Enter")
                page.get_by_text(f"frontend submit regression passed: {enter_question}").wait_for(timeout=8_000)
                if page.locator("#chatQuestionInput").input_value() != "":
                    raise AssertionError("The Enter-submitted text remained in the chat composer")
                if any("currentTarget" in item or "querySelector" in item for item in console_errors):
                    raise AssertionError(f"Composer emitted a stale-event console error: {console_errors}")
                return {
                    "click_submit": True,
                    "enter_submit": True,
                    "conversation_visible": True,
                    "console_errors": console_errors,
                }
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=3)
        ResearchAgentRuntime.chat_stream = original_stream


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ScanSci's real browser composer submission flow.")
    parser.add_argument("--output", required=True, help="Write the JSON verification report here.")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = verify()
    output.write_text(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
