"""Fault-injection tests for metadata API retry logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import call, patch

from scholaraio.services.ingest_metadata._api import (
    _query_crossref_relaxed,
    _query_oa_relaxed,
    _request_with_retry,
    query_crossref,
    query_openalex,
    query_semantic_scholar,
)


class TestRequestWithRetry:
    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    def test_success_on_first_attempt(self, mock_session):
        mock_session.get.return_value = SimpleNamespace(status_code=200)
        resp = _request_with_retry("http://example.com/test")
        assert resp.status_code == 200
        assert mock_session.get.call_count == 1

    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    @patch("scholaraio.services.ingest_metadata._api.time.sleep")
    def test_retries_429_with_retry_after(self, mock_sleep, mock_session):
        mock_session.get.side_effect = [
            SimpleNamespace(status_code=429, headers={"Retry-After": "3"}),
            SimpleNamespace(status_code=200),
        ]
        resp = _request_with_retry("http://example.com/test")
        assert resp.status_code == 200
        assert mock_session.get.call_count == 2
        mock_sleep.assert_called_once_with(3)

    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    @patch("scholaraio.services.ingest_metadata._api.time.sleep")
    def test_retries_429_with_exponential_backoff(self, mock_sleep, mock_session):
        mock_session.get.side_effect = [
            SimpleNamespace(status_code=429, headers={}),
            SimpleNamespace(status_code=429, headers={}),
            SimpleNamespace(status_code=200),
        ]
        resp = _request_with_retry("http://example.com/test")
        assert resp.status_code == 200
        assert mock_session.get.call_count == 3
        assert mock_sleep.call_args_list == [call(1), call(2)]

    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    @patch("scholaraio.services.ingest_metadata._api.time.sleep")
    def test_retries_503_with_exponential_backoff(self, mock_sleep, mock_session):
        mock_session.get.side_effect = [
            SimpleNamespace(status_code=503, headers={}),
            SimpleNamespace(status_code=503, headers={}),
            SimpleNamespace(status_code=200),
        ]
        resp = _request_with_retry("http://example.com/test")
        assert resp.status_code == 200
        assert mock_session.get.call_count == 3
        assert mock_sleep.call_args_list == [call(1), call(2)]

    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    @patch("scholaraio.services.ingest_metadata._api.time.sleep")
    def test_returns_last_response_after_max_retries(self, mock_sleep, mock_session):
        mock_session.get.return_value = SimpleNamespace(status_code=429, headers={})
        resp = _request_with_retry("http://example.com/test", max_retries=2)
        assert resp.status_code == 429
        assert mock_session.get.call_count == 3  # initial + 2 retries
        assert mock_sleep.call_args_list == [call(1), call(2)]

    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    @patch("scholaraio.services.ingest_metadata._api.time.sleep")
    def test_retry_after_capped_at_30(self, mock_sleep, mock_session):
        mock_session.get.side_effect = [
            SimpleNamespace(status_code=429, headers={"Retry-After": "100"}),
            SimpleNamespace(status_code=200),
        ]
        resp = _request_with_retry("http://example.com/test")
        assert resp.status_code == 200
        mock_sleep.assert_called_once_with(30)

    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    @patch("scholaraio.services.ingest_metadata._api.time.sleep")
    def test_invalid_retry_after_falls_back_to_backoff(self, mock_sleep, mock_session):
        mock_session.get.side_effect = [
            SimpleNamespace(status_code=429, headers={"Retry-After": "not-a-number"}),
            SimpleNamespace(status_code=200),
        ]
        resp = _request_with_retry("http://example.com/test")
        assert resp.status_code == 200
        mock_sleep.assert_called_once_with(1)


class TestQuerySemanticScholarRetry:
    @patch("scholaraio.services.ingest_metadata._api._request_with_retry")
    def test_uses_retry_helper(self, mock_retry):
        mock_retry.return_value = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"title": "Test"},
        )
        result = query_semantic_scholar(doi="10.1234/x")
        assert result["title"] == "Test"
        mock_retry.assert_called_once()


class TestQueryOpenAlexRetry:
    @patch("scholaraio.services.ingest_metadata._api._request_with_retry")
    def test_uses_retry_helper(self, mock_retry):
        mock_retry.return_value = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"results": [{"title": "Test"}]},
        )
        result = query_openalex(title="Test")
        assert result["title"] == "Test"
        mock_retry.assert_called_once()

    @patch("scholaraio.services.ingest_metadata._api._request_with_retry")
    def test_appends_api_key_from_config(self, mock_retry):
        mock_retry.return_value = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"results": [{"title": "Test"}]},
        )
        with patch(
            "scholaraio.core.config.load_config",
            return_value=SimpleNamespace(openalex=SimpleNamespace(api_key="secret-key")),
        ):
            query_openalex(title="Test")
        called_url = mock_retry.call_args.args[0]
        assert "api_key=secret-key" in called_url


class TestQueryCrossrefRetry:
    @patch("scholaraio.services.ingest_metadata._api._request_with_retry")
    def test_uses_retry_helper(self, mock_retry):
        mock_retry.return_value = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"message": {"DOI": "10.1234/x"}},
        )
        result = query_crossref(doi="10.1234/x")
        assert result["DOI"] == "10.1234/x"
        mock_retry.assert_called_once()


class TestRelaxedQueryRetry:
    @patch("scholaraio.services.ingest_metadata._api._request_with_retry")
    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    def test_crossref_relaxed_uses_retry_helper(self, mock_session, mock_retry):
        mock_session.get.side_effect = AssertionError("should use retry helper")
        mock_retry.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {"message": {"items": [{"title": ["Test paper"]}]}},
        )
        result = _query_crossref_relaxed("Test paper")
        assert result["title"] == ["Test paper"]
        mock_retry.assert_called_once()

    @patch("scholaraio.services.ingest_metadata._api._request_with_retry")
    @patch("scholaraio.services.ingest_metadata._api.SESSION")
    def test_openalex_relaxed_uses_retry_helper_and_api_key(self, mock_session, mock_retry):
        mock_session.get.side_effect = AssertionError("should use retry helper")
        mock_retry.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {"results": [{"title": "Test paper"}]},
        )
        with patch(
            "scholaraio.core.config.load_config",
            return_value=SimpleNamespace(openalex=SimpleNamespace(api_key="secret-key")),
        ):
            result = _query_oa_relaxed("Test paper")
        assert result["title"] == "Test paper"
        called_url = mock_retry.call_args.args[0]
        assert "api_key=secret-key" in called_url
