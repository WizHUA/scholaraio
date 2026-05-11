"""Contract tests for papers.py — path helpers, scrub markers, and iteration.

Verifies: directory iteration yields only valid paper dirs, path helpers
compose correctly.
Does NOT test: UUID generation randomness, internal sorting.
"""

from __future__ import annotations

from scholaraio.stores.papers import (
    best_citation,
    is_scrubbed,
    iter_paper_dirs,
    mark_scrubbed,
    md_path,
    meta_path,
    paper_dir,
    scrub_marker_path,
)


class TestPathHelpers:
    """Path composition contract."""

    def test_paper_dir_joins_correctly(self, tmp_papers):
        result = paper_dir(tmp_papers, "Smith-2023-Turbulence")
        assert result == tmp_papers / "Smith-2023-Turbulence"

    def test_meta_path(self, tmp_papers):
        result = meta_path(tmp_papers, "Smith-2023-Turbulence")
        assert result.name == "meta.json"
        assert result.exists()

    def test_md_path(self, tmp_papers):
        result = md_path(tmp_papers, "Smith-2023-Turbulence")
        assert result.name == "paper.md"
        assert result.exists()


class TestIterPaperDirs:
    """Iteration contract: yields dirs with meta.json, skips others."""

    def test_yields_valid_paper_dirs(self, tmp_papers):
        dirs = list(iter_paper_dirs(tmp_papers))
        names = [d.name for d in dirs]
        assert "Smith-2023-Turbulence" in names
        assert "Wang-2024-DeepLearning" in names

    def test_skips_dirs_without_meta(self, tmp_papers):
        # Create a directory without meta.json
        (tmp_papers / "orphan-dir").mkdir()
        dirs = list(iter_paper_dirs(tmp_papers))
        names = [d.name for d in dirs]
        assert "orphan-dir" not in names

    def test_nonexistent_dir_yields_nothing(self, tmp_path):
        dirs = list(iter_paper_dirs(tmp_path / "nonexistent"))
        assert dirs == []


class TestCitationHelpers:
    """Citation-count compatibility contract."""

    def test_best_citation_accepts_legacy_scalar_count(self):
        assert best_citation({"citation_count": 7}) == 7

    def test_best_citation_accepts_dict_counts(self):
        assert best_citation({"citation_count": {"crossref": 3, "semantic_scholar": 11}}) == 11


class TestScrubMarkers:
    """Scrub marker contract: papers can be marked as reviewed incrementally."""

    def test_is_scrubbed_false_when_marker_missing(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        assert is_scrubbed(paper_d) is False

    def test_mark_scrubbed_creates_marker(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        mark_scrubbed(paper_d)

        assert scrub_marker_path(paper_d) == paper_d / ".scrubbed"
        assert scrub_marker_path(paper_d).exists()
        assert is_scrubbed(paper_d) is True

    def test_mark_scrubbed_is_idempotent(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        mark_scrubbed(paper_d)
        mark_scrubbed(paper_d)

        assert scrub_marker_path(paper_d).exists()
        assert is_scrubbed(paper_d) is True
