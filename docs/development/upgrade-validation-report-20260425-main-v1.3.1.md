# ScholarAIO Main / v1.3.1 Coverage Validation Report

Status: Passed with one code fix committed in this validation cycle

Date: 2026-04-25

Validation root: `workspace/release-validation/20260425-main-v1.3.1/`

Evidence bundle: `workspace/release-validation/20260425-main-v1.3.1/evidence/`

## 1. Purpose

This report validates that the current `breaking-compat-cleanup` branch covers the
published `v1.3.1` command surface and the latest fetched `origin/main` feature
surface, including the recent merged PR batch on `main`.

This is intentionally not just a unit-test record. The run includes disposable
fresh-layout CLI canaries, real-root CLI canaries, online provider canaries,
webtools canaries, and an old-layout one-command migration rehearsal.

## 2. Baselines

Git refs captured after `git fetch --all --prune --tags`:

- `HEAD`: `6ad4b22b0fb687d3310769312dccf730cc00f2d2`
- `origin/main`: `81f0ef295ed839f9b5367267e1b0bdee47716a51`
- `v1.3.1^{commit}`: `7e4ab3758c34e1864805734f61249d1c0e31096d`

Ancestry checks:

- `origin/main` is an ancestor of `HEAD`: yes (`origin-main-ancestor-of-head.status = 0`)
- `v1.3.1` is an ancestor of `HEAD`: yes (`v1.3.1-ancestor-of-head.status = 0`)
- `HEAD...origin/main`: `196  0`, meaning current branch is ahead of fetched `origin/main` and not behind it
- `v1.3.1...HEAD`: `0  261`, meaning current branch contains the release tag and 261 later commits

Command-surface comparison:

- `v1.3.1` top-level commands: 37
- current top-level commands: 45
- commands present in `v1.3.1` but missing in current: none
- commands added after `v1.3.1`: `backup`, `diagram`, `ingest-link`, `migrate`, `patent-fetch`, `patent-search`, `webextract`, `websearch`

Evidence:

- `current-help.txt`
- `v1.3.1-help.txt`
- `current-commands.sorted.txt`
- `v1.3.1-commands.sorted.txt`
- `commands-missing-from-current.txt`
- `commands-added-after-v1.3.1.txt`

## 3. GitHub / Main PR Cross-Check

Local `gh pr list` was attempted but the local GitHub CLI credential is invalid:

- status: `1`
- error: `HTTP 401: Bad credentials`
- evidence: `gh-pr-list-attempt.status`, `gh-pr-list-attempt.err`

The PR cross-check therefore used two independent sources:

- fetched `origin/main` merge/non-merge logs
- GitHub connector search for merged PR metadata

Recent main features and validation mapping:

| Source | Feature | Evidence |
| --- | --- | --- |
| PR #73 / `981f554` | Patent search/fetch toolchain | `current_patent_search.log`, `fresh_patent_fetch.log` |
| PR #74 / `1f4e67a` and follow-ups | `websearch`, `webextract`, webtools CLI | `current_websearch.log`, `current_webextract.log` |
| PR #69 / `bcea13a` | `ingest-link` rendered web ingestion | `fresh_ingest_link.log` |
| PR #68 / `6492bac` | rsync backup workflow | `fresh_backup_list.log`, `fresh_backup_dry_run.log` |
| PR #70 / `8a72747` | FAISS semantic/unified search hardening | `current_vsearch.log`, `current_usearch.log`, `current_fsearch_main.log` |
| PR #66 / `9d0f3a7` | scrub/repair/audit metadata workflow | `fresh_audit.log`, `fresh_repair_dry_run.log`, skill inventory |
| PR #67 / `4716f2e` | academic-writing skill stack | `skill-entrypoints.txt`, full test suite |
| PR #63 / `2984632` | embedding defaults and disabled-topic CLI handling | `current_vsearch.log`, `current_usearch.log`, full test suite |
| PR #71 / `53a3a8c` | pipeline dedup/API retry hardening | `fresh_pipeline_list.log`, `fresh_pipeline_dry_run.log`, full test suite |
| PR #72 / `4ae38bd` | paper-to-diagram pipeline | `fresh_diagram_from_ir.log` |
| PR #76 / `3e5f807` | enhanced arXiv module | `current_arxiv_search.log` |
| PR #83 / `b4c2de6` | paper-guided-reading skill | `skill-entrypoints.txt`, full test suite |
| PR #84 / `18fa43a` | OpenAlex API-key config support | `fresh_explore_fetch_openalex.log`, `current_explore_search.log` |
| PR #62 / `8881b82` | Qwen / multi-agent skill discovery | `skill-entrypoints.txt`, full test suite |

