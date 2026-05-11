# ScholarAIO Upgrade Validation Report (2026-04-23)

Status: rehearsal execution record

Scope: concrete release-validation run for the current compatibility-window upgrade generation.

Final repo gate result:

- `ruff check` passed
- `ruff format --check` passed
- `git diff --check` passed
- `mkdocs build --strict` passed
- `python -m pytest -q -p no:cacheprovider` passed: `1304 passed, 3 skipped`

## 1. Run Context

- branch: `upgrade-validation-20260423`
- validation stamp: `workspace/release-validation/20260423-upgrade-validation/`
- base rehearsal commit at run start: `5a8b215`
- primary evidence roots:
  - `workspace/release-validation/20260423-upgrade-validation/evidence/legacy-smoke.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/migration/migration-smoke-v2.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/fresh-smoke-v2.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/online-canaries.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/translate-recheck.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/webtools-recheck.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/repo-checks-final.txt`
  - `workspace/release-validation/20260423-upgrade-validation/evidence/repo-checks-final-translate-fix.txt`

Rehearsal roots used:

- `legacy-root/`
  - compatibility-layout baseline and pre-migration smoke
- `migrated-root/`
  - first reproduction root that exposed a real migration-control bug
- `migrated-root-v2/`
  - clean rerun root after the migration-control fix
- `fresh-root-v2/`
  - new-layout-only runtime seeded from durable stores plus rebuildable state roots

## 2. Deterministic Local Validation

### 2.1 Legacy Root

`legacy-root/` was exercised with real CLI behavior, not `--help`-only checks.

Covered surfaces included:

- `setup check`
- `index --rebuild`, `embed --rebuild`
- `search`, `search-author`, `show`, `vsearch`, `usearch`, `top-cited`
- `ws list`, `ws show`, `ws search`, `ws export`
- `export docx`, `document inspect`
- `citation-check`
- `audit`, `rename --all --dry-run`, `repair --dry-run`
- `refs`, `citing`, `shared-refs`
- `style list`, `style show`
- `metrics --summary`, `insights`
- `toolref list`, `toolref search`, `toolref show`
- `explore list`, `explore search`, `fsearch --scope explore:* ...`
- `fsearch --scope proceedings ...`, `proceedings build-clean-candidates`
- `pipeline --list`, `pipeline --steps ... --dry-run --inspect`
- `attach-pdf --dry-run`
- `import-endnote --dry-run --no-api --no-convert`
- `diagram --from-ir`
- `backup list`

Result:

- deterministic legacy compatibility smoke passed
- one explore fixture (`jfm`) was correctly reported as structural-only / non-searchable because `explore.db` was absent
- proceedings helper flow produced `clean_candidates.json` as expected

### 2.2 Fresh Root

`fresh-root-v2/` was seeded with:

- `config.yaml` and `config.local.yaml`
- `data/libraries/`
- `data/spool/`
- `data/state/`
- `workspace/`

No legacy durable store trees such as `data/papers/`, `data/explore/`, `data/toolref/`, or `data/proceedings/` were copied into this root.

Fresh-root CLI coverage included:

- `setup check`
- `migrate status`
- `index --rebuild`, `embed --rebuild`
- `search`, `show`, `usearch`
- `ws list`, `ws show`
- `toolref list`
- `style list`
- `explore list`, `explore search`
- `pipeline --list`

Result:

- the new-layout-only root functioned correctly after rebuilding derived search state
- the sibling config remained usable in this root without needing manual path rewrites

## 3. Migration Rehearsal

### 3.1 Real Bug Found During First Run

The first `migrated-root/` rehearsal exposed a real migration-control defect:

- `migrate run --store citation_styles` failed with `post-run verification failed`
- the actual durable store copy was fine
- the failure came from unrelated main-library derived-state checks (`index_registry_accessible`, `keyword_search_accessible`) that were still reflecting pre-rebuild search baggage

This was fixed in code by teaching migration verification to distinguish:

- blocking failures
- non-blocking derived-state warnings

Implementation effect:

- `migrate run` now accepts `passed_with_warnings` only when every remaining failed check is in the explicitly non-blocking derived-state set
- final release signoff still requires a fully green post-rebuild `migrate verify`

### 3.2 Clean Rerun (`migrated-root-v2/`)

Migration journal:

- migration id: `validation-20260423-v2`
- journal root: `migrated-root-v2/.scholaraio-control/migrations/validation-20260423-v2/`

Control-plane and recovery coverage:

- `migrate status`
- `migrate plan --migration-id validation-20260423-v2`
- `migrate verify --migration-id validation-20260423-v2`
- synthetic `migration.lock` creation
- `migrate recover`
  - expected non-zero without `--clear-lock`
- `migrate recover --clear-lock`
- `migrate cleanup --migration-id ...`
- `migrate cleanup --migration-id ... --confirm`

Per-store runs completed successfully:

1. `citation_styles`
2. `toolref`
3. `explore`
4. `proceedings`
5. `spool`
6. `papers`

Post-migration actions:

- `migrate verify --migration-id validation-20260423-v2` -> `17/17 passed`
- `index --rebuild`
- `embed --rebuild`
- follow-up `migrate verify --migration-id validation-20260423-v2` -> `17/17 passed`
- `search`, `show`, `usearch`, `ws show`, `toolref list`, `style list`, `explore list`, `explore search`, `pipeline --list`
- `migrate cleanup --confirm` archived one cleanup candidate and left the lock absent

