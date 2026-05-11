# Upgrade Validation Report (2026-04-24)

## Scope

This report records the **real-data migration** from `../scholaraio/` into the current
`develop` workspace plus the follow-up **real CLI validation** run on:

- the migrated real root at `/home/lzmo/repos/personal/scholaraio-develop`
- a seeded scratch root at
  `workspace/release-validation/20260424-real-data-validation/writeflows-root`

It also records the later **breaking cleanup finalization** run on branch
`breaking-compat-cleanup`, where the migrated real root was converted from the
compatibility-window runtime into the fresh-layout-only runtime.

The scratch root was used for mutation-heavy commands so the primary migrated library
could remain stable while still exercising the actual CLI.

## Migration Summary

- Source root copied from `../scholaraio/`
- Pre-import backup created at:
  `/home/lzmo/repos/personal/scholaraio-develop-backups/20260424-pre-import`
- Formal migration journal:
  `.scholaraio-control/migrations/formal-20260424/`
- `migrate plan` completed with:
  - `papers: 702`
  - `workspace: 26`
  - `planned_legacy_moves: 10`
- `migrate run` completed for all supported stores:
  - `citation_styles`
  - `toolref`
  - `proceedings`
  - `spool`
  - `papers`
  - `explore`
- `migrate verify` passed after fixing a real false-negative in
  `keyword_search_accessible`
- `migrate cleanup --confirm` completed and archived legacy content under the journal

## Runtime Cutover

To force the migrated instance to use the **new layout paths** instead of legacy
auto-fallbacks, local runtime overrides were applied in `config.local.yaml` for:

- `data/libraries/papers`
- `data/libraries/explore`
- `data/libraries/toolref`
- `data/libraries/proceedings`
- `data/libraries/citation_styles`
- `data/spool/*`
- `data/state/search/index.db`
- `data/state/metrics/metrics.db`
- `data/state/topics`
- `workspace/_system/figures`
- `workspace/_system/output/output.docx`
- `workspace/_system/translation-bundles`

Post-cutover `migrate verify` confirms the explicit new-path runtime is green:

- `papers_dir_accessible -> data/libraries/papers`
- `index_registry_accessible -> data/state/search/index.db`
- `keyword_search_accessible -> data/state/search/index.db`
- `explore_inventory -> data/libraries/explore`
- `toolref_inventory -> data/libraries/toolref`
- `spool_roots_accessible -> data/spool/*`

## Breaking Cleanup Finalization

On `breaking-compat-cleanup`, the migrated real root was finalized with:

```bash
python -m scholaraio.cli migrate finalize --migration-id finalize-live-20260424 --confirm
```

Observed result:

- `status: completed`
- `workspace_status: not_needed`
- `workspace_output_status: copied`
- `workspace_output_conflict_count: 1`
- `cleanup_status: completed_archived`
- `cleanup_candidate_count: 2`
- `verify_before_cleanup: passed`
- `verify_after_cleanup: passed`

Finalization-specific effects:

- legacy `workspace/translation-ws/` content was copied into
  `workspace/_system/translation-bundles/`
- legacy `workspace/figures/` content was copied into
  `workspace/_system/figures/`
- the remaining legacy roots were archived under:
  `.scholaraio-control/migrations/finalize-live-20260424/archive/workspace/`
- the root now reports:
  - `layout_state: normal`
  - `layout_version: 1`
  - `latest_journal: finalize-live-20260424`

One real operator-facing issue was found and fixed during this pass:

- `migrate status` previously chose `latest_journal` by lexical migration-id
  order, which could hide the newest finalize run behind an older id such as
  `formal-*`
- fixed by making journal resolution follow the most recent journal activity

## Real CLI Validation

### Real-root success paths

