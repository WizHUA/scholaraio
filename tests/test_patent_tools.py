from __future__ import annotations

import urllib.request
from types import SimpleNamespace

import pytest

from scholaraio.core.config import _build_config
from scholaraio.providers import uspto_odp
from scholaraio.providers.uspto_ppubs import PpubsClient, PpubsPatent, _extract_patent
from scholaraio.services import patent_fetch


class TestPatentConfig:
    def test_build_config_wires_patent_api_key(self, tmp_path):
        cfg = _build_config(
            {"patent": {"uspto_odp_api_key": "cfg-key"}},
            tmp_path,
        )

        assert cfg.patent.uspto_odp_api_key == "cfg-key"
        assert cfg.resolved_uspto_odp_api_key() == "cfg-key"


class TestPpubsClient:
    def test_client_uses_cookie_processor_for_session_bootstrap(self):
        client = PpubsClient()

        assert any(isinstance(handler, urllib.request.HTTPCookieProcessor) for handler in client._opener.handlers)

    def test_request_bytes_retries_after_transient_urlerror(self, monkeypatch):
        client = PpubsClient()
        client._token = "token"
        client._case_id = 123
        attempts = {"count": 0}

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_open(request):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise urllib.error.URLError(OSError(104, "Connection reset by peer"))
            return DummyResponse()

        monkeypatch.setattr(client._opener, "open", fake_open)

        assert client._request_bytes("GET", "https://example.com") == b"{}"
        assert attempts["count"] == 2


class TestPpubsPatentExtraction:
    def test_pregrant_publication_uses_returned_kind_code(self):
        patent = _extract_patent(
            {
                "publicationReferenceDocumentNumber": "20240012345",
                "type": "US-PGPUB",
                "kindCode": ["A9"],
                "inventionTitle": "Demo",
            }
        )

        assert patent.publication_number == "US20240012345A9"

    def test_extracts_image_location_for_pdf_download(self):
        patent = _extract_patent(
            {
                "guid": "US-20260104498-A1",
                "publicationReferenceDocumentNumber": "20260104498",
                "type": "US-PGPUB",
                "kindCode": ["A1"],
                "imageLocation": "us-pgpub/US/2026/0104/498",
                "pageCount": 62,
            }
        )

        assert patent.image_location == "us-pgpub/US/2026/0104/498"

    def test_strips_html_highlight_markup_from_titles(self):
        patent = _extract_patent(
            {
                "publicationReferenceDocumentNumber": "20260106892",
                "type": "US-PGPUB",
                "kindCode": ["A1"],
                "inventionTitle": (
                    "Distributed Endpoint Security Architecture Enabled by "
                    '<span term=""artificial"" class="highlight18">Artificial</span> '
                    '<span term=""intelligence"" class="highlight18">Intelligence</span>'
                ),
            }
        )

        assert patent.title == "Distributed Endpoint Security Architecture Enabled by Artificial Intelligence"


class TestPpubsPdfDownload:
    def test_find_by_publication_number_uses_numeric_lookup_and_exact_match(self, monkeypatch):
        client = PpubsClient()
        seen_queries = []
        target = PpubsPatent(publication_number="US20260104498A1")

        def fake_search(query, *, start=0, limit=10, sort="date_publ desc", sources=None):
            seen_queries.append(query)
            if query == "20260104498":
                return 1, [target]
            return 0, []

        monkeypatch.setattr(client, "search", fake_search)

        patent = client.find_by_publication_number("US20260104498A1")

        assert patent is target
        assert seen_queries == ["20260104498"]

    def test_download_pdf_runs_ppubs_print_save_flow(self, tmp_path, monkeypatch):
        client = PpubsClient()
        client._token = "mock-token"
        client._case_id = 12345
        calls = []
        patent = PpubsPatent(
            guid="US-20260104498-A1",
            publication_number="US20260104498A1",
            patent_type="US-PGPUB",
            page_count=2,
            image_location="us-pgpub/US/2026/0104/498",
        )

        def fake_request_text(method, url, data=None):
            calls.append((method, url, data))
            return "3683401"

        def fake_request_json(method, url, data=None):
            calls.append((method, url, data))
            return [
                {
                    "printStatus": "COMPLETED",
                    "pdfName": "demo.pdf",
                }
            ]

        def fake_request_bytes(method, url):
            calls.append((method, url, None))
            return b"%PDF-1.7\nmock pdf\n"

        monkeypatch.setattr(client, "_request_text", fake_request_text)
        monkeypatch.setattr(client, "_request_json", fake_request_json)
        monkeypatch.setattr(client, "_request_bytes", fake_request_bytes)

        out_file = tmp_path / "US20260104498A1.pdf"
        result = client.download_pdf(patent, out_file)

        assert result == out_file
        assert out_file.read_bytes() == b"%PDF-1.7\nmock pdf\n"
        assert calls[0] == (
            "POST",
            "https://ppubs.uspto.gov/api/print/imageviewer",
            {
                "caseId": client._case_id,
                "pageKeys": [
                    "us-pgpub/US/2026/0104/498/00000001.tif",
                    "us-pgpub/US/2026/0104/498/00000002.tif",
                ],
                "patentGuid": "US-20260104498-A1",
                "saveOrPrint": "save",
                "source": "US-PGPUB",
            },
        )
        assert calls[1] == (
            "POST",
            "https://ppubs.uspto.gov/api/print/print-process",
            ["3683401"],
        )
        assert calls[2] == (
            "GET",
            "https://ppubs.uspto.gov/api/print/save/demo.pdf",
            None,
        )


