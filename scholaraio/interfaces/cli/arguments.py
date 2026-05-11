"""Shared CLI argument helpers."""

from __future__ import annotations

import argparse


class _ResultLimitAction(argparse.Action):
    """Accept --limit as the canonical flag while keeping --top as a safe alias."""

    def __call__(self, parser, namespace, values, option_string=None):
        current = getattr(namespace, self.dest, None)
        if current is not None and current != values:
            parser.error("--limit and --top cannot be set to different values at the same time")
        setattr(namespace, self.dest, values)


def _add_result_limit_arg(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "--limit",
        "--top",
        dest="result_limit",
        metavar="N",
        type=int,
        default=None,
        action=_ResultLimitAction,
        help=f"{help_text} (legacy alias: --top)",
    )


def _resolve_result_limit(args: argparse.Namespace, default: int) -> int:
    result_limit = getattr(args, "result_limit", None)
    if result_limit is not None:
        return result_limit
    legacy_top = getattr(args, "top", None)
    if legacy_top is not None:
        return legacy_top
    return default


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return _resolve_result_limit(args, default)


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024 / 2020-")
    parser.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        dest="paper_type",
        help="Paper type filter: review / journal-article / etc. (fuzzy match)",
    )
