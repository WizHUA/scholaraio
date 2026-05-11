# Webtools Integration (Optional)

ScholarAIO is agent-first: users talk to an agent, and the agent orchestrates local ScholarAIO skills.  
If you also want live web search/extraction, ScholarAIO can integrate the same backend daemons used by [AnterCreeper/claude-webtools](https://github.com/AnterCreeper/claude-webtools) as an external capability layer.

## When to use this

- You need **internet discovery** (news, latest announcements, online docs) in addition to the local paper KB.
- You want the agent to combine:
  - ScholarAIO local retrieval (`/scholaraio:search`, `/scholaraio:show`, etc.)
  - external web lookup from `GUILessBingSearch` / `qt-web-extractor`.

## Native ScholarAIO entrypoint

ScholarAIO now provides a native URL-ingest command:

```bash
scholaraio ingest-link https://example.com/page
```

This command:

1. Calls a running `qt-web-extractor` service.
2. Pulls rendered page content instead of only raw HTML source.
3. Writes extracted Markdown into a temporary document inbox.
4. Reuses the existing ScholarAIO document ingest pipeline.

In practice, this means `scholaraio ingest-link` can ingest:

- JavaScript-rendered pages that a plain HTTP fetch would miss
- online PDFs and report URLs
- technical docs, manuals, standards, and web articles as normal `document` records

The current command resolves `qt-web-extractor` in this order:

- `config.yaml -> webextract.transport` / `webextract.mcp_url` / `webextract.mcp_tool`
- `config.yaml -> webextract.base_url` / `webextract.api_key`
- `WEBEXTRACT_MCP_URL` / `QT_WEB_EXTRACTOR_MCP_URL`
- `WEBEXTRACT_URL` / `WEBEXTRACT_API_KEY` / `QT_WEB_EXTRACTOR_API_KEY`
- otherwise `http://127.0.0.1:8766`

## Preferred MCP Transports

For agent workflows, prefer the MCP endpoints exposed by the optional webtools
daemons when available. This keeps browser rendering/search state on a local or
remote service and lets agents use the same tools without installing Qt
WebEngine everywhere.

```yaml
websearch:
  transport: mcp
  mcp_url: http://127.0.0.1:8765/mcp
  api_key: your_key     # optional; sent as Bearer auth
  mcp_tool: search_bing # optional; default

webextract:
  transport: mcp
  mcp_url: http://127.0.0.1:8766/mcp
  api_key: your_key   # optional; sent as Bearer auth
  mcp_tool: fetch_url # optional; default
```

If `mcp_url` is omitted, ScholarAIO derives it from the corresponding
`base_url` by appending `/mcp`. The older HTTP paths remain supported:

```yaml
websearch:
  transport: http
  base_url: http://127.0.0.1:8765
  api_key: your_key

webextract:
  transport: http
  base_url: http://127.0.0.1:8766
  api_key: your_key
```

Environment fallbacks are also supported:

- `WEBSEARCH_TRANSPORT`, `WEBSEARCH_MCP_URL`, `GUILESS_BING_SEARCH_MCP_URL`, `WEBSEARCH_API_KEY`, `GUILESS_BING_SEARCH_API_KEY`
- `WEBEXTRACT_TRANSPORT`, `WEBEXTRACT_MCP_URL`, `QT_WEB_EXTRACTOR_MCP_URL`, `WEBEXTRACT_API_KEY`, `QT_WEB_EXTRACTOR_API_KEY`

ScholarAIO's MCP client follows the MCP Streamable HTTP lifecycle:
`initialize` -> `notifications/initialized` -> `tools/list` or `tools/call`.
It sends Bearer auth when configured and honors the protocol version negotiated
by the server.

Protocol references:

- MCP Streamable HTTP transport: <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>
- MCP lifecycle: <https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle>
- MCP tools: <https://modelcontextprotocol.io/specification/2025-11-25/server/tools>

## Agent MCP Registration

You can also expose the same daemon tools directly to MCP-capable agents.
The repository-level `.mcp.json` is an agent-neutral server inventory for hosts
that support that convention. Other agents, including Codex, may need the same
servers registered in their own MCP config store. Do not commit real secrets in
project files.

Generic MCP endpoints:

| Server | URL | Tool |
|--------|-----|------|
| `web-search` | `http://127.0.0.1:8765/mcp` | `search_bing` |
| `web-extractor` | `http://127.0.0.1:8766/mcp` | `fetch_url` |

Claude Code can consume the project `.mcp.json` directly, or register the same
servers with:

```bash
claude mcp add --transport http web-search http://127.0.0.1:8765/mcp
claude mcp add --transport http web-extractor http://127.0.0.1:8766/mcp

claude mcp add --transport http web-search http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer your-search-key"
claude mcp add --transport http web-extractor http://127.0.0.1:8766/mcp \
  --header "Authorization: Bearer your-extractor-key"
```

Codex / OpenAI Codex CLI uses its own MCP registry. Register the same
Streamable HTTP servers with:

```bash
codex mcp add web-search --url http://127.0.0.1:8765/mcp
codex mcp add web-extractor --url http://127.0.0.1:8766/mcp

codex mcp add web-search --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var GUILESS_BING_SEARCH_API_KEY
codex mcp add web-extractor --url http://127.0.0.1:8766/mcp \
  --bearer-token-env-var QT_WEB_EXTRACTOR_API_KEY
```

The equivalent Codex config shape in `~/.codex/config.toml` is:

```toml
[mcp_servers.web-search]
url = "http://127.0.0.1:8765/mcp"

[mcp_servers.web-extractor]
url = "http://127.0.0.1:8766/mcp"
bearer_token_env_var = "QT_WEB_EXTRACTOR_API_KEY"
```

Project-scoped `.mcp.json` example for agents that support it:

```json
{
  "mcpServers": {
    "web-search": {
      "type": "http",
      "url": "${GUILESS_BING_SEARCH_MCP_URL:-http://127.0.0.1:8765/mcp}",
      "headers": {
        "Authorization": "Bearer ${GUILESS_BING_SEARCH_API_KEY:-}"
      }
    },
    "web-extractor": {
      "type": "http",
      "url": "${QT_WEB_EXTRACTOR_MCP_URL:-http://127.0.0.1:8766/mcp}",
      "headers": {
        "Authorization": "Bearer ${QT_WEB_EXTRACTOR_API_KEY:-}"
      }
    }
  }
}
```

Known tool names:

- `GUILessBingSearch`: `search_bing` with `{"query": "...", "count": 5}`
- `qt-web-extractor`: `fetch_url` with `{"url": "https://..."}`

Verification commands:

```bash
claude mcp list
codex mcp list --json
```

## Recommended setup

1. Install and configure the backend services:
   - `qt-web-extractor` for rendered URL/PDF extraction, preferably exposed via MCP
   - optional `GUILessBingSearch` for search-first workflows, preferably exposed via MCP when using agent tooling
2. Keep ScholarAIO as the authoritative local knowledge pipeline (ingest/index/enrich).
3. In agent workflows:
   - use ScholarAIO first for reproducible local evidence;
   - use webtools only when freshness or external coverage is required.

`qt-web-extractor` is an external daemon, not a built-in ScholarAIO fetcher. ScholarAIO delegates browser rendering to that service, through MCP or the legacy HTTP endpoint, and then continues with its own ingest pipeline.

## Operational guidelines

- Prefer local KB evidence for stable academic claims.
- For time-sensitive facts, cross-check via webtools and record access date.
- When webtools is unavailable, agent should degrade gracefully to local-only ScholarAIO workflows.
- Prefer the default automatic URL handling first; use `scholaraio ingest-link --pdf <url>` only when a PDF URL needs an explicit hint.
