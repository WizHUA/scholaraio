"""Shared type definitions for ingest pipeline orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from scholaraio.core.config import Config


class StepResult(Enum):
    """流水线步骤返回值。"""

    OK = "ok"
    SKIP = "skip"
    FAIL = "fail"


@dataclass
class StepDef:
    """流水线步骤定义。

    Attributes:
        fn: 步骤执行函数。
        scope: 作用域，``"inbox"`` | ``"papers"`` | ``"global"``。
        desc: 步骤描述（用于 ``--list`` 输出）。
    """

    fn: Callable
    scope: str
    desc: str


@dataclass
class InboxCtx:
    """Inbox 步骤间传递的单文件上下文。

    Attributes:
        pdf_path: 原始 PDF 路径，md-only 入库时为 ``None``。
        inbox_dir: inbox 目录路径。
        papers_dir: 已入库论文目录路径。
        existing_dois: 已入库论文的 DOI → JSON 路径映射（用于去重）。
        cfg: 全局配置。
        opts: 运行选项（dry_run, no_api, force 等）。
        pending_dir: 无 DOI 论文的待审目录。
        md_path: Markdown 文件路径（MinerU 输出或直接放入）。
        meta: 提取后的 :class:`~scholaraio.services.ingest_metadata.PaperMetadata`。
        status: 当前状态，``"pending"`` | ``"ingested"`` | ``"duplicate"``
            | ``"needs_review"`` | ``"failed"`` | ``"skipped"``。
    """

    pdf_path: Path | None
    inbox_dir: Path
    papers_dir: Path
    existing_dois: dict[str, Path]
    cfg: Config
    opts: dict[str, Any]

    pending_dir: Path | None = None
    md_path: Path | None = None
    meta: Any = None  # PaperMeta instance after extraction
    status: str = "pending"  # pending | ingested | duplicate | needs_review | failed | skipped
    ingested_json: Path | None = None  # set by step_ingest on success
    is_thesis: bool = False  # thesis inbox or LLM-detected thesis
    is_patent: bool = False  # patent inbox or detected patent
    existing_pub_nums: dict[str, Path] | None = None  # patent publication number dedup
    existing_arxiv_ids: dict[str, Path] | None = None  # arXiv preprint dedup
