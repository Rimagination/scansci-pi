from scansci_html import web_search


class _Response:
    text = """
    <div class=\"result\">
      <a class=\"result__a\" href=\"https://example.org/traits\">Plant functional traits</a>
      <div class=\"result__snippet\">A useful research overview.</div>
    </div>
    """

    def raise_for_status(self):
        return None


def test_public_web_search_forwards_only_compiled_subject(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr(web_search.requests, "get", fake_get)

    result = web_search.search_public_web(
        "请帮我检索植物功能性状相关的研究资料，并总结研究进展与争议",
        limit=3,
    )

    assert calls[0][1]["params"]["q"] == "植物功能性状"
    assert result["query"] == "植物功能性状"
    assert result["search_intent"]["raw_query"].startswith("请帮我检索")
    assert result["count"] == 1
