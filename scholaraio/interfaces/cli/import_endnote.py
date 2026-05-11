"""Endnote import CLI command handler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _check_import_error(exc: ImportError) -> None:
    from scholaraio.interfaces.cli import compat as cli_mod

    cli_mod._check_import_error(exc)


def _batch_convert_pdfs(cfg, *, enrich: bool = False) -> None:
    from scholaraio.interfaces.cli import compat as cli_mod

    cli_mod._batch_convert_pdfs(cfg, enrich=enrich)


def cmd_import_endnote(args: argparse.Namespace, cfg) -> None:
    try:
        from scholaraio.providers.endnote import parse_endnote_full
    except ImportError as e:
        _check_import_error(e)

    from scholaraio.services.ingest.pipeline import import_external

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            _ui(f"Error: File does not exist: {p}")
            sys.exit(1)

    try:
        records, pdf_paths = parse_endnote_full(paths)
    except ImportError as e:
        _check_import_error(e)

    if not records:
        _ui("No records parsed")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        _ui(f"Parsed {len(records)} records, {n_pdfs} matching PDFs")
    else:
        _ui(f"Parsed {len(records)} records")

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg, enrich=True)
