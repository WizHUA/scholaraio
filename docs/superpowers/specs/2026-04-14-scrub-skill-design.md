# Scrub Skill Design

Date: 2026-04-14
Topic: `issue #51` metadata scrub workflow
Related issue: `ZimoLiao/scholaraio#51`

## Summary

ScholarAIO already has most of the primitives needed to repair bad metadata after ingest:

- `scholaraio enrich-*` enriches content and metadata-adjacent fields
- `scholaraio audit` identifies many quality problems
- `scholaraio repair` rewrites selected metadata fields for one paper
- `scholaraio rename` normalizes directory names
- `scholaraio pipeline reindex` rebuilds search state after changes

What is missing is a stable, incremental workflow for post-enrich cleanup of low-quality records produced from non-standard documents. `issue #51` asks for exactly that: a new orchestration-only `scrub` skill that repairs bad metadata after enrich and drops a `.scrubbed` marker into each processed paper directory.

This design keeps `scrub` primarily as a skill, but adds a thin layer of reusable code support so the workflow is reliable, testable, and idempotent.

## Problem

MinerU and fallback parsers can successfully convert many non-standard documents into Markdown while still leaving the resulting metadata in a poor state. Typical failures include:

- placeholder or garbled titles
- missing or malformed author names
- missing or placeholder years such as `XXXX`
- directory names derived from bad metadata

These records may already be ingestable and searchable, but they are not trustworthy enough for normal library use. Today, fixing them requires ad hoc manual inspection and repeated use of unrelated commands. The project lacks:

- a standard workflow for post-enrich cleanup
- a persistent marker for "this paper has already been reviewed"
- a shared definition of "scrub-worthy" metadata issues

## Goals

- Add a `scrub` skill that orchestrates post-enrich metadata cleanup for papers in the configured papers library
- Make the workflow incremental by skipping directories that already contain `.scrubbed`
- Reuse existing CLI and module-level repair/rename/indexing functionality
- Add a small amount of underlying support code for marker handling and suspect detection
- Keep human or agent judgment in the loop for semantic repair decisions

## Non-Goals

- Do not introduce a fully automatic metadata repair engine
- Do not replace ingest-time extraction or enrich-time logic
- Do not add a large new subsystem or a complex `scholaraio scrub` command in v1
- Do not silently invent metadata that cannot be supported by the paper content

## Current Code Context

The design builds directly on the following existing code:

- `scholaraio/cli.py`
  - `cmd_audit()`
  - `cmd_repair()`
  - `cmd_pipeline()`
- `scholaraio/audit.py`
  - rule-based metadata checks already exist, but they are framed as diagnostics rather than scrub candidates
- `scholaraio/papers.py`
  - acts as the path/source-of-truth helper layer for paper directories
- `scholaraio/ingest/metadata/_writer.py`
  - `rename_paper()` and metadata write behavior already normalize directories after fixes
- `scholaraio/loader.py`
  - `show`/layered reading supports content review needed for metadata correction

This is why `scrub` should be a workflow layer, not a new ingest subsystem.

## Proposed Approach

Use a hybrid design:

- `scrub` remains an orchestration skill
- a thin support layer is added in Python for:
  - `.scrubbed` marker management
  - shared "suspicious metadata" heuristics

This is the smallest design that makes the workflow durable. A pure skill-only solution would duplicate state handling and heuristics in Markdown instructions. A full CLI command would over-automate a task that still needs semantic review.

## User Workflow

### Primary flow

1. User asks to scrub bad records after enrich
2. Skill scans the configured papers library
3. Skill skips papers already marked with `.scrubbed`
4. Skill identifies likely-bad candidates using shared heuristics and existing audit-style checks
5. For each candidate, the agent inspects:
   - `meta.json`
   - `paper.md` head or relevant sections
   - existing enrich output when useful
6. The agent repairs key metadata fields
7. The paper is renamed into standard `Author-Year-Title` format
8. A `.scrubbed` marker is created for accepted results
9. After the batch, indexes are rebuilt once

### Incremental behavior

The marker file is the durable boundary:

- if `.scrubbed` exists, the paper is considered reviewed and skipped by default
- if the user wants to revisit all papers, they can delete markers first
- papers can still remain imperfect after review, but the marker means "reviewed and currently acceptable"

This supports large libraries and repeated cleanup passes without rescanning the whole corpus every time.

## Metadata Repair Scope

`scrub` should focus on the small set of fields that determine user-facing identity and directory naming:

- `title`
- `authors`
- `first_author`
- `first_author_lastname`
- `year`

It may preserve all other existing fields unless there is strong evidence they are wrong. In particular:

- keep DOI and IDs unless clearly invalid
- keep abstract unless the record is unusable and must be regenerated separately
- do not rewrite citations, TOC, or L3 as part of scrub

This narrow repair surface keeps the workflow safe.

