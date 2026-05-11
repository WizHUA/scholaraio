"""
_doc_extract.py — 非论文文档的元数据提取
==========================================

对于缺少标题/摘要的普通文档（技术报告、课程讲义、标准文档等），
使用 LLM 从全文生成标题和摘要，确保文档可以被检索系统正确索引。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scholaraio.core.config import Config

from scholaraio.services.ingest_metadata._models import PaperMetadata

_log = logging.getLogger(__name__)

# LLM input truncation limit
_MAX_TEXT_FOR_LLM = 60_000

# document types that skip DOI warnings
DOCUMENT_TYPES = frozenset(
    {
        "document",
        "technical-report",
        "lecture-notes",
        "standard",
        "book-chapter",
        "manual",
        "white-paper",
        "presentation",
        "meeting-notes",
    }
)


def extract_document_metadata(
    md_path: Path,
    cfg: Config,
    *,
    existing_meta: PaperMetadata | None = None,
) -> PaperMetadata:
    """Extract/generate metadata for a non-paper document.

    Flow:
    1. Try regex extraction (may get title, authors, etc.)
    2. Check if extraction results are sufficient (need at least title)
    3. If insufficient, call LLM to generate title + summary from full text

    Args:
        md_path: Markdown file path.
        cfg: Global config.
        existing_meta: Pre-existing metadata (if any).

    Returns:
        PaperMetadata with at least title and abstract filled.
    """
    from scholaraio.services.ingest_metadata.extractor import RegexExtractor

    # Step 1: try regex extraction
    try:
        extractor = RegexExtractor()
        meta = extractor.extract(md_path)
    except Exception as e:
        _log.debug("regex extraction failed for doc: %s", e)
        meta = PaperMetadata()

    if existing_meta:
        meta = _merge_seeded_metadata(meta, existing_meta)
        _drop_web_source_url_author(meta)

    text = md_path.read_text(encoding="utf-8", errors="replace")

    # Step 2: check completeness
    has_title = bool((meta.title or "").strip())
    has_abstract = bool((meta.abstract or "").strip())

    if has_title and has_abstract:
        _log.debug("document already has title and abstract, skipping LLM")
        meta.paper_type = meta.paper_type or "document"
        return meta

    # Step 3: LLM generation
    api_key = cfg.resolved_api_key()
    if not api_key:
        _log.warning("no LLM API key, using fallback for document metadata")
        return _fallback_document_metadata(md_path, meta)

    truncated = text[:_MAX_TEXT_FOR_LLM]
    prompt = _build_prompt(truncated, has_title=has_title, has_abstract=has_abstract, existing_title=meta.title or "")

    try:
        from scholaraio.services.metrics import call_llm

        result = call_llm(prompt, cfg, purpose="doc_extract", max_tokens=1000)
        data = _parse_llm_response(result.content)

        if not has_title and data.get("title"):
            meta.title = data["title"]

        if not has_abstract and data.get("summary"):
            meta.abstract = data["summary"]

        if data.get("authors") and not meta.authors:
            meta.authors = data["authors"]
            meta.first_author = data["authors"][0] if data["authors"] else ""

        if data.get("year") and not meta.year:
            meta.year = data["year"]

        if data.get("document_type"):
            meta.paper_type = data["document_type"]
        else:
            meta.paper_type = meta.paper_type or "document"

    except Exception as e:
        _log.warning("LLM document extraction failed: %s", e)
        return _fallback_document_metadata(md_path, meta)

    # Final fallback: ensure title exists
    if not (meta.title or "").strip():
        meta.title = md_path.stem.replace("-", " ").replace("_", " ")

    meta.extraction_method = meta.extraction_method or "llm_document"
    return meta


def _merge_seeded_metadata(base: PaperMetadata, seeded: PaperMetadata) -> PaperMetadata:
    """Merge sidecar metadata into extracted document metadata without dropping regex fields."""
    merged: dict[str, object] = {}
    for field in fields(PaperMetadata):
        seeded_value = getattr(seeded, field.name)
        base_value = getattr(base, field.name)
        if _has_value(seeded_value):
            merged[field.name] = seeded_value
        else:
            merged[field.name] = base_value
    return PaperMetadata(**merged)


def _drop_web_source_url_author(meta: PaperMetadata) -> None:
    if (meta.source_type or "").strip().lower() != "web":
        return
    author = (meta.first_author or "").strip()
    if not author.lower().startswith("source url:"):
        return
    meta.authors = []
    meta.first_author = ""
    meta.first_author_lastname = ""


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def _fallback_document_metadata(
    md_path: Path,
    meta: PaperMetadata | None = None,
) -> PaperMetadata:
    """Minimal metadata extraction without LLM."""
    if meta is None:
        meta = PaperMetadata()

    text = md_path.read_text(encoding="utf-8", errors="replace")

    # Title: first markdown heading or filename
    if not (meta.title or "").strip():
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("# ") and not line.startswith("## "):
                meta.title = line.lstrip("# ").strip()
                break
        if not (meta.title or "").strip():
            meta.title = md_path.stem.replace("-", " ").replace("_", " ")

    # Abstract: first 500 words as summary
    if not (meta.abstract or "").strip():
        words = text.split()[:500]
        meta.abstract = " ".join(words)

    meta.paper_type = meta.paper_type or "document"
    meta.extraction_method = meta.extraction_method or "fallback_document"
    return meta


def _build_prompt(text: str, *, has_title: bool, has_abstract: bool, existing_title: str = "") -> str:
    """Build LLM prompt for document metadata extraction."""
    tasks = []
    if not has_title:
        tasks.append("1. Generate a concise, descriptive **title** for this document")
    if not has_abstract:
        idx = "2" if not has_title else "1"
        tasks.append(
            f"{idx}. Write a **summary** (150-300 words) "
            "that captures the main content, key points, and purpose of "
            "this document. This summary will be used as the document's "
            "abstract for search indexing."
        )

    task_str = "\n".join(tasks)

    return (
        "You are analyzing a document (not necessarily an academic paper). "
        "It could be a technical report, lecture notes, manual, standard, "
        "book chapter, or any other type of document.\n\n"
        f"Your tasks:\n{task_str}\n\n"
        "Also extract if present:\n"
        "- **authors**: list of author/editor names\n"
        "- **year**: publication/creation year\n"
        "- **document_type**: one of: technical-report, lecture-notes, "
        "standard, book-chapter, manual, white-paper, presentation, "
        "meeting-notes, or document (generic fallback)\n\n"
        + (f"Existing title: {existing_title}\n" if existing_title else "")
        + "Respond in JSON format:\n"
        "```json\n"
        "{\n"
        '  "title": "...",\n'
        '  "summary": "...",\n'
        '  "authors": ["..."],\n'
        '  "year": 2024,\n'
        '  "document_type": "..."\n'
        "}\n"
        "```\n\n"
        "--- DOCUMENT CONTENT ---\n\n"
        f"{text}"
    )


def _parse_llm_response(text: str) -> dict:
    """Extract JSON from LLM response."""
    # Try ```json ... ``` block
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return {}
