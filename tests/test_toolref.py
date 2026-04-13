from __future__ import annotations

import json
import sqlite3

import pytest

from scholaraio.toolref import (
    _build_bioinformatics_manifest,
    _build_openfoam_manifest,
    _clean_manifest_text,
    _discover_bioinformatics_manifest,
    _discover_openfoam_manifest,
    _expand_search_query,
    _extract_html_anchor_fragment,
    _extract_html_headings_with_ids,
    _extract_openfoam_doc_links,
    _has_local_docs,
    _normalize_openfoam_doc_url,
    _normalize_program_filter,
    _normalize_search_query,
    _parse_lammps_rst,
    _parse_manifest_html,
    _parse_qe_def,
    _pick_manifest_synopsis,
    toolref_fetch,
    toolref_list,
    toolref_search,
    toolref_show,
    toolref_use,
)


@pytest.fixture
def toolref_mod():
    from scholaraio import toolref as mod
    from scholaraio.toolref import _legacy_snapshot as legacy_mod
    from scholaraio.toolref import fetch as fetch_mod
    from scholaraio.toolref import indexing as indexing_mod
    from scholaraio.toolref import manifest as manifest_mod
    from scholaraio.toolref import paths as paths_mod
    from scholaraio.toolref import search as search_mod

    return {
        "api": mod,
        "paths": paths_mod,
        "manifest": manifest_mod,
        "fetch": fetch_mod,
        "indexing": indexing_mod,
        "search": search_mod,
        "legacy": legacy_mod,
    }


def test_toolref_package_compat_for_default_dir_and_requests(tmp_path, toolref_mod):
    mod = toolref_mod["api"]
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    original_root = paths_mod._DEFAULT_TOOLREF_DIR
    try:
        mod._DEFAULT_TOOLREF_DIR = tmp_path
        assert tmp_path == paths_mod._DEFAULT_TOOLREF_DIR
        assert mod._db_path("qe") == tmp_path / "qe" / "toolref.db"
        assert mod.requests is fetch_mod.requests
    finally:
        mod._DEFAULT_TOOLREF_DIR = original_root


def test_index_tool_returns_final_unique_entry_count(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    indexing_mod = toolref_mod["indexing"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    vdir = tmp_path / "qe" / "7.5" / "def"
    vdir.mkdir(parents=True)
    (vdir / "INPUT_FAKE.def").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(
        indexing_mod,
        "_parse_qe_def",
        lambda _path: [
            {
                "program": "pw.x",
                "section": "SYSTEM",
                "page_name": "pw.x/SYSTEM/ecutwfc",
                "title": "ecutwfc",
                "content": "first",
            },
            {
                "program": "pw.x",
                "section": "SYSTEM",
                "page_name": "pw.x/SYSTEM/ecutwfc",
                "title": "ecutwfc",
                "content": "updated",
            },
            {
                "program": "pw.x",
                "section": "ELECTRONS",
                "page_name": "pw.x/ELECTRONS/conv_thr",
                "title": "conv_thr",
                "content": "third",
            },
        ],
    )

    count = indexing_mod._index_tool("qe", "7.5", cfg=None)

    assert count == 2
    conn = sqlite3.connect(tmp_path / "qe" / "toolref.db")
    try:
        db_count = conn.execute(
            "SELECT COUNT(*) FROM toolref_pages WHERE tool = ? AND version = ?",
            ("qe", "7.5"),
        ).fetchone()[0]
        assert db_count == 2
    finally:
        conn.close()


def test_ensure_db_drops_legacy_fts_triggers(tmp_path):
    from scholaraio.toolref.storage import _ensure_db

    db = tmp_path / "toolref.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE toolref_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool TEXT NOT NULL,
                version TEXT NOT NULL,
                program TEXT,
                section TEXT,
                page_name TEXT NOT NULL,
                title TEXT,
                category TEXT,
                var_type TEXT,
                default_val TEXT,
                synopsis TEXT,
                content TEXT NOT NULL,
                UNIQUE(tool, version, page_name)
            );
            CREATE VIRTUAL TABLE toolref_fts USING fts5(
                page_name, title, synopsis, content,
                content=toolref_pages,
                content_rowid=id
            );
            CREATE TRIGGER toolref_ai AFTER INSERT ON toolref_pages BEGIN
                INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
                VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
            END;
            CREATE TRIGGER toolref_ad AFTER DELETE ON toolref_pages BEGIN
                INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
                VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
            END;
            CREATE TRIGGER toolref_au AFTER UPDATE ON toolref_pages BEGIN
                INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
                VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
                INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
                VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
            END;
            """
        )
        conn.execute(
            """INSERT INTO toolref_pages
               (tool, version, program, section, page_name, title, synopsis, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("qe", "7.5", "pw.x", "SYSTEM", "pw.x/SYSTEM/ecutwfc", "ecutwfc", "cutoff", "content"),
        )
        conn.commit()
    finally:
        conn.close()

    conn = _ensure_db(db)
    try:
        trigger_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
        }
        assert "toolref_ai" not in trigger_names
        assert "toolref_ad" not in trigger_names
        assert "toolref_au" not in trigger_names
        assert "toolref_pages_ai" in trigger_names
        assert "toolref_pages_ad" in trigger_names
        assert "toolref_pages_au" in trigger_names

        conn.execute("DELETE FROM toolref_pages WHERE tool = ? AND version = ?", ("qe", "7.5"))
        conn.commit()
    finally:
        conn.close()


def test_toolref_use_rejects_unsafe_version_path(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)

    with pytest.raises(ValueError, match="非法版本号"):
        toolref_use("qe", "../outside", cfg=None)

    assert not (tmp_path / "qe" / "current").exists()