- `setup check --lang zh`
- `migrate status`, `plan`, `verify`, `cleanup`, `cleanup --confirm`
- `migrate finalize --confirm`
- `search`, `search-author`, `top-cited`
- `show --layer 2`, `show --layer 4`
- `refs`, `citing`, `shared-refs`
- `ws list`, `ws show`, `ws search`, `ws export`
- `style list`, `style show`
- `export markdown`, `export ris`, `export docx`
- `document inspect`
- `insights --days 30`
- `metrics --summary`
- `backup list`
- `explore list`
- `explore search --mode keyword --name jfm turbulence`
- `fsearch DMD`
- `toolref list`, `toolref search`, `toolref show`, `toolref use`
- `citation-check`
- `diagram --from-text --format mermaid`
- `translate --lang zh --force --portable`
- `arxiv search`
- `patent-search`
- `websearch`
- `webextract`

### Scratch-root success paths

- `import-endnote sample.ris`
- `attach-pdf`
- `pipeline --steps extract,dedup,ingest,embed,index` on Markdown ingest
- `audit`
- `repair`
- `rename --all`
- `backfill-abstract --doi-fetch`
- `enrich-toc --inspect`
- `enrich-l3 --inspect`
- `refetch --references-only`
- `ws init`, `ws add`, `ws show`, `ws search`, `ws rename`, `ws remove`
- `ingest-link --json --no-index`
- `arxiv fetch`
- `patent-fetch`
- `pipeline ingest --inspect` on fetched arXiv PDF
- `pipeline ingest --inspect` on fetched patent PDF
- `topics --build --rebuild --min-topic-size 2 --nr-topics 2`

## Notable Real Findings

### Fixed during this run

- `migrate verify` had a false-negative in `keyword_search_accessible`
  because the probe used an overly generic leading token and `top_k=3`
  could exclude the sample paper in real libraries.
- Fixed by making the verification probe prefer a title phrase.
- Regression test added in `tests/test_migration_control.py`.

- `migrate finalize --confirm` originally did not migrate/archive legacy
  workspace system-output roots (`workspace/translation-ws/`,
  `workspace/figures/`, `workspace/output.*`).
- Fixed by folding workspace system-output migration into finalize, preserving
  canonical target files on conflict and archiving the legacy roots in the
  journal.

- `migrate status` could report the wrong `latest_journal` because journal
  inventory used lexical directory order.
- Fixed by ordering journals by most recent activity so operator-facing status
  reflects the real latest finalize/verify run.

## Post-Restart Revalidation Note

On 2026-04-24, a post-restart repo-local CLI revalidation was run again against
the current `breaking-compat-cleanup` checkout.

Confirmed green on the current checkout via `python -m scholaraio.cli`:

- `setup check`
- `search`, `vsearch`, `usearch`
- `show`
- `ws list`, `ws show`, `ws search`, `ws export`
- `style list`
- `toolref list`, `toolref search`, `toolref show`, `toolref use`
- `explore list`, `explore search`
- `pipeline --list`
- `pipeline ingest --dry-run --inspect`
- `metrics --summary`
- `insights --days 30`
- `export docx`
- `document inspect`
- `diagram --from-ir`
- `migrate status`
- `migrate verify --migration-id finalize-live-20260424`

Important validation note:

- the environment-provided `scholaraio` console script did not reliably
  exercise the current checkout; repo-local validation therefore used
  `python -m scholaraio.cli`

Current environment blocker (not a code regression):

- provider-backed commands were attempted inside the current sandbox and were
  blocked by sandbox network restrictions or unavailable local sidecar services:
  - `translate --force --portable`: failed to reach the configured LLM proxy at
    `127.0.0.1:7890` (`Operation not permitted`)
  - `arxiv search`: failed to reach `export.arxiv.org` through the same blocked
    proxy path
  - `patent-search -c 3`: socket creation failed with `Operation not permitted`
  - `websearch`: local service `http://127.0.0.1:8765` was not reachable
  - `webextract`: local service `http://127.0.0.1:8766` was not reachable

