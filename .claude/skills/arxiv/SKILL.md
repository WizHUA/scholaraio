---
name: arxiv
description: Use when the user wants to browse arXiv preprints, search arXiv directly, fetch a PDF by arXiv ID or URL, or send a preprint into the ScholarAIO ingest pipeline.
---

# arXiv Preprints

Use this skill when the task is specifically about arXiv as a source of preprints.

This is a thin source-workflow skill:

- `search` skill handles overall paper-search routing
- `arxiv` skill handles preprint discovery, browsing, fetching, and optional ingest

## When to Use

Use this skill when the user wants to:

- browse recent or category-scoped preprints
- "随便看看" arXiv 上某个方向最近有什么
- search arXiv directly instead of only searching the local library
- fetch a paper from an arXiv ID, `abs` URL, or `pdf` URL
- download a preprint into the configured paper inbox (fresh default: `data/spool/inbox/`)
- send an arXiv preprint directly into the ingest pipeline

Do not use this skill when:

- the task is mainly about searching the local knowledge base
- the user wants a full multi-source literature survey; use `search` or `explore`

## Core Workflow

### 1. Decide whether this is browse/search or fetch/ingest

- If the user wants to look around, discover preprints, or check what is new, start with `arxiv search`
- If the user wants cross-source retrieval with the local library, use `fsearch --scope main,arxiv`
- If the user already has a specific arXiv paper in mind, use `arxiv fetch`
- If the goal is "put this preprint into my library now", use `arxiv fetch <id> --ingest`

### 2. Use the right command

Direct arXiv search:

```bash
scholaraio arxiv search "<query>"
scholaraio arxiv search "<query>" --category physics.flu-dyn
scholaraio arxiv search --category cs.LG --sort recent
```

Federated search when arXiv should complement the local library:

```bash
scholaraio fsearch "<query>" --scope main,arxiv
scholaraio fsearch "<query>" --scope arxiv
```

Fetch PDF only:

```bash
scholaraio arxiv fetch 2603.25200
scholaraio arxiv fetch arXiv:2603.25200v1
scholaraio arxiv fetch https://arxiv.org/abs/2603.25200v1
```

Fetch and ingest immediately:

```bash
scholaraio arxiv fetch 2603.25200 --ingest
```

### 3. Keep the source semantics clear

- arXiv is a preprint source, not the main curated knowledge base
- Use it to discover fresh work quickly or pull in a specific preprint
- If the paper becomes relevant to the user's ongoing work, ingest it instead of repeatedly treating it as an external result

## Practical Heuristics

- If the user says "也搜一下 arXiv", prefer `fsearch --scope main,arxiv`
- If the user says "看看最近有什么预印本", prefer `arxiv search --sort recent`
- If the user gives an arXiv ID or URL, do not start with broad search; go straight to `arxiv fetch`
- If the user is clearly collecting papers for continued reading or writing, prefer `--ingest`

## Output Style

- Make it clear when results come from arXiv rather than the local library
- When using federated search, distinguish local hits from arXiv-only hits
- When fetching without ingest, mention that the PDF now sits in the configured paper inbox (fresh default: `data/spool/inbox/`)
- When fetching with ingest, mention that the paper has been sent into the normal ingest flow