def test_toolref_fetch_refreshes_manifest_meta_when_skipping_existing_docs(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    vdir = tmp_path / "openfoam" / "2312"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    for idx, page_name in enumerate(["openfoam/simpleFoam", "openfoam/fvSchemes"], start=1):
        stem = f"{idx:03d}-page"
        (pages_dir / f"{stem}.html").write_text("<main><h1>page</h1></main>", encoding="utf-8")
        (pages_dir / f"{stem}.json").write_text(json.dumps({"page_name": page_name}), encoding="utf-8")
    (vdir / "manifest.json").write_text(
        json.dumps([{"page_name": "openfoam/simpleFoam"}, {"page_name": "openfoam/fvSchemes"}]),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "display_name": "OpenFOAM",
                "version": "2312",
                "format": "html",
                "repo": "",
                "source_type": "manifest",
                "force_refreshed": False,
                "fetched_pages": 2,
                "expected_pages": 1,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 2)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = fetch_mod.toolref_fetch("openfoam", version="2312", cfg=None)

    assert count == 2
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetched_pages"] == 2
    assert meta["expected_pages"] == 2
    assert meta["failed_pages"] == 0


def test_normalize_program_filter_for_qe():
    assert _normalize_program_filter("qe", "pw") == "pw.x"
    assert _normalize_program_filter("qe", "ph.x") == "ph.x"


def test_normalize_program_filter_for_non_qe():
    assert _normalize_program_filter("openfoam", "simpleFoam") == "simplefoam"
    assert _normalize_program_filter("bioinformatics", "samtools") == "samtools"


def test_normalize_search_query_rewrites_punctuation_runs():
    assert _normalize_search_query("k-point/convergence") == "k point convergence"
    assert _normalize_search_query("  spike__rbd ") == "spike rbd"


def test_expand_search_query_adds_openfoam_aliases():
    expanded = _expand_search_query("openfoam", "drag coefficient")
    assert "forces" in expanded
    assert "forcecoeffs" in expanded


def test_expand_search_query_adds_more_openfoam_aliases():
    expanded = _expand_search_query("openfoam", "y plus")
    assert "yplus" in expanded
    expanded = _expand_search_query("openfoam", "wall shear stress")
    assert "wallshearstress" in expanded
    expanded = _expand_search_query("openfoam", "solver residuals")
    assert "residuals" in expanded
    expanded = _expand_search_query("openfoam", "k omega sst turbulence")
    assert "komegasst" in expanded
    expanded = _expand_search_query("openfoam", "numerical schemes")
    assert "fvschemes" in expanded
    expanded = _expand_search_query("openfoam", "linear solver settings")
    assert "fvsolution" in expanded


def test_expand_search_query_adds_bioinformatics_aliases():
    expanded = _expand_search_query("bioinformatics", "phylogenetic tree")
    assert "iqtree" in expanded
    expanded = _expand_search_query("bioinformatics", "read mapping nanopore")
    assert "minimap2" in expanded
    expanded = _expand_search_query("bioinformatics", "protein structure folding")
    assert "esmfold" in expanded
    expanded = _expand_search_query("bioinformatics", "multiple sequence alignment fasta")
    assert "mafft" in expanded
    expanded = _expand_search_query("bioinformatics", "bam indexing")
    assert "samtools index" in expanded


def test_expand_search_query_adds_qe_aliases():
    expanded = _expand_search_query("qe", "ecut rho")
    assert "ecutrho" in expanded


def test_expand_search_query_adds_lammps_and_bio_aliases():
    lammps_expanded = _expand_search_query("lammps", "phase transition pressure")
    assert "fix_nphug" in lammps_expanded
    bio_expanded = _expand_search_query("bioinformatics", "spike mutation")
    assert "bcftools" in bio_expanded


def test_build_openfoam_manifest_uses_requested_version():
    manifest = _build_openfoam_manifest("2312")
    assert manifest
    assert all("page_name" in item for item in manifest)
    assert any("/2312/" in item["url"] for item in manifest if "doc.openfoam.com" in item["url"])


def test_normalize_openfoam_doc_url_filters_version_and_assets():
    assert _normalize_openfoam_doc_url("/2312/fundamentals/", "2312") == "https://doc.openfoam.com/2312/fundamentals/"
    assert _normalize_openfoam_doc_url("/2212/fundamentals/", "2312") is None
    assert _normalize_openfoam_doc_url("/2312/img/logo.png", "2312") is None


def test_extract_openfoam_doc_links_keeps_main_doc_paths():
    html = """
    <a href="/2312/fundamentals/">Fundamentals</a>
    <a href="/2312/tools/pre-processing/mesh/generation/blockMesh/blockmesh/">blockMesh</a>
    <a href="/2312/installation/">Install</a>
    <a href="/2312/img/openfoam_logo.jpg">Logo</a>
    """
    links = _extract_openfoam_doc_links(html, "2312")
    assert "https://doc.openfoam.com/2312/fundamentals/" in links
    assert "https://doc.openfoam.com/2312/tools/pre-processing/mesh/generation/blockMesh/blockmesh/" in links
    assert all("/installation/" not in link for link in links)


def test_discover_openfoam_manifest_builds_curated_mainline_pages():
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://doc.openfoam.com/2312/fundamentals/": """
                    <a href="/2312/fundamentals/case-structure/controldict/">controlDict</a>
                    <a href="/2312/fundamentals/case-structure/fvschemes/">fvSchemes</a>
                    <a href="/2312/installation/">Installation</a>
                """,
                "https://doc.openfoam.com/2312/tools/": """
                    <a href="/2312/tools/processing/solvers/rtm/incompressible/simpleFoam/">simpleFoam</a>
                    <a href="/2312/tools/post-processing/function-objects/forces/forceCoeffs/">forceCoeffs</a>
                    <a href="/2312/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/">kOmegaSST</a>
                """,
                "https://doc.openfoam.com/2312/fundamentals/case-structure/controldict/": "<main><h1>controlDict</h1></main>",
                "https://doc.openfoam.com/2312/fundamentals/case-structure/fvschemes/": "<main><h1>fvSchemes</h1></main>",
                "https://doc.openfoam.com/2312/tools/processing/solvers/rtm/incompressible/simpleFoam/": "<main><h1>simpleFoam</h1></main>",
                "https://doc.openfoam.com/2312/tools/post-processing/function-objects/forces/forceCoeffs/": "<main><h1>forceCoeffs</h1></main>",
                "https://doc.openfoam.com/2312/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/": "<main><h1>kOmegaSST</h1></main>",
            }

        def get(self, url, timeout=None):
            return FakeResponse(self.pages[url])

    manifest = _discover_openfoam_manifest("2312", FakeSession())
    page_names = {item["page_name"] for item in manifest}
    assert "openfoam/controlDict" in page_names
    assert "openfoam/fvSchemes" in page_names
    assert "openfoam/simpleFoam" in page_names
    assert "openfoam/forceCoeffs" in page_names
    assert "openfoam/kOmegaSST" in page_names
    assert all("installation" not in item["url"] for item in manifest)


def test_discover_openfoam_manifest_preserves_curated_core_pages_when_crawl_is_partial():
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://doc.openfoam.com/2312/fundamentals/": """
                    <a href="/2312/fundamentals/case-structure/controldict/">controlDict</a>
                """,
                "https://doc.openfoam.com/2312/tools/": """
                    <a href="/2312/tools/post-processing/function-objects/forces/forceCoeffs/">forceCoeffs</a>
                """,
                "https://doc.openfoam.com/2312/fundamentals/case-structure/controldict/": "<main><h1>controlDict</h1></main>",
                "https://doc.openfoam.com/2312/tools/post-processing/function-objects/forces/forceCoeffs/": "<main><h1>forceCoeffs</h1></main>",
            }

        def get(self, url, timeout=None):
            return FakeResponse(self.pages[url])

    manifest = _discover_openfoam_manifest("2312", FakeSession())
    page_names = {item["page_name"] for item in manifest}

    assert "openfoam/simpleFoam" in page_names
    assert "openfoam/fvSchemes" in page_names
    assert "openfoam/controlDict" in page_names
    assert "openfoam/forceCoeffs" in page_names


def test_build_openfoam_manifest_includes_specific_mesh_and_post_pages():
    manifest = _build_openfoam_manifest("2312")
    pages = {item["page_name"]: item for item in manifest}

    assert pages["openfoam/blockMesh"]["url"].endswith(
        "/2312/tools/pre-processing/mesh/generation/blockMesh/blockmesh/"
    )
    assert pages["openfoam/forceCoeffs"]["url"].endswith(
        "/2312/tools/post-processing/function-objects/forces/forceCoeffs/"
    )
    assert pages["openfoam/Q"]["url"].endswith("/2312/tools/post-processing/function-objects/field/Q/")


def test_build_openfoam_manifest_includes_validation_and_wall_pages():
    manifest = _build_openfoam_manifest("2312")
    pages = {item["page_name"]: item for item in manifest}

    assert pages["openfoam/yPlus"]["url"].endswith("/2312/tools/post-processing/function-objects/field/yPlus/")
    assert pages["openfoam/wallShearStress"]["url"].endswith(
        "/2312/tools/post-processing/function-objects/field/wallShearStress/"
    )
    assert pages["openfoam/residuals"]["url"].endswith("/2312/tools/processing/numerics/solvers/residuals/")


def test_build_bioinformatics_manifest_contains_multiple_subtools():
    manifest = _build_bioinformatics_manifest("2026-03-curated")
    programs = {item["program"] for item in manifest}
    assert {"blastn", "minimap2", "samtools", "bcftools", "mafft", "iqtree", "esmfold"} <= programs


def test_build_bioinformatics_manifest_includes_high_value_entry_points():
    manifest = _build_bioinformatics_manifest("2026-03-curated")
    pages = {item["page_name"]: item for item in manifest}

    assert pages["minimap2/manual"]["url"] == "https://lh3.github.io/minimap2/minimap2.html"
    assert "fallback_urls" in pages["minimap2/manual"]
    assert "github.com/lh3/minimap2" in pages["minimap2/manual"]["fallback_urls"][0]
    assert pages["bcftools/call"]["url"].endswith("/bcftools.html#call")
    assert pages["bcftools/mpileup"]["url"].endswith("/bcftools.html#mpileup")
    assert pages["iqtree/ultrafast-bootstrap"]["url"].endswith("/Command-Reference#ultrafast-bootstrap-parameters")
    assert pages["iqtree/ultrafast-bootstrap"]["anchor"] == "ultrafast-bootstrap-parameters"
    assert pages["samtools/index"]["url"].endswith("/samtools-index.html")


def test_extract_html_headings_with_ids_reads_h2_and_h3():
    html = """
    <h2 id="general-options">General options</h2>
    <h3 id="call">bcftools call</h3>
    <h4 id="ignored">ignored</h4>
    """
    headings = _extract_html_headings_with_ids(html)
    assert headings == [
        {"level": 2, "id": "general-options", "title": "General options"},
        {"level": 3, "id": "call", "title": "bcftools call"},
    ]


def test_extract_html_anchor_fragment_cuts_section_until_next_peer_heading():
    html = """
    <main>
      <h2 id="alpha">Alpha</h2>
      <p>A</p>
      <h3 id="beta">Beta</h3>
      <p>B</p>
      <h3 id="gamma">Gamma</h3>
      <p>C</p>
    </main>
    """
    fragment = _extract_html_anchor_fragment(html, "beta")
    assert "Beta" in fragment
    assert "B" in fragment
    assert "Gamma" not in fragment


def test_discover_bioinformatics_manifest_expands_from_official_index_pages():
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://www.htslib.org/doc/samtools.html": """
                    <a href="samtools-flagstat.html">flagstat</a>
                    <a href="samtools-depth.html">depth</a>
                """,
                "https://samtools.github.io/bcftools/bcftools.html": """
                    <h3 id="call">bcftools call</h3>
                    <h3 id="query">bcftools query</h3>
                    <h2 id="expressions">EXPRESSIONS</h2>
                """,
                "https://iqtree.github.io/doc/Command-Reference": """
                    <h2 id="general-options">General options</h2>
                    <h2 id="ultrafast-bootstrap">Ultrafast bootstrap</h2>
                    <h3 id="example-usages">Example usages</h3>
                """,
            }

        def get(self, url, timeout=None):
            return FakeResponse(self.pages[url])

    manifest, prefetched = _discover_bioinformatics_manifest(
        "2026-03-curated",
        FakeSession(),
        _build_bioinformatics_manifest("2026-03-curated"),
    )
    pages = {item["page_name"] for item in manifest}
    assert "samtools/flagstat" in pages
    assert "samtools/depth" in pages
    assert "bcftools/query" in pages
    assert "bcftools/expressions" in pages
    assert "iqtree/general-options" in pages
    assert "iqtree/ultrafast-bootstrap" in pages
    items = {item["page_name"]: item for item in manifest}
    assert items["bcftools/call"]["anchor"] == "call"
    assert items["iqtree/ultrafast-bootstrap"]["anchor"] == "ultrafast-bootstrap"
    assert "https://www.htslib.org/doc/samtools.html" in prefetched


def test_discover_bioinformatics_manifest_upgrades_curated_alias_to_real_anchor():
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://www.htslib.org/doc/samtools.html": "",
                "https://samtools.github.io/bcftools/bcftools.html": "",
                "https://iqtree.github.io/doc/Command-Reference": """
                    <h2 id="ultrafast-bootstrap-parameters">Ultrafast bootstrap parameters</h2>
                """,
            }

        def get(self, url, timeout=None):
            return FakeResponse(self.pages[url])

    manifest, _ = _discover_bioinformatics_manifest(
        "2026-03-curated",
        FakeSession(),
        _build_bioinformatics_manifest("2026-03-curated"),
    )
    items = {item["page_name"]: item for item in manifest}
    assert items["iqtree/ultrafast-bootstrap"]["anchor"] == "ultrafast-bootstrap-parameters"
    assert items["iqtree/ultrafast-bootstrap"]["url"].endswith("/Command-Reference#ultrafast-bootstrap-parameters")


def test_discover_bioinformatics_manifest_reuses_cached_seed_pages(tmp_path):
    class FailingSession:
        def get(self, url, timeout=None):
            from requests import RequestException

            raise RequestException("timeout")

    cache_vdir = tmp_path / "bio" / "2026-03-curated"
    pages_dir = cache_vdir / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "001-bcftools-manual.html").write_text(
        '<h3 id="query">bcftools query</h3><h3 id="view">bcftools view</h3>',
        encoding="utf-8",
    )
    (pages_dir / "001-bcftools-manual.json").write_text(
        json.dumps({"page_name": "bcftools/manual"}),
        encoding="utf-8",
    )

    manifest, prefetched = _discover_bioinformatics_manifest(
        "2026-03-curated",
        FailingSession(),
        _build_bioinformatics_manifest("2026-03-curated"),
        cache_vdir=cache_vdir,
    )

    pages = {item["page_name"] for item in manifest}
    assert "bcftools/query" in pages
    assert "https://samtools.github.io/bcftools/bcftools.html" in prefetched


def test_toolref_fetch_bioinformatics_reuses_prefetched_seed_html_for_anchor_pages(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            raise fetch_mod.requests.RequestException(f"unexpected fetch: {url}")

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    monkeypatch.setattr(fetch_mod.requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_discover_bioinformatics_manifest",
        lambda version, session, manifest, cache_vdir=None: (
            [
                {
                    "program": "bcftools",
                    "section": "variant-calling",
                    "page_name": "bcftools/query",
                    "title": "bcftools query",
                    "url": "https://samtools.github.io/bcftools/bcftools.html#query",
                    "anchor": "query",
                }
            ],
            {
                "https://samtools.github.io/bcftools/bcftools.html": '<h3 id="query">bcftools query</h3><p>query body</p>'
            },
        ),
    )
    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)

    assert count == 1
    page = tmp_path / "bioinformatics" / "2026-03-curated" / "pages" / "001-bcftools-query.html"
    assert page.exists()


def test_parse_manifest_html_extracts_main_text(tmp_path):
    html_path = tmp_path / "page.html"
    meta_path = tmp_path / "page.json"

    html_path.write_text(
        """
        <html>
          <body>
            <main>
              <h1>simpleFoam</h1>
              <p>Steady-state incompressible solver.</p>
              <pre><code>simpleFoam -case motorBike</code></pre>
            </main>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps(
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
            }
        ),
        encoding="utf-8",
    )

    records = _parse_manifest_html(html_path)

    assert len(records) == 1
    record = records[0]
    assert record["page_name"] == "openfoam/simpleFoam"
    assert "Steady-state incompressible solver." in record["content"]
    assert "simpleFoam -case motorBike" in record["content"]