These provider-backed paths require an out-of-sandbox rerun before they can be
re-marked green in the current session.

### Real negative cases that were informative

- `pipeline --steps extract,dedup,ingest,...` on PDF inputs failed with
  `no .md file` because the `mineru` step was missing.
  - Re-running with the proper `ingest` preset succeeded.
- A low-quality inbox Markdown sample failed ingest with:
  `no title and no abstract`
  - Re-running with a better real Markdown sample succeeded.
- `explore search` on `jfm` in default mode reported:
  `向量库为空`
  - `--mode keyword` worked, showing the library exists but lacks vector state.
- `topics` on a tiny 3-paper scratch library failed in UMAP/BERTopic with
  `k >= N`
  - After the scratch library grew to 7 papers, topics built successfully.

## Vector Rebuild Note

The migrated instance needed a new `data/state/search/index.db`.

Actions taken:

1. Rebuilt FTS successfully on the new path.
2. Attempted `embed --rebuild` on the new path twice:
   - once with the default runtime
   - once forcing CPU via `CUDA_VISIBLE_DEVICES=''`
3. Both runs remained in a very long pre-commit phase and did not materialize
   rows into `data/state/search/index.db` within the validation window.
4. To complete the cutover and validate real `vsearch/usearch` on the new path,
   the already validated legacy `paper_vectors` table from `data/index.db`
   was copied into `data/state/search/index.db`.

This was an explicit fallback, not a silent shortcut.

After the copy:

- `vsearch "dynamic mode decomposition"` succeeded on the new path
- `usearch "dynamic mode decomposition"` succeeded on the new path

## Environment / Capability Limits

- `import-zotero` could not be exercised end-to-end because:
  - no local `zotero.sqlite` was found under `$HOME`
  - no Zotero API key is configured
- `proceedings build-clean-candidates` succeeded on the real proceedings sample
  and generated `clean_candidates.json`
  - `apply-clean` and `apply-split` were not executed because they require
    human-authored `clean_plan.json` / `split_plan.json`

## Outputs Produced

Representative artifacts produced during the run:

- `workspace/release-validation/20260424-real-data-validation/hypersonic.bib`
- `workspace/release-validation/20260424-real-data-validation/dmd-refs.md`
- `workspace/release-validation/20260424-real-data-validation/dmd.ris`
- `workspace/release-validation/20260424-real-data-validation/launch-report.docx`
- `workspace/release-validation/20260424-real-data-validation/from_text_model_arch_Research_Question_Processing_Architectur.mermaid`
- `workspace/_system/translation-bundles/Chen-2012-Variants-of-Dynamic-Mode-Decomposition-Boundary-Condition-Koopman-and-Fourier-Analyses/paper_zh.md`

## Final Gates

Repository gates re-run after the migration-verification fix and real-root revalidation:

- `python -m pytest -q -p no:cacheprovider` -> `1305 passed, 3 skipped`
- `python -m pytest tests/test_migration_control.py -q` -> `25 passed`
- `python -m mkdocs build --strict` -> passed
- `git diff --check` -> passed
- `SCHOLARAIO_CONFIG=$PWD/config.yaml python -m scholaraio.cli migrate verify --migration-id formal-20260424`
  -> `17/17 passed`

## Overall Status

For the declared non-breaking upgrade scope, the migrated `develop` instance is
**operational on the new runtime layout** and the CLI surface has been exercised with
real commands rather than unit-test-only coverage.

Remaining items that still require either follow-up engineering or external inputs:

- investigate why full main-root `embed --rebuild` on the new search DB stays in a
  prolonged no-commit phase before the fallback copy
- add a graceful small-corpus guard for `topics` when BERTopic/UMAP receives too few
  papers
- provide a real Zotero source (`zotero.sqlite` or API credentials) if full
  `import-zotero` end-to-end validation is required
- provide human review plans if `proceedings apply-clean` / `apply-split` must be run
