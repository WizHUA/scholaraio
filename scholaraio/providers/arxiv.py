"""Shared arXiv Atom API helpers used by CLI, ingest, and federated search."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import defusedxml.ElementTree as ET
import requests
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from scholaraio.core.config import Config

_log = logging.getLogger("scholaraio.sources.arxiv")

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ARXIV_LIST_RECENT_URL = "https://arxiv.org/list/{category}/recent"
_ARXIV_NEW_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_ARXIV_OLD_ID_RE = re.compile(r"^[a-z\-]+(?:\.[a-z\-]+)?/\d{7}$", re.IGNORECASE)

# Rate limit for downloads (arXiv politely asks for ~3s between requests)
RATE_LIMIT_DELAY = 3.0
_last_request_time = 0.0


def _user_agent() -> str:
    try:
        from scholaraio import __version__
    except Exception:
        __version__ = "unknown"
    return f"scholaraio/{__version__} (https://github.com/ZimoLiao/scholaraio)"


_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": _user_agent()})
_SESSION.trust_env = True
_retry = requests.adapters.HTTPAdapter(
    max_retries=Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=["GET"],
    )
)
_SESSION.mount("https://", _retry)
_SESSION.mount("http://", _retry)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ArxivError(Exception):
    """arXiv API 异常。"""

    pass


class ArxivRateLimitError(ArxivError):
    """触发速率限制。"""

    pass


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ArxivPaper:
    """arXiv 论文条目。"""

    arxiv_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    published: str = ""  # YYYY-MM-DD
    updated: str = ""  # YYYY-MM-DD
    categories: list[str] = field(default_factory=list)
    primary_category: str = ""
    pdf_url: str = ""
    entry_url: str = ""
    doi: str | None = None

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "year": self.published[:4] if self.published else "",
            "published": self.published,
            "updated": self.updated,
            "categories": self.categories,
            "primary_category": self.primary_category,
            "pdf_url": self.pdf_url,
            "entry_url": self.entry_url,
            "doi": self.doi,
        }

    def citation_key(self) -> str:
        """生成引用键 (如: Smith2023arxiv)。"""
        if self.authors:
            first_author = self.authors[0].split()[-1]
            year = self.published[:4] if self.published else "unknown"
            return f"{first_author}{year}arxiv"
        return f"arxiv{self.arxiv_id}"


# ---------------------------------------------------------------------------
# ID normalization
# ---------------------------------------------------------------------------


def normalize_arxiv_ref(ref: str) -> str:
    """Normalize an arXiv identifier / URL to a canonical ID without version suffix.

    Args:
        ref: Bare arXiv ID, ``arXiv:<id>``, or ``arxiv.org/abs|pdf/...`` URL.

    Returns:
        Canonical arXiv ID without version suffix, or an empty string if invalid.
    """
    raw = (ref or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if lowered.startswith("arxiv:"):
        raw = raw.split(":", 1)[1].strip()
    elif lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(raw)
        path = parsed.path.strip("/")
        if path.startswith("abs/"):
            raw = path[len("abs/") :]
        elif path.startswith("pdf/"):
            raw = path[len("pdf/") :]
            if raw.lower().endswith(".pdf"):
                raw = raw[:-4]
        else:
            return ""

    raw = raw.strip().rstrip("/")
    raw = re.sub(r"v\d+$", "", raw, flags=re.IGNORECASE)
    if _ARXIV_NEW_ID_RE.fullmatch(raw) or _ARXIV_OLD_ID_RE.fullmatch(raw):
        return raw
    return ""


def _pdf_filename_for_arxiv_id(arxiv_id: str) -> str:
    """Map a canonical arXiv ID to a flat PDF filename."""
    return arxiv_id.replace("/", "_") + ".pdf"


def _quote_field_term(term: str) -> str:
    """Quote multi-word field searches so arXiv treats them as one phrase."""
    stripped = term.strip()
    if not stripped:
        return ""
    if stripped.startswith('"') and stripped.endswith('"'):
        return stripped
    if any(ch.isspace() for ch in stripped):
        return f'"{stripped}"'
    return stripped


def _normalize_filter_term(term: str) -> str:
    """Normalize a field filter term for client-side result filtering."""
    stripped = term.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
    return " ".join(stripped.lower().split())


def _filter_search_results(
    results: list[dict],
    *,
    author: str = "",
    title: str = "",
    abstract: str = "",
) -> list[dict]:
    """Tighten field-scoped searches when arXiv returns loose matches."""
    author_filter = _normalize_filter_term(author)
    title_filter = _normalize_filter_term(title)
    abstract_filter = _normalize_filter_term(abstract)

    filtered: list[dict] = []
    for result in results:
        if author_filter:
            author_names = [" ".join(str(name).lower().split()) for name in result.get("authors", [])]
            if not any(author_filter in name for name in author_names):
                continue
        if title_filter:
            title_text = " ".join(str(result.get("title", "")).lower().split())
            if title_filter not in title_text:
                continue
        if abstract_filter:
            abstract_text = " ".join(str(result.get("abstract", "")).lower().split())
            if abstract_filter not in abstract_text:
                continue
        filtered.append(result)
    return filtered


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_entry(entry: ET.Element) -> dict:
    title_el = entry.find("atom:title", _NS)
    title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""

    summary_el = entry.find("atom:summary", _NS)
    abstract = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""

    year = ""
    published = ""
    pub_el = entry.find("atom:published", _NS)
    if pub_el is not None and pub_el.text:
        published = pub_el.text[:10]
        year = pub_el.text[:4]

    updated = ""
    updated_el = entry.find("atom:updated", _NS)
    if updated_el is not None and updated_el.text:
        updated = updated_el.text[:10]

    authors: list[str] = []
    for author_el in entry.findall("atom:author", _NS):
        name_el = author_el.find("atom:name", _NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text)

    arxiv_id = ""
    id_el = entry.find("atom:id", _NS)
    if id_el is not None and id_el.text:
        arxiv_id = id_el.text.strip().split("/abs/")[-1]
        # Strip version suffix for canonical ID
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)

    doi = ""
    doi_el = entry.find("arxiv:doi", _NS)
    if doi_el is not None and doi_el.text:
        doi = doi_el.text.strip()

    categories: list[str] = []
    primary_category = ""
    for cat in entry.findall("atom:category", _NS):
        term = cat.get("term", "")
        if term:
            categories.append(term)
        if cat.get("scheme") == "http://arxiv.org/schemas/atom":
            primary_category = term

    pdf_url = ""
    entry_url = ""
    for link in entry.findall("atom:link", _NS):
        rel = link.get("rel", "")
        href = link.get("href", "")
        if rel == "alternate":
            entry_url = href
        elif link.get("title") == "pdf":
            pdf_url = href
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "published": published,
        "updated": updated,
        "categories": categories,
        "primary_category": primary_category,
        "pdf_url": pdf_url,
        "entry_url": entry_url,
    }


def _entry_to_paper(entry: ET.Element) -> ArxivPaper:
    """Parse an Atom entry into an ArxivPaper dataclass."""
    data = _parse_entry(entry)
    return ArxivPaper(
        arxiv_id=data.get("arxiv_id", ""),
        title=data.get("title", ""),
        authors=data.get("authors", []),
        abstract=data.get("abstract", ""),
        published=data.get("published", ""),
        updated=data.get("updated", ""),
        categories=data.get("categories", []),
        primary_category=data.get("primary_category", ""),
        pdf_url=data.get("pdf_url", ""),
        entry_url=data.get("entry_url", ""),
        doi=data.get("doi") or None,
    )


# ---------------------------------------------------------------------------
# API queries
# ---------------------------------------------------------------------------


def _query_arxiv_api(params: dict[str, str | int]) -> list[dict]:
    try:
        resp = _SESSION.get(_ARXIV_API_URL, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv API 不可用: %s", e)
        return []

    try:
        root = ET.fromstring(resp.text)
    except Exception as e:
        _log.warning("arXiv XML 解析失败: %s", e)
        return []

    return [_parse_entry(entry) for entry in root.findall("atom:entry", _NS)]


def _query_arxiv_api_papers(params: dict[str, str | int]) -> list[ArxivPaper]:
    """Query the arXiv API and return ArxivPaper dataclasses."""
    try:
        resp = _SESSION.get(_ARXIV_API_URL, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv API 不可用: %s", e)
        return []

    try:
        root = ET.fromstring(resp.text)
    except Exception as e:
        _log.warning("arXiv XML 解析失败: %s", e)
        return []

    return [_entry_to_paper(entry) for entry in root.findall("atom:entry", _NS)]


def _build_search_query(
    query: str = "",
    category: str = "",
    author: str = "",
    title: str = "",
    abstract: str = "",
    arxiv_id: str = "",
) -> str:
    parts: list[str] = []
    query = (query or "").strip()
    category = (category or "").strip()
    author = (author or "").strip()
    title = (title or "").strip()
    abstract = (abstract or "").strip()
    arxiv_id = (arxiv_id or "").strip()

    if arxiv_id:
        return f"id:{arxiv_id}"
    if query:
        parts.append(f"all:{query}")
    if author:
        parts.append(f"au:{_quote_field_term(author)}")
    if title:
        parts.append(f"ti:{_quote_field_term(title)}")
    if abstract:
        parts.append(f"abs:{_quote_field_term(abstract)}")
    if category:
        parts.append(f"cat:{category}")
    return " AND ".join(parts) if parts else ""


def _guess_year_from_arxiv_id(arxiv_id: str) -> str:
    if _ARXIV_NEW_ID_RE.fullmatch(arxiv_id or ""):
        return f"20{arxiv_id[:2]}"
    return ""


def _load_beautiful_soup():
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as e:
        _log.warning("缺少 beautifulsoup4，无法解析 arXiv recent 页面: %s", e)
        return None
    return BeautifulSoup


def _search_arxiv_recent_page(query: str, category: str, top_k: int) -> list[dict]:
    if not category:
        return []
    try:
        resp = _SESSION.get(_ARXIV_LIST_RECENT_URL.format(category=category), timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv recent 页面不可用: %s", e)
        return []

    beautiful_soup = _load_beautiful_soup()
    if beautiful_soup is None:
        return []

    soup = beautiful_soup(resp.text, "html.parser")
    items: list[dict] = []
    for dt, dd in zip(soup.find_all("dt"), soup.find_all("dd"), strict=False):
        id_link = dt.find("a", href=re.compile(r"^/abs/"))
        if not id_link:
            continue
        arxiv_id = normalize_arxiv_ref(id_link.get_text(" ", strip=True))
        if not arxiv_id:
            href = id_link.get("href", "")
            arxiv_id = normalize_arxiv_ref(f"https://arxiv.org{href}")
        if not arxiv_id:
            continue

        title_div = dd.find("div", class_="list-title")
        authors_div = dd.find("div", class_="list-authors")
        if not title_div:
            continue
        title = title_div.get_text(" ", strip=True).replace("Title:", "", 1).strip()
        authors = [a.get_text(" ", strip=True) for a in authors_div.find_all("a")] if authors_div else []

        haystack = " ".join([title, *authors]).lower()
        if query and query.lower() not in haystack:
            continue

        items.append(
            {
                "title": title,
                "authors": authors,
                "year": _guess_year_from_arxiv_id(arxiv_id),
                "abstract": "",
                "arxiv_id": arxiv_id,
                "doi": "",
                "published": "",
                "updated": "",
                "categories": [],
                "primary_category": "",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                "entry_url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )
        if len(items) >= top_k:
            break
    return items


def _fetch_arxiv_abs_page(arxiv_id: str) -> dict:
    """Fetch metadata from the official arXiv abstract page as a fallback."""
    url = f"https://arxiv.org/abs/{arxiv_id}"
    try:
        resp = _SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv abs 页面不可用: %s", e)
        return {}

    html = resp.text
    meta_pairs = re.findall(r'<meta\s+name="([^"]+)"\s+content="([^"]*)"', html, flags=re.IGNORECASE)
    if not meta_pairs:
        return {}

    meta_map: dict[str, list[str]] = {}
    for name, content in meta_pairs:
        meta_map.setdefault(name.lower(), []).append(unescape(content).strip())

    title = (meta_map.get("citation_title") or [""])[0]
    authors = [a for a in meta_map.get("citation_author", []) if a]
    date = (meta_map.get("citation_date") or [""])[0]
    abstract = (meta_map.get("citation_abstract") or [""])[0]
    page_arxiv_id = (meta_map.get("citation_arxiv_id") or [""])[0]
    doi = (meta_map.get("citation_doi") or [""])[0]

    if not any([title, authors, date, abstract, page_arxiv_id, doi]):
        return {}

    year = ""
    published = ""
    if date:
        year = date[:4]
        published = date[:10]

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract,
        "arxiv_id": page_arxiv_id or arxiv_id,
        "doi": doi,
        "published": published,
        "updated": "",
        "categories": [],
        "primary_category": "",
        "pdf_url": f"https://arxiv.org/pdf/{(page_arxiv_id or arxiv_id)}.pdf",
        "entry_url": f"https://arxiv.org/abs/{(page_arxiv_id or arxiv_id)}",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_arxiv_paper(arxiv_ref: str) -> dict:
    """Fetch authoritative metadata for a single arXiv paper via the Atom API.

    Args:
        arxiv_ref: arXiv ID or URL.

    Returns:
        Simplified paper dict with keys ``title``, ``authors``, ``year``,
        ``abstract``, ``arxiv_id``, ``doi``. Returns an empty dict on failure.
    """
    canonical_id = normalize_arxiv_ref(arxiv_ref)
    if not canonical_id:
        return {}
    results = _query_arxiv_api({"id_list": canonical_id})
    if results:
        return results[0]
    return _fetch_arxiv_abs_page(canonical_id)


def get_paper_by_id(arxiv_id: str, cfg: Config | None = None) -> ArxivPaper | None:
    """通过 ID 获取单篇论文详情（返回 ArxivPaper dataclass）。"""
    try:
        papers = _query_arxiv_api_papers({"id_list": arxiv_id, "max_results": 1})
        return papers[0] if papers else None
    except Exception:
        return None


def search_arxiv(
    query: str = "",
    top_k: int = 10,
    *,
    category: str = "",
    author: str = "",
    title: str = "",
    abstract: str = "",
    arxiv_id: str = "",
    id_list: list[str] | None = None,
    start: int = 0,
    sort: str = "relevance",
    sort_order: str = "descending",
) -> list[dict]:
    """Query the arXiv Atom API and return a list of simplified paper dicts.

    Args:
        query: Free-text search query.
        top_k: Maximum number of results to return.
        category: Optional arXiv category, e.g. ``physics.flu-dyn``.
        author: Author search field.
        title: Title search field.
        abstract: Abstract search field.
        arxiv_id: Single arXiv ID search.
        id_list: List of arXiv IDs to fetch directly.
        start: Pagination offset.
        sort: ``"relevance"`` or ``"recent"``.
        sort_order: ``"ascending"`` or ``"descending"``.

    Returns:
        List of dicts. Returns an empty list on network failure or XML parse error.
    """
    use_recent_page_fallback = (
        sort == "recent" and bool(category) and not any([author, title, abstract, arxiv_id, id_list])
    )

    if id_list:
        params: dict[str, str | int] = {
            "id_list": ",".join(id_list),
            "start": start,
            "max_results": top_k,
        }
    else:
        search_query = _build_search_query(
            query=query,
            category=category,
            author=author,
            title=title,
            abstract=abstract,
            arxiv_id=arxiv_id,
        )
        if not search_query:
            return []
        sort_by = "submittedDate" if sort == "recent" else "relevance"
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": top_k,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
    results = _query_arxiv_api(params)
    if results and (author or title or abstract):
        results = _filter_search_results(results, author=author, title=title, abstract=abstract)
    if results or not use_recent_page_fallback:
        return results
    return _search_arxiv_recent_page(query, category, top_k)


def search_and_display(
    query: str | None = None,
    *,
    max_results: int = 10,
    **kwargs,
) -> list[dict]:
    """搜索 arXiv 并输出到 UI。"""
    from scholaraio.core.log import ui

    try:
        papers = search_arxiv(query=query or "", top_k=max_results, **kwargs)
    except Exception as e:
        ui(f"arXiv 搜索失败: {e}")
        return []

    if not papers:
        ui(f"未找到与 '{query}' 相关的 arXiv 论文")
        return []

    ui(f"找到 {len(papers)} 篇 arXiv 论文：")
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p.get("authors", [])[:3])
        if len(p.get("authors", [])) > 3:
            authors += " et al."
        year = (p.get("published") or "")[:4] or "unknown"
        arxiv_id = p.get("arxiv_id", "")
        print(f"\n[{i}] arXiv:{arxiv_id} ({year})")
        print(f"    Title: {p.get('title', '')}")
        print(f"    Authors: {authors}")
        cats = ", ".join(p.get("categories", [])[:3])
        if cats:
            print(f"    Categories: {cats}")
        pdf = p.get("pdf_url", "")
        if pdf:
            print(f"    PDF: {pdf}")

    return papers


def download_arxiv_pdf(arxiv_ref: str, dest_dir: str | Path, *, overwrite: bool = False) -> Path:
    """Download an arXiv PDF to *dest_dir* and return the local file path."""
    canonical_id = normalize_arxiv_ref(arxiv_ref)
    if not canonical_id:
        raise ValueError(f"无效的 arXiv 标识: {arxiv_ref}")

    dest_root = Path(dest_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    out_path = dest_root / _pdf_filename_for_arxiv_id(canonical_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在: {out_path}")
    tmp_path = out_path.with_name(out_path.name + ".part")
    tmp_path.unlink(missing_ok=True)

    url = f"https://arxiv.org/pdf/{canonical_id}.pdf"
    resp = _SESSION.get(url, timeout=30, stream=True)
    resp.raise_for_status()
    try:
        with tmp_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
        tmp_path.replace(out_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return out_path


def batch_download(
    arxiv_ids: list[str],
    *,
    output_dir: str | Path = "data/spool/inbox",
    cfg: Config | None = None,
) -> list[Path]:
    """批量下载 arXiv PDF。"""
    global _last_request_time

    if cfg is not None:
        output_path = cfg._root / output_dir
    else:
        output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    for arxiv_id in arxiv_ids:
        canonical = normalize_arxiv_ref(arxiv_id)
        if not canonical:
            continue
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_LIMIT_DELAY and len(arxiv_ids) > 1:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        _last_request_time = time.time()

        try:
            path = download_arxiv_pdf(canonical, output_path, overwrite=False)
            downloaded.append(path)
        except FileExistsError:
            _log.info("文件已存在，跳过: %s", canonical)
        except Exception as e:
            _log.warning("下载失败 %s: %s", canonical, e)

    return downloaded