def test_has_local_docs_for_manifest_html(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    pages_dir = tmp_path / "openfoam" / "2312" / "pages"
    pages_dir.mkdir(parents=True)
    assert not _has_local_docs("openfoam", "2312")

    (pages_dir / "001-openfoam-simpleFoam.html").write_text("<html></html>", encoding="utf-8")
    (pages_dir / "001-openfoam-simpleFoam.json").write_text("{}", encoding="utf-8")
    assert not _has_local_docs("openfoam", "2312")

    manifest = _build_openfoam_manifest("2312")
    for idx, item in enumerate(manifest, start=1):
        (pages_dir / f"{idx:03d}-{item['page_name'].replace('/', '-')}.html").write_text(
            "<html></html>", encoding="utf-8"
        )
        (pages_dir / f"{idx:03d}-{item['page_name'].replace('/', '-')}.json").write_text("{}", encoding="utf-8")
    assert _has_local_docs("openfoam", "2312")


def test_clean_manifest_text_removes_common_navigation_and_footer():
    raw = """
Top
Toggle navigation
simpleFoam
- solvers
Overview
Steady-state incompressible solver.
Search results
Found a content problem with this page?
"""
    cleaned = _clean_manifest_text(raw, "simpleFoam", "simpleFoam")
    assert "Toggle navigation" not in cleaned
    assert "Search results" not in cleaned
    assert "Steady-state incompressible solver." in cleaned


def test_pick_manifest_synopsis_skips_generic_lines():
    lines = ["simpleFoam", "- solvers", "Overview", "Steady-state incompressible solver."]
    assert _pick_manifest_synopsis(lines, "simpleFoam") == "Steady-state incompressible solver."


def test_clean_manifest_text_anchors_blast_manual():
    raw = """
Bookshelf
Toggle navigation
BLAST® Command Line Applications User Manual
This manual documents the BLAST command line applications.
Search results
"""
    cleaned = _clean_manifest_text(raw, "BLAST+ user manual", "blastn")
    assert cleaned.startswith("BLAST")
    assert "Bookshelf" not in cleaned


def test_parse_manifest_html_uses_dictionary_synopsis(tmp_path):
    html_path = tmp_path / "page.html"
    meta_path = tmp_path / "page.json"
    html_path.write_text(
        """
        <html><body><main><h1>fvSchemes</h1><pre><code>FoamFile {}</code></pre></main></body></html>
        """,
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps(
            {
                "program": "fvSchemes",
                "section": "dictionary",
                "page_name": "openfoam/fvSchemes",
                "title": "fvSchemes",
            }
        ),
        encoding="utf-8",
    )

    record = _parse_manifest_html(html_path)[0]
    assert record["synopsis"] == "fvSchemes dictionary"


def test_toolref_fetch_manifest_force_rebuilds_pages(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            return FakeResponse(f"<html><body><main><h1>{url}</h1></main></body></html>")

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    monkeypatch.setattr(fetch_mod.requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
                "url": "https://example.org/simpleFoam",
            }
        ],
    )
    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("openfoam", version="2312", cfg=None)
    assert count == 1

    extra = tmp_path / "openfoam" / "2312" / "pages" / "stale.html"
    extra.write_text("stale", encoding="utf-8")

    count = toolref_fetch("openfoam", version="2312", force=True, cfg=None)
    assert count == 1
    assert not extra.exists()


