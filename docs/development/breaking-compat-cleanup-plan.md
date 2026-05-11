# Breaking Compatibility Cleanup Plan

Status: Active breaking-layout cleanup plan

Last Updated: 2026-04-24

This document defines the **post-compatibility-window cleanup** for ScholarAIO.
It is intentionally separate from the compatibility-window execution docs:

- `docs/development/scholaraio-upgrade-plan.md`
- `docs/development/directory-migration-sequence.md`
- `docs/development/migration-mechanism-spec.md`
- `docs/development/user-data-migration-strategy.md`
- `docs/development/config-surface-audit.md`
- `docs/development/upgrade-validation-matrix.md`

Those documents governed the non-breaking upgrade generation. This document
governs the **breaking cleanup generation** where compatibility shims, legacy
module aliases, and legacy runtime fallback readers are actually removed.

## Objectives

The breaking cleanup generation MUST finish the migration instead of keeping
half-upgraded behavior alive indefinitely.

The cleanup therefore has four goals:

1. remove legacy Python import facades and alias packages
2. reduce `scholaraio.cli` to a real entrypoint rather than a monkeypatch facade
3. remove runtime path fallback readers that still auto-open legacy trees
4. migrate any still-live user data formats that would otherwise break under the
   fresh-layout-only runtime, especially workspace paper indexes

## Non-Goals

This cleanup is **not** a redesign of product behavior.

It MUST NOT:

- change CLI command names gratuitously
- redesign the canonical package split (`core`, `providers`, `stores`,
  `projects`, `services`, `interfaces`)
- move canonical skill roots away from `.claude/skills/`
- change the upgraded runtime topology (`data/libraries/`, `data/spool/`,
  `data/state/`, `workspace/_system/`)

## Target Contract

After this cleanup:

- canonical Python imports are the only supported imports:
  - `scholaraio.core.*`
  - `scholaraio.providers.*`
  - `scholaraio.stores.*`
  - `scholaraio.projects.*`
  - `scholaraio.services.*`
  - `scholaraio.interfaces.*`
- root compatibility modules such as `scholaraio.config`,
  `scholaraio.translate`, `scholaraio.index`, and similar aliases no longer
  exist
- legacy alias packages such as `scholaraio.sources.*`,
  `scholaraio.ingest.*`, and `scholaraio.ingest.metadata.*` no longer exist
- `scholaraio.cli` remains only as the published script/module entrypoint,
  without compatibility helper re-exports or monkeypatch-only aliases
- runtime path resolution is fresh-layout-only:
  - `data/libraries/papers/`
  - `data/libraries/explore/`
  - `data/libraries/toolref/`
  - `data/libraries/proceedings/`
  - `data/libraries/citation_styles/`
  - `data/spool/*`
  - `data/state/search/index.db`
  - `data/state/topics/`
  - `data/state/metrics/metrics.db`
  - `workspace/_system/translation-bundles/`
  - `workspace/_system/figures/`
  - `workspace/_system/output/output.docx`
- workspace paper references use `workspace/<name>/refs/papers.json`
  exclusively; root-level `workspace/<name>/papers.json` is migrated away

## Required Data Migration

Before runtime fallback readers are removed, the cleanup generation MUST ensure
that live data is no longer relying on old layouts.

Required migrations:

1. real durable trees must already exist at the fresh layout targets
2. workspace paper indexes must be rewritten from root `papers.json` to
   `refs/papers.json`
3. any real migrated runtime root used for validation must stop depending on
   legacy auto-detection
4. derived state MAY be rebuilt rather than copied when that is the more robust
   path

## Hardened Finalization Contract

The breaking cleanup generation standardizes one operator-facing upgrade command:

- `scholaraio migrate upgrade --migration-id <migration-id> --confirm`

This command runs the supported old-layout store moves that are present, then
executes the hardened finalization flow below. It is the preferred command to
hand to users for one-shot migration from the compatibility-window layout to
the current fresh-layout runtime.

The lower-level cleanup command remains:

- `scholaraio migrate finalize --migration-id <migration-id> --confirm`

This command is the required post-migration cleanup gate after supported store
moves are complete.

Hard rules:

1. finalize MUST refuse to run while the root is locked or while the current
   journal is unresolved
2. finalize MUST refresh the migration plan before cleanup so the journal
   reflects the real root state at the moment of cutover
3. finalize MUST rewrite any remaining workspace root `papers.json` files to
   `workspace/<name>/refs/papers.json` before compatibility readers are removed
4. finalize MUST migrate legacy workspace system-output roots into canonical
   `_system` targets:
   - `workspace/translation-ws/` -> `workspace/_system/translation-bundles/`
   - `workspace/figures/` -> `workspace/_system/figures/`
   - `workspace/output.*` -> `workspace/_system/output/`
5. finalize MUST NOT overwrite an existing canonical target artifact; when a
   target conflict exists, the canonical target wins, the legacy source is left
   for archival, and the conflict is reported in the journal
6. finalize MUST run `verify -> cleanup -> verify` as one journaled operation
7. finalize MUST archive cleanup candidates into the migration journal instead
   of deleting them directly
8. finalize MUST mark the instance metadata as fresh-layout runtime on success:
   - `layout_state = normal`
   - `layout_version = 1`
   - `last_successful_migration_id = <migration-id>`
9. control-plane views that report the "latest" migration journal MUST use the
   most recent journal activity, not lexical directory ordering

## Cleanup Order

The cleanup MUST proceed in this order:

1. freeze the cleanup target contract in docs
2. add or complete any missing workspace-index migration support
3. remove runtime fallback readers
4. update tests, docs, and skills to canonical imports and fresh-layout-only
   paths
5. remove root module facades and alias packages
6. simplify `scholaraio.cli` and remove CLI monkeypatch compatibility plumbing
7. run full repository validation plus real CLI validation on the migrated root

## Validation Requirements

This cleanup is incomplete unless all of the following are true:

- targeted regression tests for migrated code paths pass
- full `pytest` passes
- `ruff check` passes
- `git diff --check` passes
- `mkdocs build --strict` passes
- the migrated real develop root still passes real CLI validation on the
  fresh-layout-only runtime

Real CLI validation MUST include at least:

- `setup check`
- `search`, `vsearch`, `usearch`
- `show`
- `ws list/show/search/export`
- `toolref list/search/show/use`
- `explore list/search`
- `pipeline`
- `translate --portable`
- `document inspect`
- `migrate verify`
- `migrate finalize --confirm`

## Traceability

This breaking cleanup should land as multiple commits rather than one squash,
so future review can distinguish:

- data-format migration work
- runtime path cleanup
- import-surface cleanup
- CLI facade cleanup
- final verification
