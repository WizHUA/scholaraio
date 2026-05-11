"""Citation-related CLI command handlers."""

from __future__ import annotations

import argparse
import logging
import sys


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _log_error(msg: str, *args) -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        logging.getLogger(__name__).error(msg, *args)
        return
    cli_mod._log.error(msg, *args)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    from scholaraio.interfaces.cli import compat as cli_mod

    return cli_mod._resolve_top(args, default)


def _print_search_result(idx: int, result: dict, extra: str = "") -> None:
    from scholaraio.interfaces.cli import compat as cli_mod

    cli_mod._print_search_result(idx, result, extra=extra)


def _print_search_next_steps() -> None:
    from scholaraio.interfaces.cli import compat as cli_mod

    cli_mod._print_search_next_steps()


def cmd_top_cited(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.index import top_cited

    try:
        results = top_cited(
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log_error("%s", e)
        sys.exit(1)

    if not results:
        _ui("No citation data found in the index. Run `scholaraio refetch --all` first.")
        return

    _ui(f"Top {len(results)} papers: \n")
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()