def test_toolref_list_reads_manifest_meta(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    vdir = tmp_path / "openfoam" / "2312"
    vdir.mkdir(parents=True)
    (vdir / "manifest.json").write_text(
        json.dumps([{"page_name": f"page-{idx}"} for idx in range(11)]),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "version": "2312",
                "source_type": "manifest",
                "fetched_pages": 9,
                "expected_pages": 11,
                "failed_pages": 2,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "openfoam" / "current").symlink_to(vdir, target_is_directory=True)

    entries = toolref_list("openfoam", cfg=None)
    assert len(entries) == 1
    assert entries[0]["source_type"] == "manifest"
    assert entries[0]["expected_pages"] == 11
    assert entries[0]["failed_pages"] == 2


def test_toolref_list_reconciles_stale_manifest_meta_with_snapshot(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    vdir = tmp_path / "openfoam" / "2312"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    for idx, page_name in enumerate(["openfoam/simpleFoam", "openfoam/fvSchemes"], start=1):
        stem = f"{idx:03d}-page"
        (pages_dir / f"{stem}.html").write_text("<main><h1>page</h1></main>", encoding="utf-8")
        (pages_dir / f"{stem}.json").write_text(json.dumps({"page_name": page_name}), encoding="utf-8")
    (vdir / "manifest.json").write_text(
        json.dumps([{"page_name": "openfoam/simpleFoam"}, {"page_name": "openfoam/fvSchemes"}]),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "version": "2312",
                "source_type": "manifest",
                "fetched_pages": 2,
                "expected_pages": 1,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "openfoam" / "current").symlink_to(vdir, target_is_directory=True)

    entries = toolref_list("openfoam", cfg=None)
    assert len(entries) == 1
    assert entries[0]["page_count"] == 2
    assert entries[0]["expected_pages"] == 2
    assert entries[0]["failed_pages"] == 0


def test_toolref_fetch_manifest_force_keeps_more_complete_cache(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            if "view" in url:
                raise fetch_mod.requests.RequestException("boom")
            return FakeResponse(f"<html><body><main><h1>{url}</h1></main></body></html>")

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "samtools",
                "section": "alignment",
                "page_name": "samtools/sort",
                "title": "samtools sort",
                "url": "https://example.org/sort",
            },
            {
                "program": "samtools",
                "section": "alignment",
                "page_name": "samtools/view",
                "title": "samtools view",
                "url": "https://example.org/view",
            },
        ],
    )

    vdir = tmp_path / "bioinformatics" / "2026-03-curated"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    for idx, (name, page_name) in enumerate(
        [("samtools-sort", "samtools/sort"), ("samtools-view", "samtools/view")],
        start=1,
    ):
        (pages_dir / f"{idx:03d}-{name}.html").write_text("<html></html>", encoding="utf-8")
        (pages_dir / f"{idx:03d}-{name}.json").write_text(
            json.dumps({"page_name": page_name}),
            encoding="utf-8",
        )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "bioinformatics",
                "version": "2026-03-curated",
                "source_type": "manifest",
                "fetched_pages": 2,
                "expected_pages": 2,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fetch_mod.requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod, "_index_tool", lambda tool, version, cfg=None: fetch_mod.manifest_mod._manifest_page_count(vdir)
    )
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)
    assert count == 2
    assert (pages_dir / "002-samtools-view.html").exists()
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetched_pages"] == 2
    assert meta["failed_pages"] == 0
    assert meta["last_fetch_failed_page_names"] == ["samtools/view"]


