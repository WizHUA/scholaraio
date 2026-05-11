"""Detection helpers shared by ingest document classifiers."""

from __future__ import annotations

import json
import logging
import re

from scholaraio.services.ingest.types import InboxCtx

_log = logging.getLogger(__name__)


def parse_detect_json(text: str) -> dict:
    """Tolerant JSON extraction from LLM response (handles fences/extra text)."""
    text = text.strip()
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try bare JSON object (greedy to handle nested braces)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def detect_patent(ctx: InboxCtx) -> bool:
    """Detect if a no-DOI document is a patent.

    Checks publication_number from extractor first (fast path),
    then scans text for patent keywords.

    Args:
        ctx: Inbox context with ``ctx.meta`` set.

    Returns:
        ``True`` if document is a patent.
    """
    if ctx.meta and ctx.meta.publication_number:
        _log.debug("patent detected by publication_number: %s", ctx.meta.publication_number)
        return True

    # Fast heuristic: paper_type already set
    if ctx.meta and ctx.meta.paper_type and ctx.meta.paper_type.lower().strip() == "patent":
        return True

    # Title keyword check
    title = (ctx.meta.title or "").lower() if ctx.meta else ""
    for keyword in ("patent", "专利", "发明专利", "实用新型", "utility model"):
        if keyword in title:
            _log.debug("patent detected by title keyword: %s", keyword)
            return True

    # Scan text for patent number patterns
    if ctx.md_path and ctx.md_path.exists():
        try:
            text = ctx.md_path.read_text(encoding="utf-8", errors="replace")[:10000]
            from scholaraio.services.ingest_metadata._models import PATENT_NUMBER_RE

            m = PATENT_NUMBER_RE.search(text)
            if m:
                if ctx.meta and not ctx.meta.publication_number:
                    ctx.meta.publication_number = m.group(1).upper()
                _log.debug("patent detected by publication number in text: %s", m.group(1))
                return True
        except Exception as e:
            _log.debug("failed to scan for patent number: %s", e)

    return False


def detect_thesis(ctx: InboxCtx) -> bool:
    """LLM 判断无 DOI 论文是否为学位论文。

    读取 MD 前 30000 字符，让 LLM 判断文档类型。
    LLM 不可用时退回 False（走 pending 流程）。

    Args:
        ctx: Inbox 上下文，需要 ``ctx.md_path`` 已设置。

    Returns:
        ``True`` 如果判定为 thesis/dissertation。
    """
    if not ctx.md_path or not ctx.md_path.exists():
        return False

    try:
        with open(ctx.md_path, encoding="utf-8") as f:
            text = f.read(30000)
    except Exception as e:
        _log.debug("failed to read md for thesis detection: %s", e)
        return False

    # Fast heuristic: title/metadata already hints thesis
    title = (ctx.meta.title or "").lower() if ctx.meta else ""
    for keyword in (
        "thesis",
        "dissertation",
        "学位论文",
        "硕士论文",
        "博士论文",
        "毕业论文",
        "master's thesis",
        "doctoral dissertation",
    ):
        if keyword in title:
            _log.debug("thesis detected by title keyword: %s", keyword)
            return True

    # LLM detection
    try:
        api_key = ctx.cfg.resolved_api_key()
    except Exception as e:
        _log.debug("failed to resolve API key: %s", e)
        api_key = None
    if not api_key:
        _log.debug("no LLM API key, skipping thesis detection")
        return False

    from scholaraio.services.metrics import call_llm

    prompt = (
        "Analyze the following document excerpt and determine if it is a "
        "thesis or dissertation (学位论文/硕士论文/博士论文/毕业论文). "
        "Look for indicators such as: degree awarding institution, "
        "advisor/supervisor, thesis committee, degree type (PhD/Master/Bachelor), "
        "declaration of originality, or thesis-specific formatting.\n\n"
        'Respond in JSON: {"is_thesis": true/false, "reason": "brief explanation"}\n\n'
        f"--- DOCUMENT START ---\n{text}\n--- DOCUMENT END ---"
    )
    try:
        result = call_llm(prompt, ctx.cfg, purpose="detect_thesis", max_tokens=200)
        data = parse_detect_json(result.content)
        is_thesis = bool(data.get("is_thesis", False))
        if is_thesis:
            reason = data.get("reason", "")
            _log.debug("thesis detected by LLM: %s", reason)
        return is_thesis
    except Exception as e:
        _log.debug("thesis detection LLM call failed: %s", e)

    return False


def detect_book(ctx: InboxCtx) -> bool:
    """LLM 判断无 DOI 论文是否为书籍/专著。

    读取 MD 前 30000 字符，让 LLM 判断文档类型。
    LLM 不可用时退回 False（走 pending 流程）。

    Args:
        ctx: Inbox 上下文，需要 ``ctx.md_path`` 已设置。

    Returns:
        ``True`` 如果判定为 book/monograph。
    """
    if not ctx.md_path or not ctx.md_path.exists():
        return False

    # Fast heuristic: paper_type already set by API (Crossref/S2/OpenAlex)
    _BOOK_TYPES = {"book", "monograph", "edited-book", "reference-book"}
    if ctx.meta and ctx.meta.paper_type and ctx.meta.paper_type.lower().strip() in _BOOK_TYPES:
        _log.debug("book detected by API paper_type: %s", ctx.meta.paper_type)
        return True

    # Fast heuristic: title keywords
    title = (ctx.meta.title or "").lower() if ctx.meta else ""
    for keyword in (
        "handbook",
        "textbook",
        "monograph",
        "专著",
        "教材",
        "手册",
    ):
        if keyword in title:
            _log.debug("book detected by title keyword: %s", keyword)
            return True

    try:
        with open(ctx.md_path, encoding="utf-8") as f:
            text = f.read(30000)
    except Exception as e:
        _log.debug("failed to read md for book detection: %s", e)
        return False

    # LLM detection
    try:
        api_key = ctx.cfg.resolved_api_key()
    except Exception as e:
        _log.debug("failed to resolve API key: %s", e)
        api_key = None
    if not api_key:
        _log.debug("no LLM API key, skipping book detection")
        return False

    from scholaraio.services.metrics import call_llm

    prompt = (
        "Analyze the following document excerpt and determine if it is a "
        "book or monograph (书籍/专著/教材/手册). "
        "Look for indicators such as: ISBN, publisher information, "
        "table of contents with chapters, preface/foreword, "
        "book-specific formatting (parts/chapters rather than sections), "
        "or multiple self-contained chapters with distinct topics.\n\n"
        'Respond in JSON: {"is_book": true/false, "reason": "brief explanation"}\n\n'
        f"--- DOCUMENT START ---\n{text}\n--- DOCUMENT END ---"
    )
    try:
        result = call_llm(prompt, ctx.cfg, purpose="detect_book", max_tokens=200)
        data = parse_detect_json(result.content)
        is_book = bool(data.get("is_book", False))
        if is_book:
            reason = data.get("reason", "")
            _log.debug("book detected by LLM: %s", reason)
        return is_book
    except Exception as e:
        _log.debug("book detection LLM call failed: %s", e)

    return False
