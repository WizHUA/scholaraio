"""
uspto_ppubs.py — USPTO Patent Public Search (PPUBS) 客户端
=========================================================

通过 ppubs.uspto.gov 进行美国专利搜索，**无需 API Key**。

本模块基于对 USPTO Public Search Web UI 的逆向工程实现：
1. 访问 /pubwebapp/ 获取初始 Cookie
2. POST /api/users/me/session 获取临时会话 (case_id + X-Access-Token)
3. POST /api/searches/searchWithBeFamily 执行搜索

注意：PPUBS 是 Web 会话型接口，临时令牌会过期（约 30 分钟），
调用方无需关心，本客户端会在需要时自动刷新会话。

用法::

    from scholaraio.providers.uspto_ppubs import PpubsClient, search_patents
    results = search_patents("artificial intelligence", limit=10)
"""

from __future__ import annotations

import http.cookiejar
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any

_log = logging.getLogger("scholaraio.uspto_ppubs")

PPUBS_BASE_URL = "https://ppubs.uspto.gov"
US_PUBLICATION_NUMBER_PATTERN = re.compile(
    r"^US(?P<number>\d{6,})(?P<kind>[A-Z]\d?)?$",
    re.IGNORECASE,
)


class PpubsError(Exception):
    """PPUBS 请求异常。"""

    pass


@dataclass
class PpubsPatent:
    """PPUBS 专利搜索结果条目。"""

    guid: str = ""
    publication_number: str = ""  # e.g. "US20260101103A1" or "US10123456B2"
    title: str = ""
    inventors_short: str = ""  # raw string like "Smith; John et al."
    applicants: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    application_number: str = ""  # e.g. "14/925737"
    filing_date: str = ""  # YYYY-MM-DD
    publication_date: str = ""  # YYYY-MM-DD
    patent_type: str = ""  # US-PGPUB or USPAT
    page_count: int = 0
    image_location: str = ""
    ipc_codes: list[str] = field(default_factory=list)
    cpc_codes: list[str] = field(default_factory=list)
    primary_examiner: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def inventors(self) -> list[str]:
        """从 inventors_short 解析发明人列表。"""
        if not self.inventors_short:
            return []
        # "Evans; Jeremy T. et al." -> ["Jeremy T. Evans"]
        # 也可能返回多个用逗号分隔
        text = self.inventors_short.replace(" et al.", "").strip()
        parts = [p.strip() for p in text.split(",") if p.strip()]
        result = []
        for part in parts:
            if ";" in part:
                last, first = part.split(";", 1)
                result.append(f"{first.strip()} {last.strip()}")
            else:
                result.append(part)
        return result

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "publication_number": self.publication_number,
            "title": self.title,
            "inventors": self.inventors,
            "applicants": self.applicants,
            "assignees": self.assignees,
            "application_number": self.application_number,
            "filing_date": self.filing_date,
            "publication_date": self.publication_date,
            "patent_type": self.patent_type,
            "page_count": self.page_count,
            "image_location": self.image_location,
            "ipc_codes": self.ipc_codes,
            "cpc_codes": self.cpc_codes,
        }

    def google_patents_url(self) -> str:
        """生成 Google Patents 链接。"""
        return f"https://patents.google.com/patent/{self.publication_number}/en"

    def uspto_pair_url(self) -> str:
        """生成 USPTO PAIR 链接（按申请号）。"""
        # 去掉斜杠和空格
        app = self.application_number.replace("/", "").replace(" ", "")
        return f"https://portal.uspto.gov/pair/PublicPair?applicationNumber={app}"


