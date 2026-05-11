"""Document-ingest helper functions."""

from __future__ import annotations

import json
import logging
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

from scholaraio.core.config import Config

_log = logging.getLogger(__name__)


def load_doc_sidecar_metadata(md_path: Path) -> Any | None:
    """Load same-stem JSON sidecar as pre-seeded document metadata when available."""
    sidecar_path = md_path.with_suffix(".json")
    if not sidecar_path.exists():
        return None

    try:
        from scholaraio.services.ingest_metadata._models import PaperMetadata

        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        allowed = {field.name for field in dataclass_fields(PaperMetadata)}
        payload = {key: value for key, value in data.items() if key in allowed}
        return PaperMetadata(**payload)
    except Exception as exc:
        _log.warning("failed to load document sidecar metadata %s: %s", sidecar_path.name, exc)
        return None


def repair_abstract(json_path: Path, md_path: Path, cfg: Config) -> None:
    """已入库论文 MD 补全后，检查并补写 abstract。"""
    from scholaraio.stores.papers import read_meta, write_meta

    paper_d = json_path.parent
    data = read_meta(paper_d)
    if data.get("abstract"):
        return
    from scholaraio.services.ingest_metadata import extract_abstract_from_md

    abstract = extract_abstract_from_md(md_path, cfg)
    if abstract:
        data["abstract"] = abstract
        write_meta(paper_d, data)
        _log.debug("abstract backfilled from MD (%d chars)", len(abstract))
