"""Web search and extraction CLI command handlers."""

from __future__ import annotations

import argparse
import sys


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def cmd_websearch(args: argparse.Namespace, cfg) -> None:
    """Real-time web search (Bing via GUILessBingSearch)."""
    from scholaraio.providers import webtools

    query = " ".join(args.query)
    count = args.count

    try:
        results = webtools.search_and_display(query, count=count, cfg=cfg)
    except webtools.ServiceUnavailableError as e:
        _ui(f"Error: {e}")
        _ui("Hint: Make sure the GUILessBingSearch service is running")
        _ui("  Install: https://github.com/wszqkzqk/GUILessBingSearch")
        _ui("  Start: python guiless_bing_search.py")
        sys.exit(1)
    except webtools.WebSearchError as e:
        _ui(f"Search failed: {e}")
        sys.exit(1)

    if not results:
        return


def _terminal_preview(text: str, *, max_chars: int) -> tuple[str, bool]:
    body = (text or "").strip()
    if not body:
        return "", False
    if max_chars < 1 or len(body) <= max_chars:
        return body, False
    return body[:max_chars].rstrip(), True


def cmd_webextract(args: argparse.Namespace, cfg) -> None:
    """Web content extraction (qt-web-extractor)."""
    from scholaraio.providers import webtools

    url = args.url
    pdf = args.pdf
    full = getattr(args, "full", False)
    max_chars = max(1, int(getattr(args, "max_chars", 4000) or 4000))

    try:
        result = webtools.extract_web(url, pdf=pdf, cfg=cfg)
    except webtools.WebExtractServiceUnavailableError as e:
        _ui(f"Error: {e}")
        _ui("Hint: make sure the qt-web-extractor service is running")
        sys.exit(1)
    except webtools.WebExtractError as e:
        _ui(f"Extraction failed: {e}")
        sys.exit(1)

    title = result.get("title", "")
    text = result.get("text") or ""
    text_body = text.strip()
    error = str(result.get("error") or "").strip()

    if error and not text_body:
        _ui(f"Extraction failed: {error}")
        sys.exit(1)

    if error:
        _ui(f"Extraction warning: {error}")

    _ui(f"Extraction succeeded: {title or url}")
    if not text_body:
        return

    output_text, truncated = (text_body, False) if full else _terminal_preview(text_body, max_chars=max_chars)
    if output_text:
        print(output_text)
    if truncated:
        _ui(
            f"Content is long; showing the first {len(output_text)} / {len(text_body)} characters; use --full to show the full text"
        )
