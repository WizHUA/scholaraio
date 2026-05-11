# ScholarAIO 1.4.0 Release Self-Check Report

Date: 2026-04-25

Branch: `breaking-compat-cleanup`

Checkpoint commit: `925f10b Checkpoint before 1.4 release self-check`

Evidence root: `workspace/release-validation/20260425-1.4.0-self-check/evidence/`

## Scope

This is the release-readiness gate for the post-`develop` migration and
runtime-layout refactor. It checks code, CLI behavior, migration behavior,
skills, agent entry documents, docs, packaging, and actual command execution.

Skill documentation was treated as a release blocker. The validation was aligned
with Anthropic skill best practices and OpenAI Codex skill documentation:

- Anthropic: `https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices`
- OpenAI Codex: `https://developers.openai.com/codex/skills`

## Round Matrix

| Round | Area | Gate | Status | Evidence |
| --- | --- | --- | --- | --- |
| 01 | Git baseline | Branch and pre-check state recorded before edits | PASS | `01-git-baseline.txt` |
| 02 | Version metadata | Release target is consistently represented | PASS | `02-version-metadata.txt` |
| 03 | Changelog/release notes | 1.4.0 notes describe shipped changes without stale claims | PASS | `03-changelog.txt` |
| 04 | CLI surface vs implementation | Parser command tree matches documented command surface | PASS | `04-cli-surface.txt` |
| 05 | README and getting-started docs | Top-level docs point users to current layout and commands | PASS | `05-top-level-docs.txt` |
| 06 | Agent entry docs | Agent wrappers stay lightweight and point to canonical docs/skills | PASS | `06-agent-entry-docs.txt` |
| 07 | Skill inventory | Canonical and wrapper skill sets are complete and aligned | PASS | `07-skill-inventory.txt` |
| 08 | Skill frontmatter | Skill metadata is valid, discoverable, and not process-heavy | PASS | `08-skill-frontmatter.txt` |
| 09 | Skill command/path references | Skills avoid stale legacy paths and reference valid commands | PASS | `09-skill-command-paths.txt` |
| 10 | Runtime layout docs vs code | Runtime layout docs match config/accessor behavior | PASS | `10-runtime-layout.txt` |
| 11 | Migration docs vs code/tests | Migration commands and cleanup gates match implementation | PASS | `11-migration-alignment.txt` |
| 12 | Main/v1.3.1 coverage continuity | Previous feature coverage report remains traceable and current | PASS | `12-main-v131-coverage.txt` |
| 13 | Recent feature docs vs code | Webtools, patent, import/export, workspace, scientific support align | PASS | `13-feature-docs-code.txt` |
| 14 | Packaging metadata | Build artifacts contain expected entry points and package data | PASS | `14-packaging.txt` |
| 15 | Wheel install smoke | Built package works in an isolated environment | PASS | `15-wheel-install-smoke.txt` |
| 16 | Full unit/integration tests | Full pytest suite passes from current checkout | PASS | `16-pytest.txt` |
| 17 | Static checks | Ruff lint and format checks pass | PASS | `17-ruff.txt` |
| 18 | Documentation build | MkDocs strict build passes | PASS | `18-mkdocs.txt` |
| 19 | Migration real canary | Legacy data migrates through one-command upgrade and verifies | PASS | `19-migration-canary.txt` |
| 20 | Actual CLI canary matrix | Core skills/CLI paths run against migrated data, not just tests | PASS | `20-cli-canaries.txt` |

## Key Findings

- Version metadata was still at `1.3.1`; it is now `1.4.0` in `pyproject.toml`,
  `scholaraio/__init__.py`, the changelog, and `tests/test_version.py`.
- Several public docs and skills still implied old roots could be used as normal
  runtime inputs. README, ingestion docs, agent reference, and affected skills
  now point to `scholaraio migrate upgrade --migration-id <id> --confirm`.
- Active project skill frontmatter was inconsistent across generations. All 45
  active skills now use only `name` and `description`, descriptions start with
  `Use when`, cross-agent symlinks point to the same canonical `.claude/skills/`
  source, and `.claude/skills/_templates/validate_skills.py` enforces the rule.
- A routing regression was found during skill validation: `academic-writing`
  could steal explicit rebuttal requests from `review-response`. The router
  description was narrowed, and the routing smoke tests now pass.
- Actual CLI canaries uncovered a scalar `citation_count` bug in paper metadata.
  `best_citation()` and the index hash now handle scalar citation counts, with
  regression tests in `tests/test_papers.py`.
- Webtools MCP was tested against live local services: `webextract` used
  `qt-web-extractor` MCP `fetch_url`; `websearch` used GUILessBingSearch MCP
  `search_bing`; `ingest-link --dry-run` exercised the web ingestion path.

## Verification Summary

- Package build: `Successfully built scholaraio-1.4.0.tar.gz` and
  `scholaraio-1.4.0-py3-none-any.whl`.
- Wheel smoke: isolated install exposes `scholaraio`, `python -m scholaraio.cli`,
  and imports `scholaraio.__version__ == 1.4.0`.
- Full tests: `1297 passed, 3 skipped in 74.00s`.
- Ruff: `All checks passed!` and `189 files already formatted`.
- MkDocs strict build completed successfully.
- Migration canary: `migrate upgrade`, `migrate verify`, and `migrate status`
  passed with `checks: 18/18 passed`, fresh targets present, and legacy roots
  removed or archived through the migration journal.
- CLI canary matrix: 42 real command paths were exercised against migrated data,
  including setup, migrate, index, search/show, graph, explore, workspace,
  export/style, citation-check, audit, rename, metrics, insights, toolref,
  document, diagram, backup, webextract, websearch, ingest-link, arXiv, and
  patent search. The `vsearch` disabled-semantic path intentionally exits 1
  when embeddings are configured as `provider=none`; the canary treats that as
  the expected degraded behavior.

No release-blocking gaps remain in this self-check evidence set.