def test_toolref_fetch_manifest_force_preserves_failed_pages_from_existing_cache(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            if "simpleFoam" in url:
                raise fetch_mod.requests.RequestException("timeout")
            return FakeResponse(f"<html><body><main><h1>{url}</h1></main></body></html>")

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    monkeypatch.setattr(fetch_mod.requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
                "url": "https://example.org/simpleFoam",
            },
            {
                "program": "yPlus",
                "section": "post-processing",
                "page_name": "openfoam/yPlus",
                "title": "yPlus",
                "url": "https://example.org/yPlus",
            },
        ],
    )

    vdir = tmp_path / "openfoam" / "2312"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "001-openfoam-simpleFoam.html").write_text(
        "<html><body>cached simpleFoam</body></html>", encoding="utf-8"
    )
    (pages_dir / "001-openfoam-simpleFoam.json").write_text(
        json.dumps(
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
                "url": "https://example.org/simpleFoam",
            }
        ),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "version": "2312",
                "source_type": "manifest",
                "fetched_pages": 1,
                "expected_pages": 1,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 2)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("openfoam", version="2312", force=True, cfg=None)
    assert count == 2
    assert (pages_dir / "001-openfoam-simpleFoam.html").exists()
    assert (pages_dir / "002-openfoam-yPlus.html").exists()
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetched_pages"] == 2
    assert meta["failed_pages"] == 0
    assert meta["last_fetch_failed_page_names"] == ["openfoam/simpleFoam"]


