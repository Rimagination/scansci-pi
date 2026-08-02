from __future__ import annotations

import json

from scansci_html.notion_integration import NotionClient, NotionPage, _clean_id, _notion_cache_relative_path, _notion_title_text, _page_title


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_notion_client_reads_paginated_children_and_page_tree():
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith("/users/me"):
            return _Response({"id": "bot-1", "name": "ScanSci"})
        if "/pages/00000000-0000-0000-0000-000000000001" in req.full_url:
            return _Response({"id": "00000000-0000-0000-0000-000000000001", "url": "https://notion.so/root", "properties": {"Name": {"type": "title", "title": [{"plain_text": "Root"}]}}})
        if "start_cursor" in req.full_url:
            return _Response({"results": [{"id": "00000000-0000-0000-0000-000000000002", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "second"}]}}], "has_more": False})
        return _Response({"results": [{"id": "00000000-0000-0000-0000-000000000003", "type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Heading"}]}}, {"id": "00000000-0000-0000-0000-000000000002", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "first"}]}}], "has_more": True, "next_cursor": "next"})

    client = NotionClient("secret", opener=opener)
    pages = client.export_tree("https://www.notion.so/00000000-0000-0000-0000-000000000001")

    assert len(pages) == 1
    assert "# Heading" in pages[0].markdown
    assert "first" in pages[0].markdown
    assert "second" in pages[0].markdown
    assert any("start_cursor=next" in call for call in calls)


def test_notion_title_text_recovers_a_stringified_rich_text_list():
    assert _notion_title_text("[{'plain_text': 'People'}]") == "People"


def test_notion_child_page_is_hydrated_and_keeps_its_parent():
    root_id = "00000000-0000-0000-0000-000000000001"
    child_id = "00000000-0000-0000-0000-000000000002"

    def opener(req, timeout):
        url = req.full_url
        if f"/pages/{root_id}" in url:
            return _Response({
                "id": root_id,
                "url": "https://notion.so/root",
                "parent": {"type": "workspace", "workspace": True},
                "properties": {"Name": {"type": "title", "title": [{"plain_text": "Root"}]}},
            })
        if f"/pages/{child_id}" in url:
            return _Response({
                "id": child_id,
                "url": "https://notion.so/child",
                "parent": {"type": "page_id", "page_id": root_id},
                "properties": {"Name": {"type": "title", "title": [{"plain_text": "Child"}]}},
            })
        if f"/blocks/{root_id}/children" in url:
            return _Response({
                "results": [{"id": child_id, "type": "child_page", "has_children": True, "child_page": {"title": "Child"}}],
                "has_more": False,
            })
        if f"/blocks/{child_id}/children" in url:
            return _Response({"results": [], "has_more": False})
        raise AssertionError(url)

    pages = NotionClient("secret", opener=opener).export_tree(root_id)

    child = next(page for page in pages if page.page_id == child_id)
    assert child.title == "Child"
    assert child.url == "https://notion.so/child"
    assert child.parent_id == root_id
    assert child.parent_type == "page_id"


def test_notion_cache_path_follows_page_ancestors():
    root = NotionPage("00000000-0000-0000-0000-000000000001", "Root", "", "", parent_type="workspace")
    child = NotionPage(
        "00000000-0000-0000-0000-000000000002",
        "Child",
        "",
        "",
        parent_id=root.page_id,
        parent_type="page_id",
    )

    path = _notion_cache_relative_path(child, {root.page_id: root, child.page_id: child})

    assert len(path.parts) == 2
    assert path.parts[0].startswith("Root--")
    assert path.name.startswith("Child--")


def test_notion_helpers_normalize_ids_and_titles():
    assert _clean_id("https://notion.so/a/00000000-0000-0000-0000-000000000001") == "00000000-0000-0000-0000-000000000001"
    assert _clean_id("00000000000000000000000000000001") == "00000000-0000-0000-0000-000000000001"
    assert _page_title({"title": [{"plain_text": "People"}]}) == "People"
    assert _page_title({"properties": {"title": {"type": "title", "title": [{"plain_text": "页面"}]}}}) == "页面"
