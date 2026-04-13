# Configuration

ScholarAIO uses two config files:

| File | Tracked | Purpose |
|------|---------|---------|
| `config.yaml` | Yes | Default settings |
| `config.local.yaml` | No (git-ignored) | API keys and local overrides |

## API Keys

LLM API key lookup order:

1. `config.local.yaml` → `llm.api_key`
2. Environment variable `SCHOLARAIO_LLM_API_KEY`
3. Backend-specific environment variables, based on `llm.backend`:
   - `openai-compat`: `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`
   - `anthropic`: `ANTHROPIC_API_KEY`
   - `google`: `GOOGLE_API_KEY` → `GEMINI_API_KEY`

### Example `config.local.yaml`

```yaml
llm:
  api_key: "sk-your-key-here"

ingest:
  mineru_api_key: "your-mineru-token"  # compatibility alias; MINERU_TOKEN is preferred
  s2_api_key: "your-semantic-scholar-key"  # optional

zotero:
  api_key: "your-zotero-key"  # optional
  library_id: "1234567"  # optional
```

You can also keep the token out of YAML entirely and set `MINERU_TOKEN` in the environment. `MINERU_API_KEY` is still accepted as a compatibility alias.

## Key Settings

### LLM Backend

Default: DeepSeek (`deepseek-chat`) via OpenAI-compatible protocol.

```yaml
llm:
  model: deepseek-chat
  base_url: https://api.deepseek.com
```

### Metadata Extraction

```yaml
ingest:
  extractor: robust  # regex + LLM (default)
  # Other options: auto, regex, llm
```

### Embedding Source

```yaml
embed:
  source: modelscope  # default (China)
  # source: huggingface  # for international users
```