def test_toolref_fetch_manifest_force_recovers_from_corrupted_meta_json(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.trust_env = True

        def get(self, url, timeout=60):
            return FakeResponse("<html><body><main><h1>doc</h1></main></body></html>")

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    monkeypatch.setattr(fetch_mod.requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "samtools",
                "section": "alignment",
                "page_name": "samtools/sort",
                "title": "samtools sort",
                "url": "https://example.org/sort",
            }
        ],
    )

    vdir = tmp_path / "bioinformatics" / "2026-03-curated"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    (vdir / "meta.json").write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = fetch_mod.toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)

    assert count == 1
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["tool"] == "bioinformatics"
    assert meta["version"] == "2026-03-curated"
    assert meta["fetched_pages"] == 1
    assert meta["failed_pages"] == 0
    assert (pages_dir / "001-samtools-sort.html").exists()


def test_toolref_fetch_manifest_uses_fallback_urls(tmp_path, monkeypatch, toolref_mod):
    paths_mod = toolref_mod["paths"]
    fetch_mod = toolref_mod["fetch"]

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = []
            self.trust_env = True

        def get(self, url, timeout=60):
            self.calls.append(url)
            if "primary" in url:
                raise fetch_mod.requests.RequestException("timeout")
            return FakeResponse("<html><body><main><h1>minimap2 manual</h1></main></body></html>")

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    session = FakeSession()
    monkeypatch.setattr(fetch_mod.requests, "Session", lambda: session)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "minimap2",
                "section": "alignment",
                "page_name": "minimap2/manual",
                "title": "minimap2 manual",
                "url": "https://example.org/primary",
                "fallback_urls": ["https://example.org/fallback"],
            }
        ],
    )
    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)

    assert count == 1
    assert session.trust_env is False
    assert session.calls == ["https://example.org/primary", "https://example.org/fallback"]


def test_parse_qe_def_handles_compact_braces_and_option_info(tmp_path):
    def_file = tmp_path / "INPUT_PW.def"
    def_file.write_text(
        """
-program pw.x

namelist SYSTEM {
  var occupations {
    default{'smearing'}
    info{Occupation control}
    options{
      opt -val 'fixed' info{Keep occupations fixed}
      opt -val 'smearing' info{Use electronic smearing}
    }
  }
}
""",
        encoding="utf-8",
    )

    rows = _parse_qe_def(def_file)

    assert len(rows) == 1
    row = rows[0]
    assert row["page_name"] == "pw.x/SYSTEM/occupations"
    assert row["default_val"] == "'smearing'"
    assert "Occupation control" in row["content"]
    assert "Options: fixed, smearing" in row["content"]
    assert "Keep occupations fixed" in row["content"]
    assert "Use electronic smearing" in row["content"]


