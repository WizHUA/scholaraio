# Search & Browse

ScholarAIO provides multiple search modes to find papers in your knowledge base.

## Search Modes

### Keyword Search (FTS5)

```bash
scholaraio search "turbulent boundary layer"
```

Searches title, abstract, and conclusion using SQLite FTS5 full-text search.

### Semantic Search

```bash
scholaraio vsearch "methods for predicting flow separation"
```

Uses Qwen3 embeddings + FAISS for meaning-based retrieval.

### Unified Search (Fusion)

```bash
scholaraio usearch "Reynolds stress modeling"
```

Combines keyword and semantic results using Reciprocal Rank Fusion (RRF).

### Federated Search

```bash
scholaraio fsearch "wall turbulence" --scope main,proceedings,explore:*,arxiv
```

Searches across the main library, proceedings, one or more `explore` silos, and arXiv in one command.

### Author Search

```bash
scholaraio search-author "Smith"
```

## Viewing Papers

Load paper content at different detail levels:

```bash
scholaraio show <paper-id> --layer 1  # metadata
scholaraio show <paper-id> --layer 2  # + abstract
scholaraio show <paper-id> --layer 3  # + conclusion
scholaraio show <paper-id> --layer 4  # full text
```

## Filtering

All search commands support filters:

```bash
scholaraio search "turbulence" --year 2020-2024 --journal "JFM" --type review
```

## Top-Cited Papers

```bash
scholaraio top-cited --top 20 --year 2020-
```

## arXiv Search and Fetch

```bash
scholaraio arxiv search "compliant wall turbulence" --category physics.flu-dyn
scholaraio arxiv fetch 2604.00484 --ingest
```

Use `arxiv search` to discover preprints and `arxiv fetch` to download a PDF or send it directly into the ingest pipeline.

## Scientific Tool Documentation

```bash
scholaraio toolref search openfoam "y plus"
scholaraio toolref show qe pw conv_thr
```

Use `toolref` when you need authoritative parameter or command documentation for supported scientific tools.
