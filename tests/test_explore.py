"""Tests for explore filters, validation, and public helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scholaraio.explore import _build_filter, explore_db_path, fetch_explore, validate_explore_name


class TestBuildFilter:
    def test_min_citations_positive_adds_filter(self):
        filt, _ = _build_filter(min_citations=10)
        assert "cited_by_count:>9" in filt

    def test_min_citations_zero_or_negative_ignored(self):
        filt_zero, _ = _build_filter(min_citations=0)
        filt_negative, _ = _build_filter(min_citations=-3)
        assert "cited_by_count" not in filt_zero
        assert "cited_by_count" not in filt_negative


class TestFetchExploreLimit:
    def test_limit_must_be_positive(self):
        with pytest.raises(ValueError, match="limit 必须为正整数"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=0)

        with pytest.raises(ValueError, match="limit 必须为正整数"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=-1)


class TestExploreNameValidation:
    def test_validate_explore_name_rejects_path_traversal(self):
        assert validate_explore_name("jfm-2026")
        assert not validate_explore_name("")
        assert not validate_explore_name("../escape")
        assert not validate_explore_name("nested/name")


class TestExploreDbPath:
    def test_explore_db_path_uses_default_layout(self):
        assert explore_db_path("demo") == Path("data/explore/demo/explore.db")