## Marker Support Design

Add thin helpers to `scholaraio/papers.py`:

- `scrub_marker_path(paper_d: Path) -> Path`
- `is_scrubbed(paper_d: Path) -> bool`
- `mark_scrubbed(paper_d: Path) -> None`
- `clear_scrubbed(paper_d: Path) -> None` optionally

Why `papers.py`:

- marker handling is directory-state logic
- `papers.py` is already the central path helper layer
- other modules and future skills can reuse this without re-implementing file conventions

Marker format:

- path: `<configured papers_dir>/<Author-Year-Title>/.scrubbed`
- contents: empty file is acceptable for v1

We intentionally keep it simple so the marker is stable across tools and easy to inspect from shell or agent workflows.

## Candidate Detection Design

`scholaraio/audit.py` already has useful rule-based checks, but not all of them map directly to scrub candidates. We should add a small helper layer for "suspect" detection that can be reused by the skill and possibly later by CLI/reporting.

Suggested helper shape:

- `list_scrub_suspects(papers_dir: Path) -> list[Issue]`

This does not need to be exposed as a top-level CLI command in v1. It can remain a Python helper used by tests and future extensions.

### Candidate rules

Rules should be conservative and bias toward obvious bad metadata:

- garbled title
  - contains replacement chars such as `�`
- placeholder title
  - examples: `Introduction`, `TLDR`, `Overview`, `Summary`
- truncated or obviously broken title
  - for example, suspicious punctuation endings or malformed OCR fragments
- missing or suspicious author
  - empty `authors`
  - `first_author_lastname` missing
  - likely placeholders like `Unknown`
  - obvious noise-only author strings
- suspicious year
  - missing year
  - placeholder-equivalent year state reflected in directory name or metadata workflow
- suspicious directory stem
  - malformed `Author-Year-Title` shape driven by bad metadata

The rules should be shared with `audit` where practical instead of creating two unrelated vocabularies for metadata quality.

## Skill Design

Add `.claude/skills/scrub/SKILL.md` with the following behavior:

### Trigger conditions

Use when:

- the user wants to clean metadata after enrich
- papers have bad titles, authors, or years
- the user wants incremental cleanup with `.scrubbed` markers

### Workflow

1. List unmarked papers
2. Narrow to suspicious candidates
3. Inspect paper content and metadata
4. Repair only identity-critical fields
5. Rename the paper directory
6. Mark the paper as scrubbed
7. Rebuild indexes once at the end

### Recommended command usage

- use `scholaraio audit` for initial diagnostics when helpful
- use `scholaraio show "<paper-id>" --layer 1` and inspect `paper.md` directly when needed
- use `scholaraio repair "<paper-id>" ...` for stable metadata rewriting
- use `scholaraio rename --all` or single-paper rename helpers if the workflow requires it
- use `scholaraio pipeline reindex` after the batch

### Decision policy

- title quality is highest priority
- authors and year should be fixed when evidence is available
- unknown fields may remain unknown if evidence is too weak
- never fabricate DOI or publication venue
- `.scrubbed` means reviewed, not necessarily perfect

## Error Handling

The workflow should degrade safely:

- missing `paper.md`
  - skip and report; do not mark scrubbed
- malformed `meta.json`
  - report as blocking; do not mark scrubbed
- insufficient evidence to fix author or year
  - keep unresolved field, but allow marking if title and overall identity are acceptable
- rename collision
  - defer to the existing rename collision behavior in `_writer.py`

This avoids coupling scrub to brittle all-or-nothing repair behavior.

## Testing Strategy

### Unit tests

Add tests for marker helpers:

- `is_scrubbed()` returns false when absent
- `mark_scrubbed()` creates the marker
- repeated marking is idempotent
- optional clear helper removes the marker

Add tests for suspect detection:

- placeholder titles are flagged
- garbled titles are flagged
- missing or unknown authors are flagged
- suspicious years are flagged
- healthy records are not flagged

### Regression expectations

The new support should not change:

- ingest behavior
- existing audit severity semantics unless explicitly extended
- rename behavior
- search/index schema

## Rollout Plan

### Phase 1

- add marker helpers in `papers.py`
- add suspect-detection helpers in `audit.py`
- add tests
- add `scrub` skill

### Phase 2

- evaluate whether a lightweight CLI helper is worth adding later, such as a candidate lister
- only add CLI surface if real user workflows show repeated friction

## Recommendation

Implement `issue #51` as:

- one new skill: `scrub`
- thin marker/state support in `papers.py`
- thin suspect-detection support in `audit.py`
- no top-level `scholaraio scrub` command in v1

This preserves the original "orchestration only" intent while still giving the skill a stable substrate. It fits the existing ScholarAIO architecture, which prefers reusable low-level primitives plus agent-led workflows over overly rigid automation for judgment-heavy tasks.