Evidence:

- `origin-main-recent-merge-commits.tsv`
- `origin-main-since-v1.3.1-nonmerge.tsv`
- `skill-entrypoints.txt`

## 4. CLI Canary Summary

Actual CLI canaries:

- total: 67
- passed: 67
- failed: 0

The runner logs exact commands, working directories, timestamps, stdout/stderr,
and `exit_code` for each case.

Primary status table: `cli-canary-results.tsv`

Representative coverage:

- fresh-layout read/write: setup, migrate status, index rebuild, search, show, notes, refs, workspaces
- exports: BibTeX, RIS, Markdown with custom style, DOCX
- document tooling: DOCX inspect
- quality workflows: citation-check, audit, repair dry-run, rename dry-run, abstract backfill dry-run
- ingest/import: pipeline dry-run, EndNote/RIS dry-run, attach-pdf dry-run, ingest-link real webpage ingestion
- metrics/insights: summary and behavior analytics
- diagram: IR to Mermaid output
- LLM-backed commands: `enrich-toc`, `enrich-l3`, `translate`
- online/provider commands: arXiv search, OpenAlex fetch, USPTO search, patent PDF fetch
- webtools: local GUILessBingSearch and qt-web-extractor services, exercised through CLI
- real-root retrieval: keyword search, semantic search, unified search, federated search, topics, explore, toolref

## 5. Migration Rehearsal

A disposable legacy root was created with old-layout stores:

- `data/papers/`
- `data/citation_styles/`
- `data/inbox/`
- `workspace/<name>/papers.json`

Command:

```bash
python -m scholaraio.cli migrate upgrade --migration-id validation-legacy-upgrade-20260425 --confirm
```

Result:

- `source_layout_version: 0`
- `target_layout_version: 1`
- `store_run_count: 4`
- stores: `workspace`, `citation_styles`, `spool`, `papers`
- `finalize_status: completed`
- `cleanup_status: completed_archived`
- `verify_after_cleanup: passed`

Follow-up verify:

- `status: passed`
- `checks: 18/18 passed`

Evidence:

- `legacy-migrate-upgrade.log`
- `legacy-migrate-verify.log`
- `legacy-post-layout-dirs.txt`

## 6. Bug Found And Fixed During Validation

The fresh canary initially found a real compatibility bug:

- symptom: `show` crashed when `meta.json` used legacy-style integer `citation_count`
- root cause: `_format_citations()` assumed citation counts were always dicts
- fix: `_format_citations()` now accepts legacy scalar citation counts and formats them directly
- regression test: `TestSearchResultFormatting.test_format_citations_accepts_legacy_integer_count`

This bug was not hidden by changing the fixture; it was fixed in code and then
the full CLI canary was rerun.

## 7. One-By-One CLI Evidence Index

