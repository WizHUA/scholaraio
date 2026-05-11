"""Tests for scholaraio.providers.webtools HTTP connector helpers."""

from __future__ import annotations

import json

import pytest


class _FakeResponse:
    def __init__(self, payload: object, status: int = 200, headers: dict[str, str] | None = None):
        self._payload = payload
        self.status = status
        self._headers = headers or {}

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def getheader(self, name: str, default: str | None = None) -> str | None:
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestWebtoolsConnector:
    def test_check_webextract_health(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            return _FakeResponse({"status": "ok"})

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import check_webextract_health

        result = check_webextract_health()

        assert result == {"status": "ok"}
        assert seen["url"] == "http://127.0.0.1:8766/health"
        assert seen["method"] == "GET"

    def test_check_websearch_health_uses_env_base_url(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            return _FakeResponse({"status": "ok"})

        monkeypatch.setenv("WEBSEARCH_URL", "http://localhost:9999")
        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import check_websearch_health

        result = check_websearch_health()

        assert result["status"] == "ok"
        assert seen["url"] == "http://localhost:9999/health"

    def test_websearch_posts_query_and_count(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse([{"title": "Example", "link": "https://example.com", "snippet": "snippet"}])

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import websearch

        result = websearch("wall turbulence", count=7)

        assert result[0]["title"] == "Example"
        assert seen["url"] == "http://127.0.0.1:8765/search"
        assert seen["method"] == "POST"
        assert seen["body"] == {"query": "wall turbulence", "count": 7}

    def test_webextract_single_posts_extract_payload(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "url": "https://example.com",
                    "title": "Example Domain",
                    "text": "# Example Domain",
                    "html": "<html></html>",
                    "error": "",
                }
            )

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import webextract

        result = webextract("https://example.com")

        assert result["title"] == "Example Domain"
        assert seen["url"] == "http://127.0.0.1:8766/extract"
        assert seen["method"] == "POST"
        assert seen["body"] == {"url": "https://example.com"}

    def test_webextract_single_includes_pdf_flag_when_set(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "url": "https://example.com/file",
                    "title": "PDF",
                    "text": "body",
                    "html": "",
                    "error": "",
                }
            )

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import webextract

        webextract("https://example.com/file", pdf=True)

        assert seen["body"] == {"url": "https://example.com/file", "pdf": True}

    def test_webextract_batch_posts_open_webui_payload(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(
                [
                    {
                        "page_content": "# Example",
                        "metadata": {"source": "https://example.com", "title": "Example"},
                    }
                ]
            )

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import webextract_batch

        result = webextract_batch(["https://example.com"])

        assert result[0]["metadata"]["title"] == "Example"
        assert seen["url"] == "http://127.0.0.1:8766"
        assert seen["body"] == {"urls": ["https://example.com"]}

    def test_webextract_raises_runtime_error_on_invalid_json(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse("{not-json")

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import webextract

        with pytest.raises(RuntimeError, match="解析响应失败"):
            webextract("https://example.com")

    def test_websearch_includes_bearer_token_when_env_key_is_set(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["auth"] = req.headers.get("Authorization")
            return _FakeResponse([])

        monkeypatch.setenv("WEBSEARCH_API_KEY", "secret-key")
        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import websearch

        websearch("test query")

        assert seen["auth"] == "Bearer secret-key"


class TestWebtoolsEnhancedSearch:
    def test_search_web_uses_cfg_base_url_and_api_key(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            return _FakeResponse([])

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import search_web

        cfg = _build_config(
            {
                "websearch": {
                    "base_url": "http://localhost:9999",
                    "api_key": "cfg-secret",
                }
            },
            tmp_path,
        )

        search_web("query", cfg=cfg)

        assert seen["url"] == "http://localhost:9999/search"
        assert seen["auth"] == "Bearer cfg-secret"

    def test_search_web_returns_websearchresult_list(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse(
                [
                    {"title": "T1", "link": "https://a.com", "snippet": "S1"},
                    {"title": "T2", "link": "https://b.com", "snippet": "S2"},
                ]
            )

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import search_web

        results = search_web("query")

        assert len(results) == 2
        assert results[0].title == "T1"
        assert results[0].link == "https://a.com"
        assert results[0].snippet == "S1"

    def test_search_web_mcp_transport_calls_search_bing_with_cfg_auth(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            seen.setdefault("methods", []).append(body["method"])
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            if body["method"] == "tools/call":
                seen["body"] = body
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "content": [{"type": "text", "text": "1. [Title](https://example.com)"}],
                            "structuredContent": {
                                "query": "query",
                                "count": 3,
                                "results": [
                                    {
                                        "title": "Title",
                                        "link": "https://example.com",
                                        "snippet": "Snippet",
                                    }
                                ],
                            },
                            "isError": False,
                        },
                    }
                )
            raise AssertionError(f"unexpected method: {body['method']}")

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import search_web

        cfg = _build_config(
            {
                "websearch": {
                    "transport": "mcp",
                    "mcp_url": "http://remote.example:8765/mcp",
                    "api_key": "cfg-secret",
                }
            },
            tmp_path,
        )

        results = search_web("query", count=3, cfg=cfg)

        assert seen["url"] == "http://remote.example:8765/mcp"
        assert seen["auth"] == "Bearer cfg-secret"
        assert seen["methods"] == ["initialize", "notifications/initialized", "tools/call"]
        assert seen["body"]["params"] == {"name": "search_bing", "arguments": {"query": "query", "count": 3}}
        assert len(results) == 1
        assert results[0].title == "Title"
        assert results[0].link == "https://example.com"
        assert results[0].snippet == "Snippet"

    def test_search_web_mcp_transport_env_overrides_empty_config(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            seen["url"] = req.full_url
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"structuredContent": {"results": []}, "isError": False},
                }
            )

        monkeypatch.setenv("WEBSEARCH_TRANSPORT", "mcp")
        monkeypatch.setenv("WEBSEARCH_MCP_URL", "http://env.example:8765/mcp")
        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import search_web

        search_web("query", cfg=_build_config({}, tmp_path))

        assert seen["url"] == "http://env.example:8765/mcp"

    def test_search_web_raises_service_unavailable_on_health_failure(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            raise OSError("connection refused")

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import ServiceUnavailableError, search_web

        with pytest.raises(ServiceUnavailableError):
            search_web("query")

    def test_search_and_display_prints_results(self, monkeypatch, capsys):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse([{"title": "T", "link": "https://x.com", "snippet": "S"}])

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import search_and_display

        results = search_and_display("q", count=1)

        assert len(results) == 1
        captured = capsys.readouterr()
        assert "T" in captured.out
        assert "https://x.com" in captured.out

    def test_search_and_display_propagates_service_unavailable(self, monkeypatch):
        from scholaraio.providers.webtools import ServiceUnavailableError, search_and_display

        def fake_search_web(*args, **kwargs):
            raise ServiceUnavailableError("service down")

        monkeypatch.setattr("scholaraio.providers.webtools.search_web", fake_search_web)

        with pytest.raises(ServiceUnavailableError, match="service down"):
            search_and_display("q")

    def test_search_and_fetch_arxiv_filters_results(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse(
                [
                    {"title": "ArXiv", "link": "https://arxiv.org/abs/2301.12345", "snippet": "s"},
                    {"title": "Other", "link": "https://example.com", "snippet": "s"},
                ]
            )

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import search_and_fetch_arxiv

        papers = search_and_fetch_arxiv("q")

        assert len(papers) == 1
        assert papers[0]["arxiv_id"] == "2301.12345"


class TestWebtoolsEnhancedExtract:
    def test_extract_web_returns_dict(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse({"title": "Page", "text": "body"})

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import extract_web

        result = extract_web("https://example.com")

        assert result["title"] == "Page"
        assert result["text"] == "body"

    def test_extract_web_mcp_transport_calls_fetch_url_with_cfg_auth(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            seen.setdefault("methods", []).append(body["method"])
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
                    },
                    headers={"Mcp-Session-Id": "session-123"},
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=202)
            if body["method"] == "tools/call":
                seen["body"] = body
                seen["session"] = req.get_header("Mcp-Session-Id") or dict(req.header_items()).get("Mcp-session-id")
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"content": [{"type": "text", "text": "# Page\n\nRendered body"}]},
                    }
                )
            raise AssertionError(f"unexpected method: {body['method']}")

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import extract_web

        cfg = _build_config(
            {
                "webextract": {
                    "transport": "mcp",
                    "mcp_url": "http://remote.example/mcp",
                    "api_key": "cfg-secret",
                }
            },
            tmp_path,
        )

        result = extract_web("https://example.com", cfg=cfg)

        assert seen["url"] == "http://remote.example/mcp"
        assert seen["auth"] == "Bearer cfg-secret"
        assert seen["methods"] == ["initialize", "notifications/initialized", "tools/call"]
        assert seen["session"] == "session-123"
        assert seen["body"]["method"] == "tools/call"
        assert seen["body"]["params"] == {"name": "fetch_url", "arguments": {"url": "https://example.com"}}
        assert result["title"] == "Page"
        assert result["text"] == "# Page\n\nRendered body"

    def test_extract_web_mcp_transport_derives_url_from_base_url(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            body = json.loads(req.data.decode("utf-8"))
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=202)
            return _FakeResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import extract_web

        cfg = _build_config(
            {"webextract": {"transport": "mcp", "base_url": "http://remote.example:8766/"}},
            tmp_path,
        )

        extract_web("https://example.com", cfg=cfg)

        assert seen["url"] == "http://remote.example:8766/mcp"

    def test_extract_web_mcp_transport_reads_structured_markdown(self, monkeypatch, tmp_path):
        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [{"type": "text", "text": "# Page\n\nfallback body"}],
                        "structuredContent": {
                            "url": "https://example.com",
                            "title": "Structured Page",
                            "markdown": "# Structured Page\n\nstructured body",
                            "error": "",
                        },
                        "isError": False,
                    },
                }
            )

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import extract_web

        cfg = _build_config({"webextract": {"transport": "mcp"}}, tmp_path)

        result = extract_web("https://example.com", cfg=cfg)

        assert result["title"] == "Structured Page"
        assert result["text"] == "# Structured Page\n\nstructured body"

    def test_extract_web_mcp_transport_preserves_structured_html(self, monkeypatch, tmp_path):
        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "structuredContent": {
                            "title": "Image Page",
                            "markdown": "# Image Page\n\nbody",
                            "html": "<main><img src='/figure.png'></main>",
                        },
                        "isError": False,
                    },
                }
            )

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import extract_web

        cfg = _build_config({"webextract": {"transport": "mcp"}}, tmp_path)

        result = extract_web("https://example.com", cfg=cfg, include_html=True)

        assert result["html"] == "<main><img src='/figure.png'></main>"

    def test_extract_web_mcp_transport_env_overrides_empty_config(self, monkeypatch, tmp_path):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            seen["url"] = req.full_url
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            return _FakeResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})

        monkeypatch.setenv("WEBEXTRACT_TRANSPORT", "mcp")
        monkeypatch.setenv("WEBEXTRACT_MCP_URL", "http://env.example:8766/mcp")
        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import extract_web

        extract_web("https://example.com", cfg=_build_config({}, tmp_path))

        assert seen["url"] == "http://env.example:8766/mcp"

    def test_extract_web_mcp_transport_raises_on_jsonrpc_error(self, monkeypatch, tmp_path):
        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=202)
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32000, "message": "tool failed"},
                }
            )

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import WebExtractError, extract_web

        cfg = _build_config({"webextract": {"transport": "mcp"}}, tmp_path)

        with pytest.raises(WebExtractError, match="tool failed"):
            extract_web("https://example.com", cfg=cfg)

    def test_extract_web_mcp_transport_uses_structured_error_text(self, monkeypatch, tmp_path):
        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [],
                        "structuredContent": {
                            "url": "https://example.com",
                            "title": "",
                            "markdown": "",
                            "error": "remote extractor failure",
                        },
                        "isError": True,
                    },
                }
            )

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import WebExtractError, extract_web

        cfg = _build_config({"webextract": {"transport": "mcp"}}, tmp_path)

        with pytest.raises(WebExtractError, match="remote extractor failure"):
            extract_web("https://example.com", cfg=cfg)

    def test_extract_web_mcp_transport_preserves_structured_warning(self, monkeypatch, tmp_path):
        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            if body["method"] == "initialize":
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
                    }
                )
            if body["method"] == "notifications/initialized":
                return _FakeResponse("", status=204)
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "structuredContent": {
                            "title": "Partial Page",
                            "markdown": "# Partial Page\n\npartial body",
                            "error": "some resources failed",
                        },
                        "isError": False,
                    },
                }
            )

        monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

        from scholaraio.core.config import _build_config
        from scholaraio.providers.webtools import extract_web

        cfg = _build_config({"webextract": {"transport": "mcp"}}, tmp_path)

        result = extract_web("https://example.com", cfg=cfg)

        assert result["title"] == "Partial Page"
        assert result["text"] == "# Partial Page\n\npartial body\n\n[warning] some resources failed"

    def test_extract_web_raises_on_service_unavailable(self, monkeypatch):
        def fake_urlopen(req, timeout=0):
            raise OSError("refused")

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import WebExtractServiceUnavailableError, extract_web

        with pytest.raises(WebExtractServiceUnavailableError):
            extract_web("https://example.com")

    def test_extract_and_display_prints_text(self, monkeypatch, capsys):
        def fake_urlopen(req, timeout=0):
            return _FakeResponse({"title": "Page", "text": "markdown body"})

        monkeypatch.setattr("scholaraio.providers.webtools.urlopen", fake_urlopen)

        from scholaraio.providers.webtools import extract_and_display

        result = extract_and_display("https://example.com")

        assert result is not None
        assert result["title"] == "Page"
        captured = capsys.readouterr()
        assert "markdown body" in captured.out