Result:

- migration detection, plan, run, recovery, verify, and cleanup all behaved correctly on the clean rerun root

## 4. Provider-Backed Canary Classification

All provider-backed surfaces were tested or explicitly classified.

| Surface | Result | Evidence / notes |
| --- | --- | --- |
| `arxiv` | passed | real `arxiv search dynamic mode decomposition --limit 3` returned live results |
| `explore fetch` | passed | real OpenAlex fetch wrote `data/libraries/explore/online-canary-20260423/papers.jsonl` |
| `refetch` | passed | live metadata call completed with rate-limit retries and no hard failure |
| `patent-search` + `patent-fetch` | passed | real USPTO search fetched `US20260109455A1.pdf` into `data/spool/inbox-patent/` |
| `enrich-l3` | passed | real LLM-backed conclusion extraction completed on `Chen-2012-...` |
| `diagram --from-text` | passed | real LLM-backed diagram generation wrote a Mermaid file under `workspace/skill-test/online-diagrams/` |
| `toolref fetch` | passed | real `toolref fetch qe --version 7.5 --force` indexed `1188` QE entries |
| `websearch` | passed after daemon startup | rerun against local `GUILessBingSearch` returned three live results for `dynamic mode decomposition` |
| `webextract` | passed after daemon startup | rerun against local `qt-web-extractor` extracted `https://arxiv.org/abs/2103.00001` successfully with preview text |
| `ingest-link` | passed after daemon startup | rerun fetched rendered content, ingested one md-only item, embedded it, indexed it, and returned JSON metadata |
| `translate --portable` | passed after fix and rerun | live rerun on `translate-recheck-root/` completed; `paper_zh.md` and the portable bundle were both written, `.translate_zh/` was removed after completion, and timeout fallback visibly subdivided oversized chunks |

### 4.1 Translation Follow-Up And Fix Verification

Original blocker was observed on:

- `fresh-root-v2/`
- `translate-debug-root/`

Initial symptoms:

- progress output stopped at `2/19`
- resume state showed many later chunks already successful, but chunk `2` and chunk `8` remained `pending`
- `paper_zh.md` was partially written
- no portable bundle export was completed

Relevant diagnostic details:

- chunk `2` length: `6451` chars
- chunk `8` length: `7414` chars
- both exceed the nominal `translate.chunk_size = 4000` after protected-block restoration

Current assessment:

- this was not a generic LLM-backend outage, because `enrich-l3` and `diagram --from-text` passed in the same environment
- this was not just a progress-log cosmetic issue; the translation state stopped advancing and required manual termination

Fix implemented:

- added timeout-aware resilient translation fallback that subdivides splittable chunks after a short timeout budget instead of waiting for the full five-attempt retry budget
- made retry subdivision recursive so formula-heavy restored chunks are forced under the retry target size before being sent back to the provider
- added cumulative non-prefix progress reporting so the CLI no longer looks frozen when later chunks succeed behind an early prefix gap
- covered the new behavior with targeted regression tests in `tests/test_translate.py`

Successful rerun:

- rerun root: `translate-recheck-root/`
- real command: `translate Chen-2012-Variants-of-Dynamic-Mode-Decomposition-Boundary-Condition-Koopman-and-Fourier-Analyses --lang zh --force --portable`
- observed live fallback:
  - `translate chunk timed out after retries (6451 chars); retrying as 2 subchunks`
  - `translate chunk timed out after retries (5260 chars); retrying as 2 subchunks`
- completion state:
  - `data/libraries/papers/Chen-2012-.../paper_zh.md` exists
  - `workspace/translation-ws/Chen-2012-.../paper_zh.md` exists
  - `.translate_zh/` workdir was removed after completion
- metrics snapshot on rerun root recorded `ok=38`, `error=8` translate calls, showing that the retry/split path recovered from repeated provider timeouts instead of stalling indefinitely

Artifacts retained for audit:

- `fresh-root-v2/data/libraries/papers/Chen-2012-.../.translate_zh/state.json`
- `fresh-root-v2/data/libraries/papers/Chen-2012-.../paper_zh.md`
- `translate-debug-root/.../.translate_zh/state.json`
- `workspace/release-validation/20260423-upgrade-validation/evidence/translate-debug.txt`
- `workspace/release-validation/20260423-upgrade-validation/evidence/translate-recheck.txt`

## 5. Release Judgment

### 5.1 Green

The following are now strongly validated for this upgrade generation:

- deterministic repo quality gates (`1304 passed, 3 skipped`, plus lint/format/docs gates)
- legacy compatibility reads and major CLI workflows
- migration control plane
- explicit store-by-store migration of `citation_styles`, `toolref`, `explore`, `proceedings`, `spool`, and `papers`
- post-migration rebuilt-root functionality
- fresh-layout-only runtime behavior after rebuild
- live canaries for `arxiv`, `explore fetch`, `refetch`, `websearch`, `webextract`, `ingest-link`, `patent-search/fetch`, `translate --portable`, `enrich-l3`, `diagram --from-text`, and `toolref fetch`

### 5.2 Not Fully Green Yet

No unresolved in-scope provider-backed blockers remain in this rehearsal record.

### 5.3 Strict Signoff Interpretation

If release signoff requires every provider-backed surface in scope to be green, the current rehearsal now satisfies that bar for the declared surface set.
