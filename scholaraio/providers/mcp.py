"""Generic MCP Streamable HTTP client helpers."""

from __future__ import annotations

import json
from itertools import count
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scholaraio import __version__

MCP_PROTOCOL_VERSION = "2025-11-25"


class McpError(RuntimeError):
    """Base class for MCP client failures."""


class McpTransportError(McpError):
    """Raised when the MCP endpoint cannot be reached or decoded."""


class McpProtocolError(McpError):
    """Raised when a JSON-RPC or MCP protocol error is returned."""


class StreamableHttpMcpClient:
    """Small MCP Streamable HTTP client for server tool calls.

    The client implements the current stable MCP lifecycle for the subset
    ScholarAIO needs: initialize, initialized notification, tools/list, and
    tools/call. It intentionally stays transport-level and does not model
    agent UI permission flows.
    """

    def __init__(
        self,
        endpoint_url: str,
        *,
        api_key: str = "",
        client_name: str = "scholaraio",
        client_version: str = __version__,
        protocol_version: str = MCP_PROTOCOL_VERSION,
        timeout: int = 120,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key.strip()
        self.client_name = client_name
        self.client_version = client_version
        self.protocol_version = protocol_version
        self.timeout = timeout
        self.session_id = ""
        self._initialized = False
        self._ids = count(1)

    def initialize(self) -> dict[str, Any]:
        """Run MCP lifecycle initialization if it has not already completed."""
        if self._initialized:
            return {}

        result = self.request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_name,
                    "version": self.client_version,
                },
            },
            ensure_initialized=False,
        )
        negotiated = result.get("protocolVersion")
        if isinstance(negotiated, str) and negotiated:
            self.protocol_version = negotiated

        self.request(
            "notifications/initialized",
            expect_response=False,
            ensure_initialized=False,
        )
        self._initialized = True
        return result

    def list_tools(self, *, cursor: str | None = None) -> dict[str, Any]:
        """Return tools exposed by the MCP server."""
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        return self.request("tools/list", params)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a server tool and return the MCP tool result."""
        return self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        expect_response: bool = True,
        ensure_initialized: bool = True,
    ) -> dict[str, Any]:
        """Send one JSON-RPC request or notification to the MCP endpoint."""
        if ensure_initialized and not self._initialized:
            self.initialize()

        request_id: int | None = None
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if expect_response:
            request_id = next(self._ids)
            payload["id"] = request_id
        if params is not None:
            payload["params"] = params

        response = self._post_json(payload, expect_response=expect_response, request_id=request_id)
        if not expect_response:
            return {}

        error = response.get("error")
        if error:
            if isinstance(error, dict):
                message = str(error.get("message") or error)
            else:
                message = str(error)
            raise McpProtocolError(message)

        result = response.get("result")
        if isinstance(result, dict):
            return result
        if result is None:
            return {}
        raise McpProtocolError(f"Unexpected MCP result type: {type(result).__name__}")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol_version,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post_json(
        self,
        payload: dict[str, Any],
        *,
        expect_response: bool,
        request_id: int | None,
    ) -> dict[str, Any]:
        req = Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as response:
                session_id = _response_header(response, "Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                raw = response.read().decode("utf-8", errors="replace")
                content_type = _response_header(response, "Content-Type") or ""
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise McpTransportError(f"MCP HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise McpTransportError(f"Cannot connect to MCP endpoint: {exc.reason}") from exc

        if not raw.strip():
            if expect_response:
                raise McpTransportError("MCP response body is empty")
            return {}

        if "text/event-stream" in content_type.lower():
            return _parse_sse_json_response(raw, request_id=request_id)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpTransportError(f"Cannot decode MCP JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise McpTransportError("MCP response must be a JSON object")
        return data


def call_streamable_http_tool(
    endpoint_url: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    api_key: str = "",
    timeout: int = 120,
) -> dict[str, Any]:
    """Convenience wrapper for a one-shot MCP Streamable HTTP tool call."""
    client = StreamableHttpMcpClient(endpoint_url, api_key=api_key, timeout=timeout)
    return client.call_tool(name, arguments or {})


def _response_header(response: object, name: str) -> str | None:
    getter = getattr(response, "getheader", None)
    if callable(getter):
        value = getter(name)
        if value:
            return str(value)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get(name)
        if value:
            return str(value)
    return None


def _parse_sse_json_response(raw: str, *, request_id: int | None) -> dict[str, Any]:
    event_data: list[str] = []
    candidates: list[dict[str, Any]] = []

    def flush_event() -> None:
        if not event_data:
            return
        data = "\n".join(event_data).strip()
        event_data.clear()
        if not data:
            return
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(decoded, dict):
            candidates.append(decoded)

    for line in raw.splitlines():
        if not line.strip():
            flush_event()
            continue
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())
    flush_event()

    if request_id is not None:
        for candidate in candidates:
            if candidate.get("id") == request_id:
                return candidate
    if candidates:
        return candidates[-1]
    raise McpTransportError("MCP SSE response did not contain a JSON-RPC message")
