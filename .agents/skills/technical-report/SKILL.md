---
name: technical-report
description: Use when the user wants a technical report, topic report, research briefing, structured investigation, evidence synthesis, recommendations, or final report packaging.
---
# Technical Report Workflow

Create a report-oriented workflow for investigation, synthesis, and recommendation.

## Purpose

This skill handles the cases that are **not quite a paper and not just raw notes**:
- technical survey reports
- topic briefings
- special-topic investigations
- advisor or team-facing research reports

It does not replace the deeper analysis skills. Instead, it decides which analysis path to use and then shapes the result into a report.

## When To Use

Use this skill when the user wants:
- a technical report
- a topic or special-subject report
- a research briefing for a team, supervisor, or project
- a recommendation memo grounded in literature

If the user mainly wants:
- a literature review article: use `/literature-review`
- an open-problem analysis: use `/research-gap`
- a slide deck: use `/document`

## Workflow

### 1. Clarify Report Goal

Identify:
- who the report is for
- whether the report is explanatory, comparative, or decision-support
- whether the user wants conclusions only or also recommendations
- whether the report is meant to stay as Markdown or become a formal DOCX/PPTX deliverable

### 2. Choose The Analysis Backbone

Use one primary path:

| Report type | Route |
|-------------|-------|
| State-of-the-art / what is known | `/literature-review` |
| Open questions / what is missing | `/research-gap` |
| User's own project update or method summary | `/paper-writing` |

### 3. Build A Report Structure

Recommended default structure:
1. Executive summary
2. Scope and question definition
3. Evidence base or literature coverage
4. Comparative analysis
5. Risks, limitations, or disagreements
6. Recommendations / next steps
7. References

Adjust by audience:
- supervisor or PI: prioritize takeaways and decisions
- technical team: prioritize trade-offs, methods, constraints
- self-study memo: prioritize structure and evidence trail

### 4. Package The Deliverable

- Use `/document` when the report should be turned into a formal `DOCX` or presentation.
- Use `/citation-check` before final delivery if the report contains generated author-year citations.
- Use `/export` if the user wants a bibliography bundle alongside the report.

## Output Pattern

Recommended outputs inside `workspace/<name>/`:
- `technical-report-outline.md`
- `technical-report.md`
- `references.bib`
- packaged deliverable from `/document` if requested

## Principles

- **Decision-oriented structure**: reports should help someone act, not only read.
- **Separation of layers**: analysis comes from existing writing/research skills; this skill organizes it into a report.
- **Audience-aware emphasis**: same evidence, different structure for different readers.
- **Honest scope**: packaging is currently routed through `/document`; do not imply a separate report generator backend.

## Example

用户说："帮我写一个这个方向的技术调研报告，给组会用"
→ 用本 skill 先明确 audience 和结构，再转 `/literature-review` 或 `/research-gap` 形成分析主体，最后接 `/document`
