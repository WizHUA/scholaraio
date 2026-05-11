"""Tests for the generic MCP Streamable HTTP provider."""

from __future__ import annotations

import json

import pytest


class _FakeResponse:
    def __init__(self, payload: object, *, status: int = 200, headers: dict[str, str] | None = None):
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


def _header(req, name: str) -> str | None:
    value = req.get_header(name)
    if value is not None:
        return value
    for key, header_value in req.header_items():
        if key.lower() == name.lower():
            return header_value
    return None


def test_streamable_http_client_initializes_and_calls_tool_with_session_headers(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(
            {
                "url": req.full_url,
                "method": body["method"],
                "body": body,
                "auth": _header(req, "Authorization"),
                "accept": _header(req, "Accept"),
                "protocol": _header(req, "MCP-Protocol-Version"),
                "session": _header(req, "Mcp-Session-Id"),
            }
        )
        if body["method"] == "initialize":
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-mcp", "version": "1.0"},
                    },
                },
                headers={"Mcp-Session-Id": "session-123"},
            )
        if body["method"] == "notifications/initialized":
            return _FakeResponse("", status=202)
        if body["method"] == "tools/call":
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"content": [{"type": "text", "text": "rendered"}], "isError": False},
                }
            )
        raise AssertionError(f"unexpected method: {body['method']}")

    monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

    from scholaraio.providers.mcp import StreamableHttpMcpClient

    client = StreamableHttpMcpClient("http://127.0.0.1:8766/mcp", api_key="secret")
    result = client.call_tool("fetch_url", {"url": "https://example.com"})

    assert [call["method"] for call in calls] == ["initialize", "notifications/initialized", "tools/call"]
    assert calls[0]["session"] is None
    assert calls[2]["session"] == "session-123"
    assert calls[2]["body"]["params"] == {"name": "fetch_url", "arguments": {"url": "https://example.com"}}
    assert all(call["url"] == "http://127.0.0.1:8766/mcp" for call in calls)
    assert all(call["auth"] == "Bearer secret" for call in calls)
    assert all(call["accept"] == "application/json, text/event-stream" for call in calls)
    assert calls[0]["protocol"] == "2025-11-25"
    assert calls[1]["protocol"] == "2025-06-18"
    assert calls[2]["protocol"] == "2025-06-18"
    assert result == {"content": [{"type": "text", "text": "rendered"}], "isError": False}


def test_streamable_http_client_lists_tools_from_sse_response(monkeypatch):
    calls: list[str] = []

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(body["method"])
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
        if body["method"] == "tools/list":
            data = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"tools": [{"name": "fetch_url", "inputSchema": {"type": "object"}}]},
                }
            )
            return _FakeResponse(f"event: message\ndata: {data}\n\n", headers={"Content-Type": "text/event-stream"})
        raise AssertionError(f"unexpected method: {body['method']}")

    monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

    from scholaraio.providers.mcp import StreamableHttpMcpClient

    client = StreamableHttpMcpClient("http://127.0.0.1:8766/mcp")
    result = client.list_tools()

    assert calls == ["initialize", "notifications/initialized", "tools/list"]
    assert result["tools"][0]["name"] == "fetch_url"


def test_streamable_http_client_raises_jsonrpc_error(monkeypatch):
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
        if body["method"] == "tools/call":
            return _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32602, "message": "invalid tool arguments"},
                }
            )
        raise AssertionError(f"unexpected method: {body['method']}")

    monkeypatch.setattr("scholaraio.providers.mcp.urlopen", fake_urlopen)

    from scholaraio.providers.mcp import McpProtocolError, StreamableHttpMcpClient

    client = StreamableHttpMcpClient("http://127.0.0.1:8766/mcp")

    with pytest.raises(McpProtocolError, match="invalid tool arguments"):
        client.call_tool("fetch_url", {"url": "https://example.com"})
