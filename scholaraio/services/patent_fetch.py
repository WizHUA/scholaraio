"""
patent_fetch.py — 专利 PDF 下载
==============================

优先通过 USPTO PPUBS 官方导出接口下载美国专利 PDF，并在必要时回退到
Google Patents 页面抓取。

用法::

    from scholaraio.services.patent_fetch import download_patent_pdf
    path = download_patent_pdf("https://patents.google.com/patent/US20240176406A1")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import requests

from scholaraio.core.log import ui
from scholaraio.providers import uspto_ppubs

if TYPE_CHECKING:
    from scholaraio.core.config import Config

_log = logging.getLogger("scholaraio.patent_fetch")

GOOGLE_PATENTS_HOST = "patents.google.com"
PDF_URL_PATTERN = re.compile(r"https?://patentimages\.storage\.googleapis\.com/[^\s\"'<>]+\.pdf")
US_PUBLICATION_NUMBER_PATTERN = re.compile(r"^US\d{6,}[A-Z]\d?$", re.IGNORECASE)


class PatentFetchError(Exception):
    """专利下载异常。"""

    pass


def _resolve_url(id_or_url: str) -> str:
    """将专利 ID 或 URL 解析为完整的 Google Patents URL。"""
    raw = id_or_url.strip()
    if raw.startswith(("http://", "https://")):
        return raw
    # 纯 ID，构造默认 URL
    return f"https://patents.google.com/patent/{raw}"


def _extract_patent_id(url: str) -> str:
    """从 URL 中提取专利 ID（如 US20240176406A1）。"""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    # 期望路径: /patent/<ID>
    if len(path_parts) >= 2 and path_parts[0] == "patent":
        return path_parts[1]
    # 兜底：取最后一段
    if path_parts:
        return path_parts[-1]
    return "unknown"


def _normalize_identifier(identifier: str) -> str:
    """标准化专利标识。"""
    return re.sub(r"[^A-Za-z0-9]", "", str(identifier or "")).upper()


def _looks_like_us_publication_number(identifier: str) -> bool:
    """判断是否是可由 USPTO PPUBS 直接处理的美国公开号。"""
    return bool(US_PUBLICATION_NUMBER_PATTERN.match(_normalize_identifier(identifier)))


def _download_via_ppubs(
    publication_number: str,
    out_file: Path,
    *,
    timeout: float,
) -> Path | None:
    """优先通过 USPTO PPUBS 官方导出链路下载美国专利 PDF。"""
    normalized = _normalize_identifier(publication_number)
    if not _looks_like_us_publication_number(normalized):
        return None

    client = uspto_ppubs.PpubsClient()
    try:
        patent = client.find_by_publication_number(normalized)
    except uspto_ppubs.PpubsError as e:
        _log.warning("PPUBS lookup failed for %s: %s", normalized, e)
        return None

    if patent is None:
        _log.warning("PPUBS did not find an exact match for %s", normalized)
        return None

    try:
        return client.download_pdf(patent, out_file, timeout=timeout)
    except uspto_ppubs.PpubsError as e:
        _log.warning("PPUBS download failed for %s: %s", normalized, e)
        return None


def extract_pdf_url(
    id_or_url: str,
    *,
    timeout: float = 30.0,
) -> str | None:
    """从 Google Patents 页面提取 PDF 下载链接。

    Args:
        id_or_url: Google Patents 页面 URL 或专利 ID（如 US20240176406A1）。
        timeout: 请求超时（秒）。

    Returns:
        PDF 下载链接，未找到则返回 None。

    Raises:
        PatentFetchError: Page fetch failed.
    """
    url = _resolve_url(id_or_url)

    try:
        _log.info("Fetching patent page: %s", url)
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise PatentFetchError(f"Request timed out ({timeout}s)")
    except requests.exceptions.RequestException as e:
        raise PatentFetchError(f"Failed to fetch page: {e}")

    html = resp.text
    matches = PDF_URL_PATTERN.findall(html)

    if not matches:
        return None

    # Deduplicate while preserving order.
    seen = set()
    for candidate in matches:
        if candidate not in seen:
            seen.add(candidate)
            _log.info("Found PDF URL: %s", candidate)
            return candidate

    return None


def download_patent_pdf(
    id_or_url: str,
    *,
    output_dir: str | Path = "data/spool/inbox-patent",
    filename: str | None = None,
    timeout: float = 120.0,
    cfg: Config | None = None,
) -> Path | None:
    """下载专利 PDF。

    Args:
        id_or_url: 专利页面 URL 或专利 ID（如 US20240176406A1）。
        output_dir: 保存目录（默认 data/spool/inbox-patent）。
        filename: 自定义文件名（不含 .pdf，默认从 URL/ID 提取专利 ID）。
        timeout: 下载超时（秒）。
        cfg: 配置对象（用于解析路径）。

    Returns:
        下载文件的 Path，失败返回 None。

    Example:
        >>> path = download_patent_pdf("US20240176406A1")
        >>> path = download_patent_pdf("https://patents.google.com/patent/US20240176406A1")
    """
    url = _resolve_url(id_or_url)

    # 解析路径
    if cfg is not None:
        patent_inbox_dir = getattr(cfg, "patent_inbox_dir", None)
        if patent_inbox_dir is not None:
            output_path = Path(patent_inbox_dir)
        else:
            output_path = Path(getattr(cfg, "_root", Path.cwd())) / "data" / "spool" / "inbox-patent"
    else:
        output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    # 文件名
    patent_id = _extract_patent_id(url)
    if filename:
        out_file = output_path / f"{filename}.pdf"
    else:
        out_file = output_path / f"{patent_id}.pdf"

    # 检查是否已存在
    if out_file.exists():
        ui(f"File already exists: {out_file}")
        return out_file

    normalized_patent_id = _normalize_identifier(patent_id)

    # 优先走 USPTO PPUBS 官方导出链路
    ppubs_path = _download_via_ppubs(
        normalized_patent_id,
        out_file,
        timeout=timeout,
    )
    if ppubs_path is not None:
        ui(f"Downloaded: {ppubs_path} ({ppubs_path.stat().st_size} bytes)")
        return ppubs_path

    # 回退到 Google Patents 页面抓取
    try:
        pdf_url = extract_pdf_url(id_or_url, timeout=30.0)
    except PatentFetchError as e:
        ui(f"Error: {e}")
        return None

    if not pdf_url:
        ui("No PDF download link was found on this page")
        return None

    # 下载 PDF
    headers = {"User-Agent": "ScholarAIO/1.0 (https://github.com/ZimoLiao/scholaraio)"}

    try:
        _log.info("Downloading PDF: %s", pdf_url)
        resp = requests.get(pdf_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        out_file.write_bytes(resp.content)
        ui(f"Downloaded: {out_file} ({len(resp.content)} bytes)")
        return out_file
    except requests.exceptions.Timeout:
        ui(f"Download timed out ({timeout}s)")
        return None
    except requests.exceptions.RequestException as e:
        ui(f"Download failed: {e}")
        return None
