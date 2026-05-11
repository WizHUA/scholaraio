"""Pending-spool helpers for ingest."""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any

from scholaraio.services.ingest.assets import move_assets
from scholaraio.services.ingest.paths import pending_dir as resolve_pending_dir
from scholaraio.services.ingest.types import InboxCtx

_log = logging.getLogger(__name__)


def move_to_pending(
    ctx: InboxCtx,
    *,
    issue: str = "no_doi",
    message: str = "API 查询后仍无 DOI，需人工确认后补充 DOI 再入库",
    extra: dict | None = None,
) -> None:
    """将文件移入 pending 目录（每篇一个子目录）。

    Args:
        ctx: Inbox 上下文。
        issue: 问题类型标识（``"no_doi"`` | ``"no_pub_num"`` | ``"duplicate"``）。
        message: 人类可读的问题描述。
        extra: 附加信息写入 pending.json（如重复论文的已有路径）。
    """
    from scholaraio.services.ingest_metadata import metadata_to_dict

    pending_dir = ctx.pending_dir or resolve_pending_dir(ctx.cfg)
    pending_dir.mkdir(parents=True, exist_ok=True)

    md_stem = ctx.md_path.stem if ctx.md_path else ""
    pdf_stem = ctx.pdf_path.stem if ctx.pdf_path else ""
    # Use PDF name as directory name (human-readable), fall back to md stem or title
    dir_name = pdf_stem or md_stem
    if not dir_name and ctx.meta and ctx.meta.title:
        from scholaraio.services.ingest_metadata import generate_new_stem

        dir_name = generate_new_stem(ctx.meta)
    if not dir_name:
        dir_name = "unknown"
    paper_d = pending_dir / dir_name
    # Avoid overwriting an existing pending directory
    suffix = 2
    while paper_d.exists():
        paper_d = pending_dir / f"{dir_name}-{suffix}"
        suffix += 1
    paper_d.mkdir(parents=True)

    # Move .md
    if ctx.md_path and ctx.md_path.exists():
        shutil.move(str(ctx.md_path), str(paper_d / "paper.md"))

    # Move .pdf if present
    if ctx.pdf_path and ctx.pdf_path.exists():
        shutil.move(str(ctx.pdf_path), str(paper_d / ctx.pdf_path.name))

    # Move MinerU assets (images, layout.json, etc.)
    move_assets(ctx.inbox_dir, paper_d, pdf_stem or md_stem, md_stem)

    # Write marker JSON with extracted metadata + issue description
    marker: dict[str, Any] = {
        "issue": issue,
        "message": message,
    }
    if extra:
        marker.update(extra)
    if ctx.meta:
        marker["extracted_metadata"] = metadata_to_dict(ctx.meta)
    (paper_d / "pending.json").write_text(json.dumps(marker, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _log.debug("-> pending/%s/ (%s)", dir_name, issue)
