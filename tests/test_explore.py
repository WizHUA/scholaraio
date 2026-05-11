"""Tests for explore filters, validation, and public helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scholaraio.core.config import _build_config
from scholaraio.stores.explore import _build_filter, explore_db_path, fetch_explore, validate_explore_name


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
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=0)

        with pytest.raises(ValueError, match="limit must be a positive integer"):
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

    def test_explore_db_path_uses_configured_root(self, tmp_path):
        cfg = _build_config({"paths": {"explore_root": "stores/explore"}}, tmp_path)

        assert explore_db_path("demo", cfg) == (tmp_path / "stores" / "explore" / "demo" / "explore.db").resolve()

    def test_list_explore_libs_uses_configured_root(self, tmp_path):
        from scholaraio.stores.explore import list_explore_libs

        cfg = _build_config({"paths": {"explore_root": "stores/explore"}}, tmp_path)
        custom_root = cfg.explore_root
        custom_root.mkdir(parents=True)
        (custom_root / "alpha").mkdir()
        (custom_root / "alpha" / "papers.jsonl").write_text("", encoding="utf-8")

        legacy_root = tmp_path / "data" / "explore"
        legacy_root.mkdir(parents=True)
        (legacy_root / "legacy").mkdir()
        (legacy_root / "legacy" / "papers.jsonl").write_text("", encoding="utf-8")

        assert list_explore_libs(cfg) == ["alpha"]
