"""Setup CLI command handler."""

from __future__ import annotations

import argparse


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def cmd_setup(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.setup import format_check_results, run_check, run_wizard

    action = getattr(args, "setup_action", None)
    if action == "check":
        lang = getattr(args, "lang", "zh")
        results = run_check(cfg, lang)
        _ui(format_check_results(results))
    else:
        run_wizard(cfg)
