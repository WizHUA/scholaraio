from __future__ import annotations

import sys
import types

import requests

from . import paths as _paths_mod
from .constants import TOOL_REGISTRY
from .fetch import toolref_fetch
from .indexing import _index_tool
from .manifest import (
    _build_bioinformatics_manifest,
    _build_manifest,
    _build_openfoam_manifest,
    _copy_manifest_page_from_cache,
    _discover_bioinformatics_manifest,
    _discover_openfoam_manifest,
    _discover_openfoam_manifest_bundle,
    _expected_manifest_pages,
    _extract_html_anchor_fragment,
    _extract_html_headings_with_ids,
    _extract_html_main,
    _extract_openfoam_doc_links,
    _has_local_docs,
    _load_manifest_cached_html,
    _load_manifest_snapshot,
    _manifest_missing_page_names,
    _manifest_page_count,
    _manifest_present_page_names,
    _normalize_openfoam_doc_url,
    _slugify,
    _write_manifest_snapshot,
)
from .parsers import (
    _clean_manifest_text,
    _parse_gromacs_rst,
    _parse_lammps_rst,
    _parse_manifest_html,
    _parse_qe_def,
    _pick_manifest_synopsis,
)
from .paths import (
    _current_link,
    _db_path,
    _tool_dir,
    _toolref_root,
    _validate_version,
    _version_dir,
    validate_tool_name,
)
from .search import (
    _expand_search_query,
    _normalize_alias_phrase,
    _normalize_program_filter,
    _normalize_search_query,
    _score_search_result,
    _tokenize_rank_text,
    toolref_search,
    toolref_show,
)
from .storage import _FTS_SCHEMA, _FTS_TRIGGERS, _PAGES_SCHEMA, _ensure_db, _set_current, toolref_list, toolref_use


class _ToolrefModule(types.ModuleType):
    """Preserve legacy module-level patch points after the package split."""

    def __getattribute__(self, name: str):
        if name == "_DEFAULT_TOOLREF_DIR":
            return _paths_mod._DEFAULT_TOOLREF_DIR
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value) -> None:
        if name == "_DEFAULT_TOOLREF_DIR":
            _paths_mod._DEFAULT_TOOLREF_DIR = value
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ToolrefModule

__all__ = [
    "TOOL_REGISTRY",
    "_DEFAULT_TOOLREF_DIR",
    "_FTS_SCHEMA",
    "_FTS_TRIGGERS",
    "_PAGES_SCHEMA",
    "_build_bioinformatics_manifest",
    "_build_manifest",
    "_build_openfoam_manifest",
    "_clean_manifest_text",
    "_copy_manifest_page_from_cache",
    "_current_link",
    "_db_path",
    "_discover_bioinformatics_manifest",
    "_discover_openfoam_manifest",
    "_discover_openfoam_manifest_bundle",
    "_ensure_db",
    "_expand_search_query",
    "_expected_manifest_pages",
    "_extract_html_anchor_fragment",
    "_extract_html_headings_with_ids",
    "_extract_html_main",
    "_extract_openfoam_doc_links",
    "_has_local_docs",
    "_index_tool",
    "_load_manifest_cached_html",
    "_load_manifest_snapshot",
    "_manifest_missing_page_names",
    "_manifest_page_count",
    "_manifest_present_page_names",
    "_normalize_alias_phrase",
    "_normalize_openfoam_doc_url",
    "_normalize_program_filter",
    "_normalize_search_query",
    "_parse_gromacs_rst",
    "_parse_lammps_rst",
    "_parse_manifest_html",
    "_parse_qe_def",
    "_pick_manifest_synopsis",
    "_score_search_result",
    "_set_current",
    "_slugify",
    "_tokenize_rank_text",
    "_tool_dir",
    "_toolref_root",
    "_validate_version",
    "_version_dir",
    "_write_manifest_snapshot",
    "requests",
    "toolref_fetch",
    "toolref_list",
    "toolref_search",
    "toolref_show",
    "toolref_use",
    "validate_tool_name",
]