class PpubsClient:
    """USPTO PPUBS 会话客户端。

    自动管理 Cookie、会话创建和令牌刷新。
    """

    def __init__(self, base_url: str = PPUBS_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cookie_jar))
        self._token: str | None = None
        self._case_id: int | None = None

    def _ensure_session(self) -> None:
        """确保已建立有效会话。"""
        if self._token and self._case_id:
            return

        _log.debug("Establishing new PPUBS session")

        # Step 1: Get landing page cookies
        req1 = urllib.request.Request(
            f"{self.base_url}/pubwebapp/",
            method="GET",
        )
        req1.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self._opener.open(req1)

        # Step 2: Create session
        req2 = urllib.request.Request(
            f"{self.base_url}/api/users/me/session",
            data=b"-1",
            method="POST",
        )
        req2.add_header("X-Access-Token", "null")
        req2.add_header("referer", f"{self.base_url}/pubwebapp/")
        req2.add_header("Content-Type", "application/json")

        try:
            with self._opener.open(req2) as resp:
                session = json.loads(resp.read().decode("utf-8"))
                self._case_id = session["userCase"]["caseId"]
                self._token = resp.headers.get("X-Access-Token")
        except (urllib.error.HTTPError, KeyError) as e:
            raise PpubsError(f"Failed to establish PPUBS session: {e}") from e

        if not self._token or not self._case_id:
            raise PpubsError("PPUBS session returned empty token or caseId")

        _log.debug("PPUBS session established: caseId=%s", self._case_id)

    def _request_bytes(
        self,
        method: str,
        url: str,
        data: dict | list | None = None,
    ) -> bytes:
        """执行带自动会话刷新的请求并返回原始 bytes。"""
        self._ensure_session()

        body = json.dumps(data).encode("utf-8") if data is not None else None
        for attempt in range(3):
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("X-Access-Token", self._token or "")
            req.add_header(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            req.add_header("referer", f"{self.base_url}/pubwebapp/")
            req.add_header("Origin", self.base_url)
            req.add_header("X-Requested-With", "XMLHttpRequest")
            if data is not None:
                req.add_header("Content-Type", "application/json")

            try:
                with self._opener.open(req) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 403 and attempt < 2:
                    _log.debug("PPUBS session expired, refreshing")
                    self._token = None
                    self._case_id = None
                    self._ensure_session()
                    continue
                try:
                    detail = e.read().decode("utf-8", "replace")
                except Exception:
                    detail = ""
                raise PpubsError(f"HTTP {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                if attempt == 0:
                    _log.debug("Transient PPUBS request failure, retrying: %s", e.reason)
                    time.sleep(0.2)
                    continue
                raise PpubsError(f"Request failed: {e.reason}") from e

        raise PpubsError("PPUBS request failed after session refresh")

    def _request_text(
        self,
        method: str,
        url: str,
        data: dict | list | None = None,
    ) -> str:
        """执行请求并返回 UTF-8 文本。"""
        return self._request_bytes(method, url, data).decode("utf-8", "replace")

    def _request_json(
        self,
        method: str,
        url: str,
        data: dict | list | None = None,
    ) -> dict | list:
        """执行请求并返回 JSON。"""
        try:
            return json.loads(self._request_text(method, url, data))
        except json.JSONDecodeError as e:
            raise PpubsError(f"Invalid JSON response: {e}") from e

    def _request(self, method: str, url: str, data: dict | None = None) -> dict:
        """执行带自动会话刷新的 JSON 请求。"""
        result = self._request_json(method, url, data)
        if not isinstance(result, dict):
            raise PpubsError(f"Expected JSON object from PPUBS, got {type(result).__name__}")
        return result

    def search(
        self,
        query: str,
        *,
        start: int = 0,
        limit: int = 10,
        sort: str = "date_publ desc",
        sources: list[str] | None = None,
    ) -> tuple[int, list[PpubsPatent]]:
        """搜索专利。

        Args:
            query: 搜索查询字符串（支持 PPUBS 语法，如 `(\"10123456\").pn.`）。
            start: 分页起始位置。
            limit: 每页结果数。
            sort: 排序方式。
            sources: 数据源列表，默认包含 US-PGPUB、USPAT、USOCR。

        Returns:
            (total_hits, PpubsPatent 列表)
        """
        if sources is None:
            sources = ["US-PGPUB", "USPAT", "USOCR"]

        self._ensure_session()

        query_data: dict[str, Any] = {
            "caseId": self._case_id,
            "hl_snippets": "2",
            "op": "OR",
            "q": query,
            "queryName": query,
            "highlights": "1",
            "qt": "brs",
            "spellCheck": False,
            "viewName": "tile",
            "plurals": True,
            "britishEquivalents": True,
            "databaseFilters": [{"databaseName": s, "countryCodes": []} for s in sources],
            "searchType": 1,
            "ignorePersist": True,
            "userEnteredQuery": query,
        }

        search_payload: dict[str, Any] = {
            "start": start,
            "pageCount": min(max(limit, 1), 100),
            "sort": sort,
            "docFamilyFiltering": "familyIdFiltering",
            "searchType": 1,
            "familyIdEnglishOnly": True,
            "familyIdFirstPreferred": "US-PGPUB",
            "familyIdSecondPreferred": "USPAT",
            "familyIdThirdPreferred": "FPRS",
            "showDocPerFamilyPref": "showEnglish",
            "queryId": 0,
            "tagDocSearch": False,
            "query": query_data,
        }

        _log.debug("PPUBS search: query=%r start=%d limit=%d", query, start, limit)

        # Execute search directly (counts are included in search response)
        url = f"{self.base_url}/api/searches/searchWithBeFamily"
        result = self._request("POST", url, search_payload)

        patents = result.get("patents") or []
        total = result.get("numFound", 0)

        _log.debug("PPUBS returned %d / %d results", len(patents), total)
        return total, [_extract_patent(p) for p in patents]

    def find_by_publication_number(
        self,
        publication_number: str,
        *,
        limit: int = 10,
    ) -> PpubsPatent | None:
        """按公开号定位唯一专利条目。"""
        normalized = _normalize_publication_number(publication_number)
        if not normalized:
            return None

        query = _publication_search_query(normalized)
        _, results = self.search(query, limit=limit)
        for patent in results:
            if _normalize_publication_number(patent.publication_number) == normalized:
                return patent
        return None

    def download_pdf(
        self,
        patent: PpubsPatent,
        out_file: str | Path,
        *,
        timeout: float = 120.0,
        poll_interval: float = 1.0,
    ) -> Path:
        """通过 PPUBS 官方导出接口下载 PDF。"""
        self._ensure_session()

        if not patent.guid:
            raise PpubsError("PPUBS patent entry is missing guid")
        if not patent.image_location:
            raise PpubsError("PPUBS patent entry is missing imageLocation")
        if patent.page_count <= 0:
            raise PpubsError("PPUBS patent entry returned invalid pageCount")

        page_keys = [f"{patent.image_location}/{i:08d}.tif" for i in range(1, patent.page_count + 1)]
        job_id = (
            self._request_text(
                "POST",
                f"{self.base_url}/api/print/imageviewer",
                {
                    "caseId": self._case_id,
                    "pageKeys": page_keys,
                    "patentGuid": patent.guid,
                    "saveOrPrint": "save",
                    "source": patent.patent_type,
                },
            )
            .strip()
            .strip('"')
        )
        if not job_id:
            raise PpubsError("PPUBS print job did not return a job id")

        deadline = time.monotonic() + timeout
        pdf_name = ""
        while time.monotonic() < deadline:
            status_data = self._request_json(
                "POST",
                f"{self.base_url}/api/print/print-process",
                [job_id],
            )
            if not isinstance(status_data, list) or not status_data:
                raise PpubsError("PPUBS print status returned an empty response")

            status = status_data[0]
            if status.get("printStatus") == "COMPLETED" and status.get("pdfName"):
                pdf_name = str(status["pdfName"])
                break
            if status.get("printStatus") == "FAILED":
                raise PpubsError(f"PPUBS print job failed: {status}")
            time.sleep(poll_interval)

        if not pdf_name:
            raise PpubsError("Timed out waiting for PPUBS PDF export")

        pdf_bytes = self._request_bytes(
            "GET",
            f"{self.base_url}/api/print/save/{pdf_name}",
        )
        out_path = Path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf_bytes)
        return out_path


def _normalize_publication_number(publication_number: str) -> str:
    """标准化公开号，移除分隔符并转成大写。"""
    return re.sub(r"[^A-Za-z0-9]", "", str(publication_number or "")).upper()


def _publication_search_query(publication_number: str) -> str:
    """生成更稳定的 PPUBS 检索词。"""
    normalized = _normalize_publication_number(publication_number)
    match = US_PUBLICATION_NUMBER_PATTERN.match(normalized)
    if match:
        return match.group("number")
    return normalized


def _strip_markup(text: str) -> str:
    """移除 PPUBS 返回的高亮 HTML 标记。"""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", unescape(plain)).strip()


def _extract_patent(item: dict) -> PpubsPatent:
    """从 PPUBS 搜索响应中提取 PpubsPatent。"""
    # Build clean publication number
    doc_id = item.get("documentId", "")  # e.g. "US 10123456 B2"
    pub_num_raw = str(item.get("publicationReferenceDocumentNumber", "")).strip()
    patent_type = item.get("type", "")

    publication_number = ""
    if pub_num_raw and patent_type:
        kind = ""
        if item.get("kindCode"):
            kind = item["kindCode"][0] if isinstance(item["kindCode"], list) else item["kindCode"]
        if patent_type == "US-PGPUB":
            publication_number = f"US{pub_num_raw}{kind or 'A1'}"
        elif patent_type == "USPAT":
            publication_number = f"US{pub_num_raw}{kind or 'B2'}"
        else:
            publication_number = f"US{pub_num_raw}{kind}"

    # Parse dates
    pub_date = item.get("datePublished", "")
    if pub_date:
        pub_date = pub_date[:10]  # YYYY-MM-DD
    filing_date = ""
    if item.get("applicationFilingDate"):
        filing_date = (
            item["applicationFilingDate"][0][:10]
            if isinstance(item["applicationFilingDate"], list)
            else str(item["applicationFilingDate"])[:10]
        )

    # IPC / CPC
    ipc = []
    if item.get("ipcCodeFlattened"):
        ipc = [c.strip() for c in str(item["ipcCodeFlattened"]).split(";") if c.strip()]
    cpc = []
    if item.get("cpcInventiveFlattened"):
        cpc = [c.strip() for c in str(item["cpcInventiveFlattened"]).split(";") if c.strip()]

    applicants = []
    if item.get("applicantName"):
        applicants = item["applicantName"] if isinstance(item["applicantName"], list) else [item["applicantName"]]

    assignees = []
    if item.get("assigneeName"):
        assignees = item["assigneeName"] if isinstance(item["assigneeName"], list) else [item["assigneeName"]]

    return PpubsPatent(
        guid=item.get("guid", ""),
        publication_number=publication_number,
        title=_strip_markup(str(item.get("inventionTitle", ""))),
        inventors_short=item.get("inventorsShort", ""),
        applicants=applicants,
        assignees=assignees,
        application_number=str(item.get("applicationNumber", "")),
        filing_date=filing_date,
        publication_date=pub_date,
        patent_type=patent_type,
        page_count=int(item.get("pageCount", 0) or 0),
        image_location=str(item.get("imageLocation", "")),
        ipc_codes=ipc,
        cpc_codes=cpc,
        primary_examiner=str(item.get("primaryExaminer", "")),
        raw=item,
    )


def search_patents(
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[PpubsPatent]:
    """便捷函数：无需 API Key 搜索 USPTO 专利。

    Args:
        query: 搜索查询字符串。
        limit: 返回结果数量上限（默认 10）。
        offset: 分页偏移（默认 0）。

    Returns:
        PpubsPatent 列表。
    """
    client = PpubsClient()
    _, results = client.search(query, start=offset, limit=limit)
    return results
