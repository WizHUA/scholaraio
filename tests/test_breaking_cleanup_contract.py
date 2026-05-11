from __future__ import annotations

import importlib
from importlib.machinery import PathFinder
from pathlib import Path

REMOVED_LEGACY_IMPORTS = (
    "scholaraio.audit",
    "scholaraio.backup",
    "scholaraio.citation_check",
    "scholaraio.citation_styles",
    "scholaraio.config",
    "scholaraio.diagram",
    "scholaraio.document",
    "scholaraio.explore",
    "scholaraio.export",
    "scholaraio.index",
    "scholaraio.ingest",
    "scholaraio.ingest.extractor",
    "scholaraio.ingest.metadata",
    "scholaraio.ingest.mineru",
    "scholaraio.ingest.parser_matrix_benchmark",
    "scholaraio.ingest.pdf_fallback",
    "scholaraio.ingest.pipeline",
    "scholaraio.ingest.proceedings",
    "scholaraio.insights",
    "scholaraio.loader",
    "scholaraio.log",
    "scholaraio.metrics",
    "scholaraio.migration_control",
    "scholaraio.papers",
    "scholaraio.patent_fetch",
    "scholaraio.proceedings",
    "scholaraio.setup",
    "scholaraio.sources",
    "scholaraio.sources.arxiv",
    "scholaraio.sources.endnote",
    "scholaraio.sources.webtools",
    "scholaraio.sources.zotero",
    "scholaraio.toolref",
    "scholaraio.topics",
    "scholaraio.translate",
    "scholaraio.uspto_odp",
    "scholaraio.uspto_ppubs",
    "scholaraio.vectors",
    "scholaraio.workspace",
)


def _local_package_spec(module_name: str):
    importlib.import_module("scholaraio")
    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root / "scholaraio"
    relative_parts = module_name.split(".")[1:]
    search_root = package_root.joinpath(*relative_parts[:-1])
    if not search_root.exists():
        return None
    return PathFinder.find_spec(module_name, [str(search_root)])


def test_breaking_cleanup_removes_legacy_public_imports() -> None:
    for module_name in REMOVED_LEGACY_IMPORTS:
        assert _local_package_spec(module_name) is None, f"{module_name} should not exist in the local package tree"


def test_cli_module_is_a_minimal_entrypoint() -> None:
    from scholaraio import cli
    from scholaraio.interfaces.cli import runtime

    assert cli.main is runtime.main
    for attr in (
        "load_config",
        "ui",
        "cmd_search",
        "cmd_translate",
        "_build_parser",
        "_resolve_paper",
        "_record_search_metrics",
        "_INSTALL_HINTS",
    ):
        assert not hasattr(cli, attr), f"scholaraio.cli should not expose {attr} in the breaking cleanup generation"
