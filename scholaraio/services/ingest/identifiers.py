"""Identifier collection helpers for ingest duplicate detection."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

_log = logging.getLogger(__name__)


def collect_existing_ids(papers_dir: Path) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path]]:
    """Collect existing DOIs, patent publication numbers, and arXiv IDs for dedup.

    Returns:
        (dois, pub_nums, arxiv_ids) — DOI map lowercase key → json_path,
        pub_nums map uppercase key → json_path,
        arxiv_ids map normalized key → json_path.
    """
    from scholaraio.stores.papers import iter_paper_dirs

    dois: dict[str, Path] = {}
    pub_nums: dict[str, Path] = {}
    arxiv_ids: dict[str, Path] = {}
    if not papers_dir.exists():
        return dois, pub_nums, arxiv_ids
    for pdir in iter_paper_dirs(papers_dir):
        json_path = pdir / "meta.json"
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            doi = data.get("doi") or (data.get("ids") or {}).get("doi")
            if doi and doi.strip():
                dois[doi.lower().strip()] = json_path
            pub_num = (data.get("ids") or {}).get("patent_publication_number", "")
            if pub_num and pub_num.strip():
                pub_nums[pub_num.upper().strip()] = json_path
            arxiv_id = data.get("arxiv_id") or (data.get("ids") or {}).get("arxiv", "")
            arxiv_key = normalize_arxiv_id(arxiv_id)
            if arxiv_key:
                arxiv_ids[arxiv_key] = json_path
        except Exception as e:
            _log.debug("failed to read %s: %s", json_path.name, e)
    return dois, pub_nums, arxiv_ids


def collect_existing_dois(papers_dir: Path) -> dict[str, Path]:
    """Backward-compatible wrapper returning only DOIs."""
    dois, _, _ = collect_existing_ids(papers_dir)
    return dois


def normalize_arxiv_id(arxiv_id: str) -> str:
    """Normalize arXiv IDs for duplicate detection.

    Removes optional ``arXiv:`` prefix, trims whitespace, lowercases, and strips
    version suffixes such as ``v2`` so multiple versions map to the same record.
    """
    key = (arxiv_id or "").strip()
    if not key:
        return ""
    if key.lower().startswith("arxiv:"):
        key = key.split(":", 1)[1]
    key = key.strip().lower()
    return re.sub(r"v\d+$", "", key)
