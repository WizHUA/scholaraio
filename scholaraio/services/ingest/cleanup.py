"""Cleanup helpers for ingest inbox files."""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def cleanup_inbox(pdf_path: Path | None, md_path: Path | None, dry_run: bool) -> None:
    if dry_run:
        if pdf_path:
            _log.debug("would delete: %s", pdf_path.name)
        if md_path and md_path.exists():
            _log.debug("would delete: %s", md_path.name)
        return
    if pdf_path and pdf_path.exists():
        pdf_path.unlink()
        _log.debug("deleted: %s", pdf_path.name)
    if md_path and md_path.exists():
        md_path.unlink()
        _log.debug("deleted: %s", md_path.name)
