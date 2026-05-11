"""Contract tests for BibTeX export.

Verifies: given well-formed metadata, export produces valid BibTeX.
Does NOT test: internal helper functions, exact string formatting.
"""

from __future__ import annotations

from scholaraio.services.export import export_bibtex, meta_to_bibtex


class TestMetaToBibtex:
    """Single-entry BibTeX conversion contract."""

    def test_journal_article_has_required_fields(self):
        meta = {
            "title": "Some Title",
            "authors": ["Alice", "Bob"],
            "year": 2023,
            "journal": "Nature",
            "doi": "10.1234/test",
            "paper_type": "journal-article",
            "first_author_lastname": "Alice",
        }
        bib = meta_to_bibtex(meta)
        assert bib.startswith("@article{")
        assert "Some Title" in bib
        assert "author = {Alice and Bob}" in bib
        assert "year = {2023}" in bib
        assert "doi = {10.1234/test}" in bib

    def test_thesis_maps_to_phdthesis(self):
        meta = {
            "title": "My Thesis",
            "authors": ["Grad Student"],
            "year": 2024,
            "paper_type": "thesis",
            "first_author_lastname": "Student",
        }
        bib = meta_to_bibtex(meta)
        assert bib.startswith("@phdthesis{")

    def test_special_chars_escaped(self):
        meta = {
            "title": "CO2 & H2O: 50% of the #1 problem",
            "authors": [],
            "first_author_lastname": "Test",
        }
        bib = meta_to_bibtex(meta)
        assert "\\&" in bib
        assert "\\%" in bib
        assert "\\#" in bib


class TestExportBibtex:
    """Batch export contract: filters work, output is concatenated entries."""

    def test_export_all(self, tmp_papers):
        result = export_bibtex(tmp_papers)
        assert "@article{" in result
        assert "@phdthesis{" in result

    def test_filter_by_year(self, tmp_papers):
        result = export_bibtex(tmp_papers, year="2024")
        assert "Deep learning" in result
        assert "Turbulence" not in result

    def test_filter_by_journal(self, tmp_papers):
        result = export_bibtex(tmp_papers, journal="Fluid Mechanics")
        assert "Turbulence" in result
        assert "Deep learning" not in result

    def test_filter_by_paper_type(self, tmp_papers):
        result = export_bibtex(tmp_papers, paper_type="THES")
        assert "Deep learning" in result
        assert "Turbulence" not in result

    def test_filter_by_paper_ids(self, tmp_papers):
        result = export_bibtex(tmp_papers, paper_ids=["Smith-2023-Turbulence"])
        assert "Turbulence" in result
        assert "Deep learning" not in result

    def test_empty_result_returns_empty_string(self, tmp_papers):
        result = export_bibtex(tmp_papers, year="1900")
        assert result == ""