| ID | Status | Evidence |
| --- | --- | --- |
| `fresh_setup_check` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_setup_check.log` |
| `fresh_migrate_status` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_migrate_status.log` |
| `fresh_index_rebuild` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_index_rebuild.log` |
| `fresh_search_keyword` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_search_keyword.log` |
| `fresh_search_author` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_search_author.log` |
| `fresh_show_l1` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_show_l1.log` |
| `fresh_show_l2` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_show_l2.log` |
| `fresh_show_l4` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_show_l4.log` |
| `fresh_show_translated` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_show_translated.log` |
| `fresh_append_notes` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_append_notes.log` |
| `fresh_top_cited` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_top_cited.log` |
| `fresh_refs` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_refs.log` |
| `fresh_citing` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_citing.log` |
| `fresh_shared_refs` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_shared_refs.log` |
| `fresh_ws_init` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_init.log` |
| `fresh_ws_add` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_add.log` |
| `fresh_ws_list` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_list.log` |
| `fresh_ws_show` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_show.log` |
| `fresh_ws_search` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_search.log` |
| `fresh_ws_export` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_export.log` |
| `fresh_ws_rename` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_rename.log` |
| `fresh_ws_remove` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ws_remove.log` |
| `fresh_export_bibtex` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_export_bibtex.log` |
| `fresh_export_ris` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_export_ris.log` |
| `fresh_export_markdown` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_export_markdown.log` |
| `fresh_export_docx` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_export_docx.log` |
| `fresh_document_inspect` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_document_inspect.log` |
| `fresh_style_list` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_style_list.log` |
| `fresh_style_show` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_style_show.log` |
| `fresh_citation_check` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_citation_check.log` |
| `fresh_audit` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_audit.log` |
| `fresh_repair_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_repair_dry_run.log` |
| `fresh_rename_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_rename_dry_run.log` |
| `fresh_backfill_abstract_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_backfill_abstract_dry_run.log` |
| `fresh_pipeline_list` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_pipeline_list.log` |
| `fresh_pipeline_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_pipeline_dry_run.log` |
| `fresh_import_endnote_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_import_endnote_dry_run.log` |
| `fresh_attach_pdf_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_attach_pdf_dry_run.log` |
| `fresh_metrics_summary` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_metrics_summary.log` |
| `fresh_insights` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_insights.log` |
| `fresh_diagram_from_ir` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_diagram_from_ir.log` |
| `fresh_enrich_toc` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_enrich_toc.log` |
| `fresh_enrich_l3` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_enrich_l3.log` |
| `fresh_translate` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_translate.log` |
| `fresh_ingest_link` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_ingest_link.log` |
| `fresh_patent_fetch` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_patent_fetch.log` |
| `fresh_backup_list` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_backup_list.log` |
| `fresh_backup_dry_run` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_backup_dry_run.log` |
| `current_setup_check` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_setup_check.log` |
| `current_search_keyword` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_search_keyword.log` |
| `current_vsearch` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_vsearch.log` |
| `current_usearch` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_usearch.log` |
| `current_fsearch_main` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_fsearch_main.log` |
| `current_topics_overview` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_topics_overview.log` |
| `current_explore_list` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_explore_list.log` |
| `current_explore_info` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_explore_info.log` |
| `current_explore_search` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_explore_search.log` |
| `current_toolref_list` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_toolref_list.log` |
| `current_toolref_search` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_toolref_search.log` |
| `current_toolref_show` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_toolref_show.log` |
| `current_arxiv_search` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_arxiv_search.log` |
| `current_websearch` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_websearch.log` |
| `current_webextract` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_webextract.log` |
| `current_patent_search` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_patent_search.log` |
| `current_migrate_status` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_migrate_status.log` |
| `current_migrate_verify` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/current_migrate_verify.log` |
| `fresh_explore_fetch_openalex` | `0` | `workspace/release-validation/20260425-main-v1.3.1/evidence/fresh_explore_fetch_openalex.log` |

## 8. Final Determination

For the `v1.3.1` release baseline and fetched `origin/main` feature set, the
current branch preserves the old command surface, includes later main features,
and passes the real CLI canary matrix above.

This report does not claim that every possible option permutation of every
command was exhaustively fuzzed. It does claim that each user-facing command
family and each recent main feature family was exercised through at least one
real behavioral CLI path, with logs and exit codes retained for review.