class TestUSPTOODP:
    def test_clean_publication_number_removes_spaces_and_hyphens(self):
        assert uspto_odp._clean_publication_number("US 2021-0123456 A1") == "US20210123456A1"

    def test_extract_patent_result_maps_metadata_to_search_and_meta_fields(self):
        patent = uspto_odp._extract_patent_result(
            {
                "applicationNumberText": "17123456",
                "applicationMetaData": {
                    "inventionTitle": "Demo Patent",
                    "inventorBag": [{"firstName": "Ada", "lastName": "Lovelace"}],
                    "applicantBag": [{"applicantName": "Example Inc."}],
                    "filingDate": "2020-01-02",
                    "grantDate": "2023-04-05",
                    "publicationDateBag": ["2021-06-07"],
                    "patentNumber": "12345678",
                    "earliestPublicationNumber": "US 2021-0123456 A1",
                    "applicationStatusDescriptionText": "Published",
                    "applicationTypeLabelName": "Utility",
                },
            }
        )

        assert patent.application_number == "17123456"
        assert patent.inventors == ["Ada Lovelace"]
        assert patent.applicants == ["Example Inc."]
        assert patent.publication_number == "US20210123456A1"

        meta = patent.to_meta_dict()
        assert meta["paper_type"] == "patent"
        assert meta["year"] == 2023
        assert meta["ids"]["patent_publication_number"] == "US20210123456A1"
        assert meta["ids"]["uspto_application_number"] == "17123456"

    def test_search_patents_uses_configured_api_key_and_caps_page_size(self, monkeypatch):
        captured = {}

        class FakeConfig:
            def resolved_uspto_odp_api_key(self):
                return "cfg-key"

        def fake_request_json(url, *, api_key=None, method="GET", data=None, timeout=30.0):
            captured.update(
                {
                    "url": url,
                    "api_key": api_key,
                    "method": method,
                    "data": data,
                    "timeout": timeout,
                }
            )
            return {
                "count": 1,
                "patentFileWrapperDataBag": [
                    {
                        "applicationNumberText": "17123456",
                        "applicationMetaData": {"inventionTitle": "Demo Patent"},
                    }
                ],
            }

        monkeypatch.setattr(uspto_odp, "_request_json", fake_request_json)

        results = uspto_odp.search_patents(
            "artificial intelligence",
            limit=250,
            offset=4,
            base_url="https://example.test/",
            timeout=7.0,
            cfg=FakeConfig(),
        )

        assert len(results) == 1
        assert captured["url"] == "https://example.test/api/v1/patent/applications/search"
        assert captured["api_key"] == "cfg-key"
        assert captured["method"] == "POST"
        assert captured["timeout"] == 7.0
        assert captured["data"]["q"] == "artificial intelligence"
        assert captured["data"]["pagination"] == {"offset": 4, "limit": 100}

    def test_search_patents_requires_api_key(self):
        with pytest.raises(uspto_odp.USPTOAPIError, match="缺少 USPTO ODP API Key"):
            uspto_odp.search_patents("artificial intelligence")


class TestPatentFetch:
    def test_download_patent_pdf_prefers_ppubs_for_us_publication_numbers(self, tmp_path, monkeypatch):
        patent = PpubsPatent(publication_number="US20260104498A1")

        class FakeClient:
            def find_by_publication_number(self, publication_number):
                assert publication_number == "US20260104498A1"
                return patent

            def download_pdf(self, match, out_file, timeout=120.0):
                assert match is patent
                out_file.write_bytes(b"%PDF-1.7\nppubs\n")
                return out_file

        monkeypatch.setattr(patent_fetch.uspto_ppubs, "PpubsClient", lambda: FakeClient())
        monkeypatch.setattr(
            patent_fetch,
            "extract_pdf_url",
            lambda *args, **kwargs: pytest.fail("Google fallback should not be used"),
        )

        result = patent_fetch.download_patent_pdf(
            "US20260104498A1",
            output_dir=tmp_path,
        )

        assert result == tmp_path / "US20260104498A1.pdf"
        assert result.read_bytes() == b"%PDF-1.7\nppubs\n"

    def test_download_patent_pdf_uses_configured_patent_inbox_dir(self, tmp_path, monkeypatch):
        patent = PpubsPatent(publication_number="US20260104498A1")

        class FakeClient:
            def find_by_publication_number(self, publication_number):
                assert publication_number == "US20260104498A1"
                return patent

            def download_pdf(self, match, out_file, timeout=120.0):
                assert match is patent
                out_file.write_bytes(b"%PDF-1.7\nppubs\n")
                return out_file

        monkeypatch.setattr(patent_fetch.uspto_ppubs, "PpubsClient", lambda: FakeClient())
        monkeypatch.setattr(
            patent_fetch,
            "extract_pdf_url",
            lambda *args, **kwargs: pytest.fail("Google fallback should not be used"),
        )

        custom_inbox = tmp_path / "queues" / "patent-inbox"
        cfg = SimpleNamespace(_root=tmp_path, patent_inbox_dir=custom_inbox)

        result = patent_fetch.download_patent_pdf(
            "US20260104498A1",
            cfg=cfg,
        )

        assert result == custom_inbox / "US20260104498A1.pdf"
        assert result.read_bytes() == b"%PDF-1.7\nppubs\n"
        assert not (tmp_path / "data" / "inbox-patent" / "US20260104498A1.pdf").exists()