def test_toolref_show_falls_back_to_program_manual_page(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "bioinformatics"
    vdir = tdir / "2026-03-curated"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "bioinformatics",
            "2026-03-curated",
            "minimap2",
            "alignment",
            "minimap2/manual",
            "minimap2 manual",
            "manual page",
            "manual content",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "bioinformatics",
            "2026-03-curated",
            "minimap2",
            "alignment",
            "minimap2/options",
            "minimap2 options",
            "options page",
            "options content",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_show("bioinformatics", "minimap2", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "minimap2/manual"


def test_parse_lammps_rst_surfaces_aliases_for_search(tmp_path):
    rst = tmp_path / "fix_nh.rst"
    rst.write_text(
        """
fix nvt command
================

.. index:: fix nvt
.. index:: fix npt
.. index:: fix nph

Syntax
"""
        """""

.. code-block:: LAMMPS

   fix ID group-ID style_name keyword value ...

Description
"""
        """"""
        """"

Thermostat and barostat.
""",
        encoding="utf-8",
    )

    parsed = _parse_lammps_rst(rst)[0]

    assert "Aliases: fix nvt, fix npt, fix nph" in parsed["synopsis"]
    assert "fix npt" in parsed["content"]


def test_toolref_show_qe_prefers_exact_program_title_match(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "qe"
    vdir = tdir / "7.5"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("qe", "7.5", "pw.x", "ELECTRONS", "pw.x/ELECTRONS/conv_thr", "conv_thr", "", "exact"),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("qe", "7.5", "pw.x", "CONTROL", "pw.x/CONTROL/forc_conv_thr", "forc_conv_thr", "", "other"),
    )
    conn.commit()
    conn.close()

    rows = toolref_show("qe", "pw", "conv_thr", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "pw.x/ELECTRONS/conv_thr"


def test_toolref_show_lammps_resolves_alias_from_query(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "lammps"
    vdir = tdir / "stable"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "lammps",
            "stable",
            "lammps",
            "fix",
            "lammps/fix_nh",
            "fix nvt command",
            "fix ID group-ID style_name keyword value ... | Aliases: fix nvt, fix npt, fix nph",
            "Alias keys: |fix nvt| |fix npt| |fix nph|\nAliases: fix nvt, fix npt, fix nph",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "lammps",
            "stable",
            "lammps",
            "fix",
            "lammps/fix_npt_asphere",
            "fix npt/asphere command",
            "fix ID group-ID npt/asphere keyword value ... | Aliases: fix npt/asphere",
            "Alias keys: |fix npt/asphere|",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_show("lammps", "fix_npt", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "lammps/fix_nh"


def test_toolref_search_lammps_boosts_exact_alias_match(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "lammps"
    vdir = tdir / "stable"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "lammps",
            "stable",
            "lammps",
            "howto",
            "lammps/Howto_barostat",
            "Howto barostat",
            "barostat notes",
            "NPT barostat overview",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "lammps",
            "stable",
            "lammps",
            "fix",
            "lammps/fix_nh",
            "fix nvt command",
            "fix ID group-ID style_name keyword value ... | Aliases: fix nvt, fix npt, fix nph",
            "Aliases: fix nvt, fix npt, fix nph",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("lammps", "fix npt", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "lammps/fix_nh"


def test_toolref_search_fallback_keeps_version_program_and_section_filters(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "qe"
    vdir = tdir / "7.5"
    other_vdir = tdir / "7.4"
    vdir.mkdir(parents=True)
    other_vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.executemany(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                "qe",
                "7.5",
                "pw.x",
                "SYSTEM",
                "pw.x/SYSTEM/ecutwfc",
                "pw.x ecutwfc",
                "pw.x system cutoff",
                "pw.x cutoff variable",
            ),
            (
                "qe",
                "7.4",
                "pw.x",
                "SYSTEM",
                "pw.x/SYSTEM/legacy",
                "pw.x legacy",
                "pw.x old version",
                "pw.x legacy variable",
            ),
            (
                "qe",
                "7.5",
                "cp.x",
                "SYSTEM",
                "cp.x/SYSTEM/other",
                "cp.x mentions pw.x",
                "cp.x unrelated page",
                "pw.x appears here but should be filtered out",
            ),
            (
                "qe",
                "7.5",
                "pw.x",
                "ELECTRONS",
                "pw.x/ELECTRONS/conv_thr",
                "pw.x conv_thr",
                "pw.x wrong section",
                "pw.x wrong section result",
            ),
        ],
    )
    conn.commit()
    conn.close()

    rows = toolref_search("qe", "pw.x", program="pw.x", section="SYSTEM", cfg=None)

    assert rows
    assert [row["page_name"] for row in rows] == ["pw.x/SYSTEM/ecutwfc"]
    assert {row["version"] for row in rows} == {"7.5"}
    assert {row["program"] for row in rows} == {"pw.x"}
    assert {row["section"] for row in rows} == {"SYSTEM"}


def test_toolref_search_scores_each_row_once(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]
    search_mod = toolref_mod["search"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "lammps"
    vdir = tdir / "stable"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.executemany(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("lammps", "stable", "lammps", "fix", "lammps/fix_nh", "fix nvt command", "alias", "fix npt"),
            ("lammps", "stable", "lammps", "howto", "lammps/Howto_barostat", "Howto barostat", "notes", "npt"),
        ],
    )
    conn.commit()
    conn.close()

    seen: list[str] = []

    def fake_score(tool: str, normalized_query: str, expanded_query: str, row: sqlite3.Row) -> tuple[int, float]:
        seen.append(row["page_name"])
        return (10 if row["page_name"].endswith("fix_nh") else 5, float(row["rank"] or 0.0))

    monkeypatch.setattr(search_mod, "_score_search_result", fake_score)

    rows = search_mod.toolref_search("lammps", "fix npt", cfg=None)

    assert rows
    assert seen == ["lammps/fix_nh", "lammps/Howto_barostat"]


def test_parse_gromacs_mdp_block_keeps_option_descriptions(tmp_path):
    rst = tmp_path / "mdp-options.rst"
    rst.write_text(
        """
.. mdp:: pcoupl

   .. mdp-value:: no

      No pressure coupling.

   .. mdp-value:: Parrinello-Rahman

      Extended-ensemble pressure coupling.

.. mdp:: constraints

   Controls which bonds become rigid.

   .. mdp-value:: h-bonds

      Convert the bonds with H-atoms to constraints.
""",
        encoding="utf-8",
    )

    records = __import__("scholaraio.toolref", fromlist=["_parse_gromacs_rst"])._parse_gromacs_rst(rst)
    pcoupl = next(r for r in records if r["title"] == "pcoupl")
    constraints = next(r for r in records if r["title"] == "constraints")

    assert "Parrinello-Rahman" in pcoupl["synopsis"]
    assert "Extended-ensemble pressure coupling" in pcoupl["content"]
    assert "h-bonds" in constraints["synopsis"]
    assert "Convert the bonds with H-atoms to constraints." in constraints["content"]


def test_expand_search_query_adds_gromacs_aliases():
    expanded = _expand_search_query("gromacs", "Parrinello Rahman")
    assert "pcoupl" in expanded
    expanded = _expand_search_query("gromacs", "v-rescale thermostat")
    assert "tcoupl" in expanded
    expanded = _expand_search_query("gromacs", "constraints h-bonds")
    assert "constraints" in expanded
    expanded = _expand_search_query("gromacs", "temperature coupling")
    assert "tcoupl" in expanded
    expanded = _expand_search_query("gromacs", "pressure coupling")
    assert "pcoupl" in expanded


def test_score_search_result_matches_legacy_for_lammps_alias_row(toolref_mod):
    search_mod = toolref_mod["search"]
    legacy_mod = toolref_mod["legacy"]

    query = "fix npt"
    normalized_query = search_mod._normalize_search_query(query)
    expanded_query = search_mod._expand_search_query("lammps", query)
    row = {
        "title": "fix nvt command",
        "page_name": "lammps/fix_nh",
        "synopsis": "fix ID group-ID style_name keyword value ... | Aliases: fix nvt, fix npt, fix nph",
        "content": "Alias keys: |fix nvt| |fix npt| |fix nph|",
        "section": "fix",
        "program": "lammps",
        "rank": -4.8,
    }

    assert search_mod._score_search_result(
        "lammps", normalized_query, expanded_query, row
    ) == legacy_mod._score_search_result("lammps", normalized_query, expanded_query, row)


def test_score_search_result_matches_legacy_for_openfoam_row(toolref_mod):
    search_mod = toolref_mod["search"]
    legacy_mod = toolref_mod["legacy"]

    query = "y plus"
    normalized_query = search_mod._normalize_search_query(query)
    expanded_query = search_mod._expand_search_query("openfoam", query)
    row = {
        "title": "yplus",
        "page_name": "openfoam/yPlus",
        "synopsis": "post processing field function object",
        "content": "y plus wall function boundary layer",
        "section": "post-processing",
        "program": "yPlus",
        "rank": -7.1,
    }

    assert search_mod._score_search_result(
        "openfoam", normalized_query, expanded_query, row
    ) == legacy_mod._score_search_result("openfoam", normalized_query, expanded_query, row)


def test_toolref_search_matches_legacy_tie_break_order(tmp_path, monkeypatch, toolref_mod):
    search_mod = toolref_mod["search"]
    db_path = tmp_path / "toolref.db"
    db_path.write_text("", encoding="utf-8")

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return list(self._rows)

    class FakeConn:
        def __init__(self, rows):
            self.rows = rows
            self.row_factory = None

        def execute(self, _sql, _params):
            return FakeCursor(self.rows)

        def close(self):
            return None

    rows = [
        {
            "id": 1,
            "tool": "gromacs",
            "version": "2024",
            "program": "gromacs",
            "section": "mdp",
            "page_name": "gromacs/mdp/tau-p",
            "title": "tau-p",
            "category": "mdp",
            "var_type": "",
            "default_val": "",
            "synopsis": "MDP parameter",
            "content": "The time constant for pressure coupling.",
            "rank": -18.0,
        },
        {
            "id": 2,
            "tool": "gromacs",
            "version": "2024",
            "program": "gromacs",
            "section": "mdp",
            "page_name": "gromacs/mdp/ref-p",
            "title": "ref-p",
            "category": "mdp",
            "var_type": "",
            "default_val": "",
            "synopsis": "MDP parameter",
            "content": "The reference setting for pressure coupling.",
            "rank": -21.0,
        },
    ]

    monkeypatch.setattr(search_mod, "_db_path", lambda tool, cfg=None: db_path)
    monkeypatch.setattr(search_mod, "_current_link", lambda tool, cfg=None: tmp_path / "current")
    monkeypatch.setattr(search_mod.sqlite3, "connect", lambda _path: FakeConn(rows))

    results = search_mod.toolref_search("gromacs", "pressure coupling", cfg=None)

    assert [row["page_name"] for row in results[:2]] == ["gromacs/mdp/ref-p", "gromacs/mdp/tau-p"]


def test_toolref_search_gromacs_boosts_parameter_hits(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "gromacs"
    vdir = tdir / "2024"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "gromacs",
            "2024",
            "gromacs",
            "mdp",
            "gromacs/mdp/pcoupl",
            "pcoupl",
            "MDP parameter | Options: no, Parrinello-Rahman",
            "pcoupl Parrinello-Rahman pressure coupling tau-p ref-p",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "gromacs",
            "2024",
            "gromacs",
            "general",
            "gromacs/general/physical_validation",
            "Physical validation",
            "General notes",
            "Parrinello Rahman mentioned in passing",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("gromacs", "Parrinello Rahman", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "gromacs/mdp/pcoupl"


def test_toolref_search_gromacs_v_rescale_maps_to_tcoupl(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "gromacs"
    vdir = tdir / "2024"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "gromacs",
            "2024",
            "gromacs",
            "mdp",
            "gromacs/mdp/tcoupl",
            "tcoupl",
            "MDP parameter | Options: no, nose-hoover, v-rescale",
            "tcoupl v rescale thermostat temperature coupling tau t ref t",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "gromacs",
            "2024",
            "gromacs",
            "general",
            "gromacs/general/2020.4",
            "2020.4",
            "release notes",
            "v rescale mentioned in release notes",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("gromacs", "v-rescale thermostat", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "gromacs/mdp/tcoupl"


def test_toolref_search_gromacs_pressure_coupling_prefers_pcoupl(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "gromacs"
    vdir = tdir / "2024"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "gromacs",
            "2024",
            "gromacs",
            "mdp",
            "gromacs/mdp/pcoupl",
            "pcoupl",
            "pressure coupling",
            "Pressure coupling master switch",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "gromacs",
            "2024",
            "gromacs",
            "mdp",
            "gromacs/mdp/pcoupltype",
            "pcoupltype",
            "pressure coupling type",
            "Select isotropic or anisotropic pressure coupling type",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("gromacs", "pressure coupling", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "gromacs/mdp/pcoupl"


def test_toolref_search_bioinformatics_multiple_sequence_alignment_prefers_mafft(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "bioinformatics"
    vdir = tdir / "2026-03-curated"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "bioinformatics",
            "2026-03-curated",
            "samtools",
            "alignment",
            "samtools/manual",
            "samtools manual",
            "manual",
            "General utilities for FASTA and SAM workflows",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "bioinformatics",
            "2026-03-curated",
            "mafft",
            "phylogenetics",
            "mafft/manual",
            "MAFFT manual",
            "multiple sequence alignment",
            "Multiple sequence alignment for FASTA inputs",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("bioinformatics", "multiple sequence alignment fasta", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "mafft/manual"


def test_toolref_search_bioinformatics_bam_indexing_prefers_samtools_index(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    from scholaraio import toolref as mod

    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "bioinformatics"
    vdir = tdir / "2026-03-curated"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "bioinformatics",
            "2026-03-curated",
            "samtools",
            "alignment",
            "samtools/sort",
            "samtools sort",
            "sort bam",
            "Sort BAM files before indexing",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "bioinformatics",
            "2026-03-curated",
            "samtools",
            "alignment",
            "samtools/index",
            "samtools index",
            "index bam",
            "Create BAM indexes for region access",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("bioinformatics", "bam indexing", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "samtools/index"


def test_toolref_search_openfoam_boosts_yplus_page(tmp_path, monkeypatch, toolref_mod):
    import sqlite3

    mod = toolref_mod["api"]
    paths_mod = toolref_mod["paths"]

    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    tdir = tmp_path / "openfoam"
    vdir = tdir / "2312"
    vdir.mkdir(parents=True)
    (tdir / "current").symlink_to(vdir, target_is_directory=True)

    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    conn.executescript(mod._PAGES_SCHEMA)
    conn.executescript(mod._FTS_SCHEMA)
    conn.executescript(mod._FTS_TRIGGERS)
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "openfoam",
            "2312",
            "yPlus",
            "post-processing",
            "openfoam/yPlus",
            "yPlus",
            "wall distance non-dimensionalisation",
            "yPlus function object wall y plus boundary layer",
        ),
    )
    conn.execute(
        """INSERT INTO toolref_pages
           (tool, version, program, section, page_name, title, synopsis, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "openfoam",
            "2312",
            "functionObjects",
            "post-processing",
            "openfoam/functionObjects",
            "function objects",
            "overview",
            "post processing overview mentioning yPlus",
        ),
    )
    conn.commit()
    conn.close()

    rows = toolref_search("openfoam", "y plus", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "openfoam/yPlus"
