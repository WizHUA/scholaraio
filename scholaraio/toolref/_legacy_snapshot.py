"""
toolref.py — 科学计算工具文档知识库
====================================

多版本工具文档管理：拉取（fetch）、版本切换（use）、精确查看（show）、
全文搜索（search）。数据存储在 ``data/toolref/<tool>/<version>/``，
``current`` 符号链接指向当前活跃版本。

支持的工具及文档格式：
- Quantum ESPRESSO: ``.def`` 文件（Tcl-like DSL，机器可解析参数定义）
- LAMMPS: ``.rst`` 文件（Sphinx reStructuredText，每命令一文件）
- GROMACS: ``.rst`` 文件（Sphinx，含自定义 ``.. mdp::`` 指令）

用法::

    from scholaraio.toolref import toolref_fetch, toolref_show, toolref_search
    toolref_fetch("qe", version="7.5")
    result = toolref_show("qe", "pw", "ecutwfc")
    results = toolref_search("qe", "wavefunction cutoff")
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import textwrap
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from scholaraio.log import ui

if TYPE_CHECKING:
    from scholaraio.config import Config

_log = logging.getLogger(__name__)

_DEFAULT_TOOLREF_DIR = Path("data/toolref")
_MANIFEST_REQUEST_TIMEOUT = (10, 20)
_OPENFOAM_DISCOVERY_TIMEOUT = (5, 10)
_OPENFOAM_MAX_DISCOVERY_PAGES = 800
_OPENFOAM_DISCOVERY_SEEDS = ("fundamentals/", "tools/")
_BIO_DISCOVERY_TIMEOUT = (5, 15)
_BIO_DISCOVERED_PAGE_ALIASES = {
    "iqtree/ultrafast-bootstrap": {
        "source_page": "iqtree/ultrafast-bootstrap-parameters",
        "anchor": "ultrafast-bootstrap-parameters",
    },
}

# ============================================================================
#  Tool registry — maps tool name to repo/doc-path/format metadata
# ============================================================================

TOOL_REGISTRY: dict[str, dict] = {
    "qe": {
        "display_name": "Quantum ESPRESSO",
        "source_type": "git",
        "repo": "https://github.com/QEF/q-e.git",
        "tag_prefix": "qe-",
        "doc_path": None,  # scattered across */Doc/
        "doc_glob": "**/INPUT_*.def",
        "format": "def",
    },
    "lammps": {
        "display_name": "LAMMPS",
        "source_type": "git",
        "repo": "https://github.com/lammps/lammps.git",
        "tag_prefix": "stable_",
        "doc_path": "doc/src",
        "doc_glob": "*.rst",
        "format": "rst",
    },
    "gromacs": {
        "display_name": "GROMACS",
        "source_type": "git",
        "repo": "https://github.com/gromacs/gromacs.git",
        "tag_prefix": "release-",
        "doc_path": "docs",
        "doc_glob": "**/*.rst",
        "format": "rst",
    },
    "openfoam": {
        "display_name": "OpenFOAM",
        "source_type": "manifest",
        "manifest_name": "openfoam",
        "format": "html",
        "default_version": "2312",
    },
    "bioinformatics": {
        "display_name": "Bioinformatics Toolchain",
        "source_type": "manifest",
        "manifest_name": "bioinformatics",
        "format": "html",
        "default_version": "2026-03-curated",
    },
}

# ============================================================================
#  Path helpers
# ============================================================================


def _toolref_root(cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg._root / "data" / "toolref"
    return _DEFAULT_TOOLREF_DIR


def _tool_dir(tool: str, cfg: Config | None = None) -> Path:
    return _toolref_root(cfg) / tool


def _version_dir(tool: str, version: str, cfg: Config | None = None) -> Path:
    return _tool_dir(tool, cfg) / version


def _current_link(tool: str, cfg: Config | None = None) -> Path:
    return _tool_dir(tool, cfg) / "current"


def _db_path(tool: str, cfg: Config | None = None) -> Path:
    return _tool_dir(tool, cfg) / "toolref.db"


def validate_tool_name(name: str) -> bool:
    """Return True if *name* is a known, safe tool identifier."""
    return name in TOOL_REGISTRY


def _validate_version(version: str) -> bool:
    if not version or os.path.isabs(version):
        return False
    return "/" not in version and "\\" not in version and ".." not in version


def _slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return value.strip("-") or "page"


def _normalize_program_filter(tool: str, program: str) -> str:
    prog = program.lower().strip()
    if tool == "qe" and prog and not prog.endswith(".x"):
        prog += ".x"
    return prog


def _normalize_alias_phrase(*parts: str) -> str:
    phrase = " ".join((p or "").strip().lower() for p in parts if p and p.strip())
    phrase = phrase.replace("_", " ")
    phrase = re.sub(r"\s+", " ", phrase)
    return phrase.strip()


def _tokenize_rank_text(text: str) -> list[str]:
    normalized = _normalize_alias_phrase(text)
    return [token for token in normalized.split() if token]


def _expanded_terms(query: str) -> list[str]:
    return [part.strip().lower() for part in re.split(r"\s+or\s+", query, flags=re.IGNORECASE) if part.strip()]


def _score_search_result(
    tool: str,
    normalized_query: str,
    expanded_query: str,
    row: sqlite3.Row,
) -> tuple[int, float]:
    title = (row["title"] or "").lower()
    page_name = (row["page_name"] or "").lower()
    synopsis = (row["synopsis"] or "").lower()
    content = (row["content"] or "").lower()
    section = (row["section"] or "").lower()
    program = (row["program"] or "").lower()
    rank = float(row["rank"]) if row["rank"] is not None else 0.0

    score = 0
    normalized_slug = normalized_query.replace(" ", "-")
    normalized_snake = normalized_query.replace(" ", "_")
    query_tokens = _tokenize_rank_text(normalized_query)
    expanded_terms = _expanded_terms(expanded_query)

    if normalized_query and title == normalized_query:
        score += 120
    if normalized_query and (
        page_name.endswith(f"/{normalized_query}")
        or page_name.endswith(f"/{normalized_slug}")
        or page_name.endswith(f"/{normalized_snake}")
    ):
        score += 110
    if normalized_query and normalized_query in synopsis:
        score += 90
    if normalized_query and normalized_query in content:
        score += 70

    for term in expanded_terms:
        if not term or term == normalized_query:
            continue
        if title == term:
            score += 80
        if page_name.endswith(f"/{term}") or page_name.endswith(f"/{term.replace(' ', '-')}"):
            score += 75
        if term in synopsis:
            score += 55
        if term in content:
            score += 35

    if query_tokens:
        synopsis_hits = sum(1 for token in query_tokens if token in synopsis)
        content_hits = sum(1 for token in query_tokens if token in content)
        title_hits = sum(1 for token in query_tokens if token in title)
        score += title_hits * 18 + synopsis_hits * 12 + content_hits * 6

    if tool == "gromacs" and section == "mdp":
        score += 20
        if normalized_query == "pressure coupling":
            if page_name.endswith("/pcoupl"):
                score += 90
            if page_name.endswith("/pcoupltype"):
                score += 40
        if normalized_query == "temperature coupling" and page_name.endswith("/tcoupl"):
            score += 90
    if tool == "bioinformatics":
        if (
            "multiple sequence alignment" in normalized_query or normalized_query.startswith("msa")
        ) and program == "mafft":
            score += 140
        if (
            "bam indexing" in normalized_query
            or "samtools index" in normalized_query
            or "index bam" in normalized_query
        ) and page_name.endswith("/index"):
            score += 140
        if (
            "read mapping" in normalized_query or "nanopore" in normalized_query or "long read" in normalized_query
        ) and program == "minimap2":
            score += 120
        if ("variant calling" in normalized_query or "vcf" in normalized_query) and program == "bcftools":
            score += 110
        if (
            "phylogenetic tree" in normalized_query or "ultrafast bootstrap" in normalized_query
        ) and program == "iqtree":
            score += 120

    return score, rank


def _has_local_docs(tool: str, version: str, cfg: Config | None = None) -> bool:
    info = TOOL_REGISTRY[tool]
    vdir = _version_dir(tool, version, cfg)
    if not vdir.exists():
        return False
    if info["format"] == "def":
        return any((vdir / "def").glob("INPUT_*.def"))
    if info["format"] == "rst":
        return any((vdir / "src").rglob("*.rst"))
    if info["format"] == "html":
        page_count = (
            _manifest_page_count(vdir)
            if info.get("source_type") == "manifest"
            else len(list((vdir / "pages").glob("*.html")))
        )
        if not page_count:
            return False
        if info.get("source_type") == "manifest":
            expected = _expected_manifest_pages(tool, version, cfg)
            return page_count >= expected
        return True
    return False


def _manifest_page_count(vdir: Path) -> int:
    pages_dir = vdir / "pages"
    if not pages_dir.exists():
        return 0
    count = 0
    for html_path in pages_dir.glob("*.html"):
        if html_path.with_suffix(".json").exists():
            count += 1
    return count


def _manifest_snapshot_path(vdir: Path) -> Path:
    return vdir / "manifest.json"


def _load_manifest_snapshot(vdir: Path) -> list[dict] | None:
    path = _manifest_snapshot_path(vdir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def _write_manifest_snapshot(vdir: Path, manifest: list[dict]) -> None:
    _manifest_snapshot_path(vdir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _expected_manifest_pages(tool: str, version: str, cfg: Config | None = None) -> int:
    vdir = _version_dir(tool, version, cfg)
    snapshot = _load_manifest_snapshot(vdir)
    if snapshot:
        return len(snapshot)
    return len(_build_manifest(tool, version))


def _manifest_present_page_names(vdir: Path) -> set[str]:
    pages_dir = vdir / "pages"
    if not pages_dir.exists():
        return set()
    names: set[str] = set()
    for meta_path in pages_dir.glob("*.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        page_name = payload.get("page_name")
        if page_name and meta_path.with_suffix(".html").exists():
            names.add(page_name)
    return names


def _manifest_missing_page_names(vdir: Path, manifest: list[dict]) -> list[str]:
    present = _manifest_present_page_names(vdir)
    return [item["page_name"] for item in manifest if item["page_name"] not in present]


def _copy_manifest_page_from_cache(src_vdir: Path, dst_vdir: Path, page_name: str) -> bool:
    src_pages = src_vdir / "pages"
    dst_pages = dst_vdir / "pages"
    if not src_pages.exists() or not dst_pages.exists():
        return False

    for meta_path in src_pages.glob("*.json"):
        html_path = meta_path.with_suffix(".html")
        if not html_path.exists():
            continue
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("page_name") != page_name:
            continue
        shutil.copy2(html_path, dst_pages / html_path.name)
        shutil.copy2(meta_path, dst_pages / meta_path.name)
        return True
    return False


def _load_manifest_cached_html(vdir: Path, page_name: str) -> str | None:
    pages_dir = vdir / "pages"
    if not pages_dir.exists():
        return None
    for meta_path in pages_dir.glob("*.json"):
        html_path = meta_path.with_suffix(".html")
        if not html_path.exists():
            continue
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("page_name") != page_name:
            continue
        try:
            return html_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    return None


def _normalize_search_query(query: str) -> str:
    normalized = re.sub(r"[-_/]+", " ", query).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized or query.strip()


def _expand_search_query(tool: str, query: str) -> str:
    normalized = _normalize_search_query(query).lower()
    expansions: list[str] = [normalized]

    if tool == "openfoam":
        if "drag coefficient" in normalized or "drag coefficients" in normalized:
            expansions.extend(["forces", "force coeffs", "forcecoeffs"])
        if "force coefficients" in normalized:
            expansions.extend(["forces", "force coeffs", "forcecoeffs"])
        if "q criterion" in normalized:
            expansions.extend(["function objects", "post processing", "qcriterion", "q"])
        if "y plus" in normalized:
            expansions.extend(["yplus", "wall function", "boundary layer"])
        if "wall shear stress" in normalized:
            expansions.extend(["wallshearstress", "wall shear", "shear stress"])
        if "solver residuals" in normalized or normalized == "residuals":
            expansions.extend(["residuals", "linear solver", "convergence"])
        if "k omega sst" in normalized or "k-omega sst" in normalized or "sst turbulence" in normalized:
            expansions.extend(["komegasst", "turbulence model", "ras model", "sst"])
        if "numerical schemes" in normalized:
            expansions.extend(["fvschemes", "discretisation schemes", "fv schemes"])
        if "linear solver settings" in normalized or "solver settings" in normalized:
            expansions.extend(["fvsolution", "linear solver", "solver controls"])
    elif tool == "lammps":
        if "phase transition pressure" in normalized or "shock pressure" in normalized:
            expansions.extend(["fix_nphug", "fix_msst", "fix_qbmsst", "shock"])
    elif tool == "qe":
        if "ecut rho" in normalized:
            expansions.append("ecutrho")
        if "ecut wfc" in normalized:
            expansions.append("ecutwfc")
    elif tool == "gromacs":
        if "parrinello rahman" in normalized or "parrinello-rahman" in normalized:
            expansions.extend(["pcoupl", "barostat", "pressure coupling"])
        if "v rescale thermostat" in normalized or "v-rescale thermostat" in normalized:
            expansions.extend(["tcoupl", "v rescale", "temperature coupling", "tau t", "ref t"])
        if "nose hoover thermostat" in normalized or "nose-hoover thermostat" in normalized:
            expansions.extend(["tcoupl", "nose hoover", "temperature coupling", "tau t"])
        if "constraints h bonds" in normalized or "constraints h-bonds" in normalized:
            expansions.extend(["constraints", "h bonds", "constraint algorithm"])
        if normalized == "temperature coupling" or "temperature coupling" in normalized:
            expansions.extend(["tcoupl", "tau t", "ref t"])
        if normalized == "pressure coupling" or "pressure coupling" in normalized:
            expansions.extend(["pcoupl", "pcoupltype", "tau p", "ref p"])
    elif tool == "bioinformatics":
        if "phylogenetic tree" in normalized:
            expansions.extend(["iqtree", "mafft", "phylogenetics"])
        if "bootstrap tree" in normalized or "bootstrap support" in normalized or "ultrafast bootstrap" in normalized:
            expansions.extend(["iqtree", "ultrafast bootstrap", "ufboot", "phylogenetics"])
        if "read mapping" in normalized or "long read" in normalized or "nanopore" in normalized:
            expansions.extend(["minimap2", "alignment", "long reads", "ont"])
        if "multiple sequence alignment" in normalized or "msa" in normalized:
            expansions.extend(["mafft", "alignment", "fasta"])
        if "bam indexing" in normalized or "index bam" in normalized:
            expansions.extend(["samtools index", "samtools", "bam index"])
        if "mutation" in normalized:
            expansions.extend(["bcftools", "samtools", "variant calling"])
        if "variant calling" in normalized or "vcf" in normalized:
            expansions.extend(["bcftools", "bcftools call", "bcftools mpileup"])
        if "protein structure" in normalized or "folding" in normalized:
            expansions.extend(["esmfold", "protein structure prediction", "transformers"])

    deduped: list[str] = []
    for item in expansions:
        if item and item not in deduped:
            deduped.append(item)
    return " OR ".join(deduped) if len(deduped) > 1 else deduped[0]


def _build_openfoam_manifest(version: str) -> list[dict]:
    base = f"https://doc.openfoam.com/{version}"
    return [
        {
            "program": "simpleFoam",
            "section": "solver",
            "page_name": "openfoam/simpleFoam",
            "title": "simpleFoam",
            "url": f"{base}/tools/processing/solvers/rtm/incompressible/simpleFoam/",
        },
        {
            "program": "pimpleFoam",
            "section": "solver",
            "page_name": "openfoam/pimpleFoam",
            "title": "pimpleFoam",
            "url": f"{base}/tools/processing/solvers/rtm/incompressible/pimpleFoam/",
        },
        {
            "program": "rhoSimpleFoam",
            "section": "solver",
            "page_name": "openfoam/rhoSimpleFoam",
            "title": "rhoSimpleFoam",
            "url": f"{base}/tools/processing/solvers/rtm/compressible/rhoSimpleFoam/",
        },
        {
            "program": "blockMesh",
            "section": "mesh",
            "page_name": "openfoam/blockMesh",
            "title": "blockMesh",
            "url": f"{base}/tools/pre-processing/mesh/generation/blockMesh/blockmesh/",
        },
        {
            "program": "snappyHexMesh",
            "section": "mesh",
            "page_name": "openfoam/snappyHexMesh",
            "title": "snappyHexMesh",
            "url": f"{base}/tools/pre-processing/mesh/generation/snappyhexmesh/",
        },
        {
            "program": "controlDict",
            "section": "dictionary",
            "page_name": "openfoam/controlDict",
            "title": "controlDict",
            "url": f"{base}/fundamentals/case-structure/controldict/",
        },
        {
            "program": "fvSchemes",
            "section": "dictionary",
            "page_name": "openfoam/fvSchemes",
            "title": "fvSchemes",
            "url": f"{base}/fundamentals/case-structure/fvschemes/",
        },
        {
            "program": "fvSolution",
            "section": "dictionary",
            "page_name": "openfoam/fvSolution",
            "title": "fvSolution",
            "url": f"{base}/fundamentals/case-structure/fvsolution/",
        },
        {
            "program": "kOmegaSST",
            "section": "model",
            "page_name": "openfoam/kOmegaSST",
            "title": "kOmegaSST",
            "url": f"{base}/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/",
        },
        {
            "program": "functionObjects",
            "section": "post-processing",
            "page_name": "openfoam/functionObjects",
            "title": "function objects",
            "url": f"{base}/tools/post-processing/function-objects/",
        },
        {
            "program": "forces",
            "section": "post-processing",
            "page_name": "openfoam/forces",
            "title": "forces",
            "url": f"{base}/tools/post-processing/function-objects/forces/",
        },
        {
            "program": "forceCoeffs",
            "section": "post-processing",
            "page_name": "openfoam/forceCoeffs",
            "title": "forceCoeffs",
            "url": f"{base}/tools/post-processing/function-objects/forces/forceCoeffs/",
        },
        {
            "program": "Q",
            "section": "post-processing",
            "page_name": "openfoam/Q",
            "title": "Q",
            "url": f"{base}/tools/post-processing/function-objects/field/Q/",
        },
        {
            "program": "yPlus",
            "section": "post-processing",
            "page_name": "openfoam/yPlus",
            "title": "yPlus",
            "url": f"{base}/tools/post-processing/function-objects/field/yPlus/",
        },
        {
            "program": "wallShearStress",
            "section": "post-processing",
            "page_name": "openfoam/wallShearStress",
            "title": "wallShearStress",
            "url": f"{base}/tools/post-processing/function-objects/field/wallShearStress/",
        },
        {
            "program": "residuals",
            "section": "solver-control",
            "page_name": "openfoam/residuals",
            "title": "Residuals",
            "url": f"{base}/tools/processing/numerics/solvers/residuals/",
        },
    ]


_OPENFOAM_CORE_PAGE_MAP: dict[str, tuple[str, str, str, str]] = {
    "tools/processing/solvers/rtm/incompressible/simpleFoam/": (
        "openfoam/simpleFoam",
        "simpleFoam",
        "simpleFoam",
        "solver",
    ),
    "tools/processing/solvers/rtm/incompressible/pimpleFoam/": (
        "openfoam/pimpleFoam",
        "pimpleFoam",
        "pimpleFoam",
        "solver",
    ),
    "tools/processing/solvers/rtm/compressible/rhoSimpleFoam/": (
        "openfoam/rhoSimpleFoam",
        "rhoSimpleFoam",
        "rhoSimpleFoam",
        "solver",
    ),
    "tools/pre-processing/mesh/generation/blockMesh/blockmesh/": (
        "openfoam/blockMesh",
        "blockMesh",
        "blockMesh",
        "mesh",
    ),
    "tools/pre-processing/mesh/generation/snappyhexmesh/": (
        "openfoam/snappyHexMesh",
        "snappyHexMesh",
        "snappyHexMesh",
        "mesh",
    ),
    "fundamentals/case-structure/controldict/": ("openfoam/controlDict", "controlDict", "controlDict", "dictionary"),
    "fundamentals/case-structure/fvschemes/": ("openfoam/fvSchemes", "fvSchemes", "fvSchemes", "dictionary"),
    "fundamentals/case-structure/fvsolution/": ("openfoam/fvSolution", "fvSolution", "fvSolution", "dictionary"),
    "tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/": (
        "openfoam/kOmegaSST",
        "kOmegaSST",
        "kOmegaSST",
        "model",
    ),
    "tools/post-processing/function-objects/": (
        "openfoam/functionObjects",
        "functionObjects",
        "function objects",
        "post-processing",
    ),
    "tools/post-processing/function-objects/forces/": ("openfoam/forces", "forces", "forces", "post-processing"),
    "tools/post-processing/function-objects/forces/forceCoeffs/": (
        "openfoam/forceCoeffs",
        "forceCoeffs",
        "forceCoeffs",
        "post-processing",
    ),
    "tools/post-processing/function-objects/field/Q/": ("openfoam/Q", "Q", "Q", "post-processing"),
    "tools/post-processing/function-objects/field/yPlus/": ("openfoam/yPlus", "yPlus", "yPlus", "post-processing"),
    "tools/post-processing/function-objects/field/wallShearStress/": (
        "openfoam/wallShearStress",
        "wallShearStress",
        "wallShearStress",
        "post-processing",
    ),
    "tools/processing/numerics/solvers/residuals/": ("openfoam/residuals", "residuals", "Residuals", "solver-control"),
}


def _normalize_openfoam_doc_url(url: str, version: str, *, base_url: str = "https://doc.openfoam.com") -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = base_url.rstrip("/") + url
    elif not re.match(r"^https?://", url):
        url = base_url.rstrip("/") + "/" + url.lstrip("./")

    if not url.startswith(base_url.rstrip("/") + "/"):
        return None

    url = url.split("#", 1)[0].split("?", 1)[0]
    if not url.endswith("/"):
        url += "/"

    path = url.removeprefix(base_url.rstrip("/")).lstrip("/")
    if not path.startswith(f"{version}/"):
        return None
    rel = path[len(version) + 1 :]
    if not rel or any(rel.endswith(ext) for ext in (".css/", ".js/", ".png/", ".jpg/", ".svg/", ".pdf/", ".txt/")):
        return None
    return base_url.rstrip("/") + "/" + path


def _is_openfoam_doc_path_allowed(rel_path: str) -> bool:
    if not rel_path:
        return False
    return any(rel_path.startswith(prefix) for prefix in _OPENFOAM_DISCOVERY_SEEDS)


def _extract_openfoam_doc_links(html: str, version: str, *, base_url: str = "https://doc.openfoam.com") -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"""href=["']([^"'#?]+(?:/)?(?:#[^"']*)?)["']""", html, re.IGNORECASE):
        normalized = _normalize_openfoam_doc_url(match.group(1), version, base_url=base_url)
        if not normalized:
            continue
        rel = normalized.removeprefix(base_url.rstrip("/") + f"/{version}/")
        if not _is_openfoam_doc_path_allowed(rel):
            continue
        if normalized not in links:
            links.append(normalized)
    return links


def _classify_openfoam_section(rel_path: str) -> str:
    if rel_path.startswith("fundamentals/case-structure/"):
        return "dictionary"
    if rel_path.startswith("fundamentals/"):
        return "fundamentals"
    if rel_path.startswith("tools/pre-processing/mesh/"):
        return "mesh"
    if rel_path.startswith("tools/processing/solvers/"):
        return "solver"
    if rel_path.startswith("tools/processing/models/"):
        return "model"
    if rel_path.startswith("tools/processing/numerics/"):
        return "solver-control"
    if rel_path.startswith("tools/post-processing/"):
        return "post-processing"
    if rel_path.startswith("tools/"):
        return "tool"
    return "general"


def _discover_openfoam_manifest_bundle(version: str, session: requests.Session) -> tuple[list[dict], dict[str, str]]:
    base_url = "https://doc.openfoam.com"
    queue = [base_url.rstrip("/") + f"/{version}/{seed}" for seed in _OPENFOAM_DISCOVERY_SEEDS]
    seen: set[str] = set()
    discovered: set[str] = set()
    prefetched_html: dict[str, str] = {}

    while queue and len(seen) < _OPENFOAM_MAX_DISCOVERY_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = session.get(url, timeout=_OPENFOAM_DISCOVERY_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            _log.debug("OpenFOAM discovery skip %s: %s", url, e)
            continue
        prefetched_html[url] = resp.text

        rel = url.removeprefix(base_url.rstrip("/") + f"/{version}/")
        if _is_openfoam_doc_path_allowed(rel):
            discovered.add(url)

        for child in _extract_openfoam_doc_links(resp.text, version, base_url=base_url):
            if child not in seen and child not in queue:
                queue.append(child)

    if not discovered:
        return [], {}

    rel_paths = sorted(url.removeprefix(base_url.rstrip("/") + f"/{version}/") for url in discovered)
    slug_counts: dict[str, int] = {}
    for rel_path in rel_paths:
        slug = Path(rel_path.rstrip("/")).name
        slug_counts[slug] = slug_counts.get(slug, 0) + 1

    manifest: list[dict] = []
    for rel_path in rel_paths:
        mapped = _OPENFOAM_CORE_PAGE_MAP.get(rel_path)
        url = base_url.rstrip("/") + f"/{version}/{rel_path}"
        if mapped:
            page_name, program, title, section = mapped
        else:
            slug = Path(rel_path.rstrip("/")).name
            program = slug
            title = slug
            section = _classify_openfoam_section(rel_path)
            if slug_counts.get(slug, 0) == 1 and slug not in {"overview", "index"}:
                page_name = f"openfoam/{slug}"
            else:
                page_name = "openfoam/" + rel_path.rstrip("/").replace("/", "__")
        manifest.append(
            {
                "program": program,
                "section": section,
                "page_name": page_name,
                "title": title,
                "url": url,
            }
        )
    return manifest, prefetched_html


def _discover_openfoam_manifest(version: str, session: requests.Session) -> list[dict]:
    manifest, _ = _discover_openfoam_manifest_bundle(version, session)
    return manifest


def _build_bioinformatics_manifest(_version: str) -> list[dict]:
    return [
        {
            "program": "blastn",
            "section": "alignment",
            "page_name": "blast/blastn",
            "title": "BLAST+ user manual",
            "url": "https://www.ncbi.nlm.nih.gov/books/NBK279690/",
        },
        {
            "program": "minimap2",
            "section": "alignment",
            "page_name": "minimap2/manual",
            "title": "minimap2 manual",
            "url": "https://lh3.github.io/minimap2/minimap2.html",
            "fallback_urls": [
                "https://github.com/lh3/minimap2#readme",
            ],
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/manual",
            "title": "samtools manual",
            "url": "https://www.htslib.org/doc/samtools.html",
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/sort",
            "title": "samtools sort",
            "url": "https://www.htslib.org/doc/samtools-sort.html",
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/view",
            "title": "samtools view",
            "url": "https://www.htslib.org/doc/samtools-view.html",
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/index",
            "title": "samtools index",
            "url": "https://www.htslib.org/doc/samtools-index.html",
        },
        {
            "program": "bcftools",
            "section": "variant-calling",
            "page_name": "bcftools/manual",
            "title": "bcftools manual",
            "url": "https://samtools.github.io/bcftools/bcftools.html",
        },
        {
            "program": "bcftools",
            "section": "variant-calling",
            "page_name": "bcftools/call",
            "title": "bcftools call",
            "url": "https://samtools.github.io/bcftools/bcftools.html#call",
        },
        {
            "program": "bcftools",
            "section": "variant-calling",
            "page_name": "bcftools/mpileup",
            "title": "bcftools mpileup",
            "url": "https://samtools.github.io/bcftools/bcftools.html#mpileup",
        },
        {
            "program": "mafft",
            "section": "phylogenetics",
            "page_name": "mafft/manual",
            "title": "MAFFT manual",
            "url": "https://mafft.cbrc.jp/alignment/software/multithreading.html",
        },
        {
            "program": "iqtree",
            "section": "phylogenetics",
            "page_name": "iqtree/command-reference",
            "title": "IQ-TREE command reference",
            "url": "https://iqtree.github.io/doc/Command-Reference",
        },
        {
            "program": "iqtree",
            "section": "phylogenetics",
            "page_name": "iqtree/ultrafast-bootstrap",
            "title": "IQ-TREE ultrafast bootstrap",
            "url": "https://iqtree.github.io/doc/Command-Reference#ultrafast-bootstrap-parameters",
            "anchor": "ultrafast-bootstrap-parameters",
        },
        {
            "program": "esmfold",
            "section": "protein-structure",
            "page_name": "esmfold/huggingface-doc",
            "title": "ESM / ESMFold documentation",
            "url": "https://huggingface.co/docs/transformers/model_doc/esm",
        },
    ]


def _extract_html_headings_with_ids(html: str, *, min_level: int = 2, max_level: int = 3) -> list[dict]:
    headings: list[dict] = []
    pattern = re.compile(
        r"<h([1-6])\b[^>]*\bid=[\"']([^\"']+)[\"'][^>]*>(.*?)</h\1>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        level = int(match.group(1))
        if level < min_level or level > max_level:
            continue
        title = re.sub(r"<[^>]+>", "", unescape(match.group(3)))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        headings.append({"level": level, "id": match.group(2), "title": title})
    return headings


def _extract_html_anchor_fragment(html: str, anchor: str) -> str:
    body = _extract_html_main(html)
    heading_re = re.compile(
        r"<h([1-6])\b[^>]*\bid=[\"']([^\"']+)[\"'][^>]*>.*?</h\1>",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(heading_re.finditer(body))
    for idx, match in enumerate(matches):
        if match.group(2) != anchor:
            continue
        level = int(match.group(1))
        end = len(body)
        for nxt in matches[idx + 1 :]:
            if int(nxt.group(1)) <= level:
                end = nxt.start()
                break
        return body[match.start() : end]
    return body


def _discover_bioinformatics_manifest(
    version: str,
    session: requests.Session,
    base_manifest: list[dict],
    *,
    cache_vdir: Path | None = None,
) -> tuple[list[dict], dict[str, str]]:
    del version  # reserved for future versioned discovery rules
    prefetched_html: dict[str, str] = {}
    manifest_by_page = {item["page_name"]: dict(item) for item in base_manifest}

    for item in base_manifest:
        if item["page_name"] not in {"samtools/manual", "bcftools/manual", "iqtree/command-reference"}:
            continue
        try:
            resp = session.get(item["url"], timeout=_BIO_DISCOVERY_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            _log.debug("Bio discovery skip %s: %s", item["url"], e)
            if cache_vdir is not None:
                cached = _load_manifest_cached_html(cache_vdir, item["page_name"])
                if cached:
                    prefetched_html[item["url"]] = cached
            continue
        prefetched_html[item["url"]] = resp.text

    samtools_html = prefetched_html.get("https://www.htslib.org/doc/samtools.html")
    if samtools_html:
        seen_links: set[str] = set()
        for match in re.finditer(r'href=["\'](samtools-[a-z0-9-]+\.html)["\']', samtools_html, re.IGNORECASE):
            rel = match.group(1)
            if rel in seen_links:
                continue
            seen_links.add(rel)
            subcmd = rel.removeprefix("samtools-").removesuffix(".html")
            page_name = f"samtools/{subcmd}"
            manifest_by_page.setdefault(
                page_name,
                {
                    "program": "samtools",
                    "section": "alignment",
                    "page_name": page_name,
                    "title": f"samtools {subcmd}",
                    "url": f"https://www.htslib.org/doc/{rel}",
                },
            )

    bcftools_html = prefetched_html.get("https://samtools.github.io/bcftools/bcftools.html")
    if bcftools_html:
        for heading in _extract_html_headings_with_ids(bcftools_html):
            hid = heading["id"]
            if hid.startswith("_"):
                continue
            if not (
                heading["title"].lower().startswith("bcftools ")
                or hid in {"common_options", "expressions", "terminology"}
            ):
                continue
            page_name = f"bcftools/{hid.replace('_', '-')}"
            item = manifest_by_page.get(page_name, {})
            item.update(
                {
                    "program": "bcftools",
                    "section": "variant-calling",
                    "page_name": page_name,
                    "title": heading["title"],
                    "url": f"https://samtools.github.io/bcftools/bcftools.html#{hid}",
                    "anchor": hid,
                }
            )
            manifest_by_page[page_name] = item

    iqtree_html = prefetched_html.get("https://iqtree.github.io/doc/Command-Reference")
    if iqtree_html:
        for heading in _extract_html_headings_with_ids(iqtree_html):
            hid = heading["id"]
            if hid in {"command-reference", "example-usages"}:
                continue
            page_name = f"iqtree/{hid.replace('_', '-').replace(' ', '-')}"
            item = manifest_by_page.get(page_name, {})
            item.update(
                {
                    "program": "iqtree",
                    "section": "phylogenetics",
                    "page_name": page_name,
                    "title": heading["title"],
                    "url": f"https://iqtree.github.io/doc/Command-Reference#{hid}",
                    "anchor": hid,
                }
            )
            manifest_by_page[page_name] = item

    for page_name, alias in _BIO_DISCOVERED_PAGE_ALIASES.items():
        if page_name not in manifest_by_page or alias["source_page"] not in manifest_by_page:
            continue
        item = manifest_by_page[page_name]
        source_item = manifest_by_page[alias["source_page"]]
        item["url"] = source_item["url"]
        item["anchor"] = alias["anchor"]

    manifest = sorted(manifest_by_page.values(), key=lambda item: (item["program"], item["page_name"]))
    return manifest, prefetched_html


def _build_manifest(tool: str, version: str) -> list[dict]:
    info = TOOL_REGISTRY[tool]
    manifest_name = info.get("manifest_name")
    if manifest_name == "openfoam":
        return _build_openfoam_manifest(version)
    if manifest_name == "bioinformatics":
        return _build_bioinformatics_manifest(version)
    raise ValueError(f"{tool} 未定义 manifest")


# ============================================================================
#  DB schema
# ============================================================================

_PAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS toolref_pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool        TEXT NOT NULL,
    version     TEXT NOT NULL,
    program     TEXT,
    section     TEXT,
    page_name   TEXT NOT NULL,
    title       TEXT,
    category    TEXT,
    var_type    TEXT,
    default_val TEXT,
    synopsis    TEXT,
    content     TEXT NOT NULL,
    UNIQUE(tool, version, page_name)
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS toolref_fts USING fts5(
    page_name,
    title,
    synopsis,
    content,
    content=toolref_pages,
    content_rowid=id,
    tokenize='unicode61'
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS toolref_ai AFTER INSERT ON toolref_pages BEGIN
    INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
    VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
END;

CREATE TRIGGER IF NOT EXISTS toolref_ad AFTER DELETE ON toolref_pages BEGIN
    INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
    VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
END;

CREATE TRIGGER IF NOT EXISTS toolref_au AFTER UPDATE ON toolref_pages BEGIN
    INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
    VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
    INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
    VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
END;
"""


def _ensure_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_PAGES_SCHEMA)
    conn.executescript(_FTS_SCHEMA)
    conn.executescript(_FTS_TRIGGERS)
    return conn


# ============================================================================
#  QE .def parser
# ============================================================================


def _parse_qe_def(filepath: Path) -> list[dict]:
    """Parse a Quantum ESPRESSO .def file into a list of variable records.

    Each record represents one input parameter with fields:
    program, section (namelist), page_name, title, category, var_type,
    default_val, synopsis, content (full text block).
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")

    # extract program name from input_description line
    m = re.search(r"-program\s+(\S+)", text)
    program = m.group(1).strip("{}") if m else filepath.stem.replace("INPUT_", "").lower()

    records: list[dict] = []
    current_namelist = ""

    # state machine for brace-balanced parsing
    def _extract_braced(s: str, start: int) -> tuple[str, int]:
        """Extract content between balanced braces starting at s[start]='{'.
        Returns (content, end_index)."""
        if start >= len(s) or s[start] != "{":
            return "", start
        depth = 0
        i = start
        while i < len(s):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    return s[start + 1 : i], i + 1
            i += 1
        return s[start + 1 :], len(s)

    def _clean_text(t: str) -> str:
        """Strip QE markup (@b, @i, @ref, @tt, @br) and normalize whitespace."""
        t = re.sub(r"@b\s*\{([^}]*)\}", r"\1", t)
        t = re.sub(r"@i\s*\{([^}]*)\}", r"\1", t)
        t = re.sub(r"@ref\s+(\w+)", r"\1", t)
        t = re.sub(r"@tt\s*\{([^}]*)\}", r"\1", t)
        t = re.sub(r"@br\b", "\n", t)
        t = re.sub(r"@[a-z]+\s*", "", t)
        return textwrap.dedent(t).strip()

    def _parse_var_block(block: str, var_name: str) -> dict:
        """Parse a var {...} block, extracting type, default, info, options."""

        def _match_braced(field: str) -> str:
            match = re.search(rf"{field}\s*\{{", block)
            if not match:
                return ""
            value, _ = _extract_braced(block, match.end() - 1)
            return _clean_text(value)

        # type
        vtype = ""
        tm = re.search(r"-type\s+(\S+)", block)
        if tm:
            vtype = tm.group(1)

        # status
        status = ""
        sm = re.search(r"status\s*\{([^}]*)\}", block)
        if sm:
            status = sm.group(1).strip()

        # default
        default_val = _match_braced("default")

        # info
        info_text = _match_braced("info")

        # options
        options_text = ""
        om = re.search(r"options\s*\{", block)
        if om:
            raw_options_text, _ = _extract_braced(block, om.end() - 1)
            # extract opt -val entries
            opts = re.findall(r"opt\s+-val\s+'([^']+)'", raw_options_text)
            option_info = re.findall(r"info\s*\{([^}]*)\}", raw_options_text)
            if opts:
                options_text = "Options: " + ", ".join(opts)
                # also extract any info inside options
                if option_info:
                    options_text += "\n" + _clean_text(" ".join(option_info))

        # build synopsis
        parts = []
        if vtype:
            parts.append(f"Type: {vtype}")
        if default_val:
            parts.append(f"Default: {default_val}")
        if status:
            parts.append(f"Status: {status}")
        synopsis = "; ".join(parts) if parts else ""

        # build full content
        content_parts = []
        if synopsis:
            content_parts.append(synopsis)
        if info_text:
            content_parts.append(info_text)
        if options_text:
            content_parts.append(options_text)
        content = "\n\n".join(content_parts)

        return {
            "var_type": vtype,
            "default_val": default_val,
            "synopsis": synopsis,
            "content": content if content else f"{var_name}: {vtype}",
        }

    # scan for namelist and var/dimension/vargroup declarations
    pos = 0
    while pos < len(text):
        # match namelist
        nm = re.match(r"\s*namelist\s+(\w+)\s*\{", text[pos:])
        if nm:
            current_namelist = nm.group(1)
            pos += nm.end()
            continue

        # match var
        vm = re.match(r"\s*var\s+([\w()]+)\s*(?:-type\s+(\S+))?\s*\{", text[pos:])
        if vm:
            var_name = vm.group(1)
            brace_start = pos + vm.end() - 1
            block, end = _extract_braced(text, brace_start)
            parsed = _parse_var_block(
                f"-type {vm.group(2)} " + block if vm.group(2) else block,
                var_name,
            )
            page_name = f"{program}/{current_namelist}/{var_name}".strip("/")
            records.append(
                {
                    "program": program,
                    "section": current_namelist,
                    "page_name": page_name,
                    "title": var_name,
                    "category": "variable",
                    **parsed,
                }
            )
            pos = end
            continue

        # match dimension (array variable)
        dm = re.match(r"\s*dimension\s+([\w()]+)\s+.*?-type\s+(\S+)\s*\{", text[pos:])
        if dm:
            var_name = dm.group(1)
            brace_start = pos + dm.end() - 1
            block, end = _extract_braced(text, brace_start)
            parsed = _parse_var_block(f"-type {dm.group(2)} " + block, var_name)
            page_name = f"{program}/{current_namelist}/{var_name}".strip("/")
            records.append(
                {
                    "program": program,
                    "section": current_namelist,
                    "page_name": page_name,
                    "title": var_name,
                    "category": "dimension",
                    **parsed,
                }
            )
            pos = end
            continue

        # match vargroup
        vgm = re.match(r"\s*vargroup\s+.*?-type\s+(\S+)\s*\{", text[pos:])
        if vgm:
            brace_start = pos + vgm.end() - 1
            block, end = _extract_braced(text, brace_start)
            # extract var names inside vargroup
            vg_vars = re.findall(r"var\s+(\w+)", block)
            if vg_vars:
                parsed = _parse_var_block(
                    f"-type {vgm.group(1)} " + block,
                    ", ".join(vg_vars),
                )
                for vn in vg_vars:
                    page_name = f"{program}/{current_namelist}/{vn}".strip("/")
                    records.append(
                        {
                            "program": program,
                            "section": current_namelist,
                            "page_name": page_name,
                            "title": vn,
                            "category": "vargroup",
                            **parsed,
                        }
                    )
            pos = end
            continue

        # match card (store as a single record with its full content)
        cm = re.match(r"\s*card\s+([\w_]+)\s*\{", text[pos:])
        if cm:
            card_name = cm.group(1)
            brace_start = pos + cm.end() - 1
            block, end = _extract_braced(text, brace_start)
            page_name = f"{program}/card/{card_name}"
            records.append(
                {
                    "program": program,
                    "section": "card",
                    "page_name": page_name,
                    "title": card_name,
                    "category": "card",
                    "var_type": "",
                    "default_val": "",
                    "synopsis": f"Input card: {card_name}",
                    "content": _clean_text(block)[:4000],
                }
            )
            pos = end
            continue

        pos += 1

    return records


# ============================================================================
#  LAMMPS RST parser
# ============================================================================


def _parse_lammps_rst(filepath: Path) -> list[dict]:
    """Parse a LAMMPS .rst documentation file into records.

    Each LAMMPS doc file typically documents one command (fix, compute,
    pair_style, etc.) with sections: Syntax, Examples, Description,
    Restrictions, Related commands, Default.
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")
    stem = filepath.stem  # e.g. "fix_nh", "pair_lj"

    # extract command names from index directives
    commands = re.findall(r"\.\.\s+index::\s+(.+)", text)
    # filter out accelerator variants
    commands = [
        c.strip()
        for c in commands
        if "/gpu" not in c and "/intel" not in c and "/kk" not in c and "/omp" not in c and "/opt" not in c
    ]
    alias_commands: list[str] = []
    for command in commands:
        normalized_command = _normalize_alias_phrase(command)
        if normalized_command and normalized_command not in alias_commands:
            alias_commands.append(normalized_command)

    # extract first title (the primary command)
    title_match = re.search(r"^(.+?)\n={3,}", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else stem

    # detect command category from filename
    category = "other"
    for prefix in (
        "fix_",
        "compute_",
        "pair_",
        "bond_",
        "angle_",
        "dihedral_",
        "improper_",
        "dump_",
        "region_",
        "group_",
    ):
        if stem.startswith(prefix):
            category = prefix.rstrip("_")
            break

    # split into sections by RST headings (""" underlined)
    sections: dict[str, str] = {}
    section_pattern = re.compile(r'^(.+)\n"{3,}', re.MULTILINE)
    matches = list(section_pattern.finditer(text))
    for i, m in enumerate(matches):
        sec_name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[sec_name.lower()] = text[start:end].strip()

    # build synopsis from Syntax section
    synopsis = ""
    if "syntax" in sections:
        # extract first code-block content
        cb = re.search(r"\.\.\s+code-block::\s+LAMMPS\s*\n\n((?:\s+.+\n?)+)", sections["syntax"])
        if cb:
            synopsis = cb.group(1).strip().split("\n")[0].strip()
    if alias_commands:
        alias_text = ", ".join(alias_commands[:12])
        synopsis = f"{synopsis} | Aliases: {alias_text}" if synopsis else f"Aliases: {alias_text}"

    # build full content (Syntax + Description, truncated)
    content_parts = []
    if alias_commands:
        content_parts.append("Alias keys: " + " ".join(f"|{alias}|" for alias in alias_commands[:20]))
        content_parts.append("Aliases:\n" + "\n".join(f"- {alias}" for alias in alias_commands[:20]))
    if "syntax" in sections:
        content_parts.append("Syntax:\n" + sections["syntax"][:1000])
    if "description" in sections:
        content_parts.append("Description:\n" + sections["description"][:3000])
    if "restrictions" in sections:
        content_parts.append("Restrictions:\n" + sections["restrictions"][:500])
    if "default" in sections:
        content_parts.append("Default:\n" + sections["default"][:300])
    content = "\n\n".join(content_parts) if content_parts else text[:2000]

    records = [
        {
            "program": "lammps",
            "section": category,
            "page_name": f"lammps/{stem}",
            "title": title,
            "category": category,
            "var_type": "",
            "default_val": sections.get("default", "")[:200].strip(),
            "synopsis": synopsis,
            "content": content,
        }
    ]

    return records


# ============================================================================
#  GROMACS RST parser
# ============================================================================


def _parse_gromacs_rst(filepath: Path) -> list[dict]:
    """Parse a GROMACS .rst documentation file.

    For mdp-options.rst: extract each MDP parameter as a separate record.
    For other files: store as a single record per file.
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")
    stem = filepath.stem
    records: list[dict] = []

    # Special handling for mdp-options.rst (the core parameter reference)
    if stem == "mdp-options":
        starts = list(re.finditer(r"(?m)^\.\.\s+mdp::\s+(\S+)\s*$", text))
        for idx, match in enumerate(starts):
            param_name = match.group(1).strip()
            start = match.end()
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
            block = text[start:end].strip()

            values = [v.strip() for v in re.findall(r"(?m)^\s*\.\.\s+mdp-value::\s+(.+?)\s*$", block)]
            cleaned_lines: list[str] = []
            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith(".. mdp-value::"):
                    value = stripped.split("::", 1)[1].strip()
                    cleaned_lines.append(f"Option: {value}")
                    continue
                cleaned_lines.append(line.rstrip())
            cleaned = "\n".join(cleaned_lines)
            cleaned = re.sub(r":mdp:`([^`]+)`", r"\1", cleaned)
            cleaned = re.sub(r":mdp-value:`([^`]+)`", r"\1", cleaned)
            cleaned = re.sub(r"\s+\n", "\n", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

            synopsis = "MDP parameter"
            if values:
                synopsis += f" | Options: {', '.join(values[:8])}"

            records.append(
                {
                    "program": "gromacs",
                    "section": "mdp",
                    "page_name": f"gromacs/mdp/{param_name}",
                    "title": param_name,
                    "category": "mdp",
                    "var_type": "",
                    "default_val": "",
                    "synopsis": synopsis,
                    "content": f"{param_name}\n\n{cleaned[:3000]}",
                }
            )
        return records

    # For non-MDP files: store the whole file as one record
    # extract title
    title_match = re.search(r"^(.+?)\n={3,}", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else stem

    # determine section from path-like info in the file or filename
    section = "general"
    if "user-guide" in str(filepath):
        section = "user-guide"
    elif "reference-manual" in str(filepath):
        section = "reference-manual"
    elif "how-to" in str(filepath):
        section = "how-to"

    records.append(
        {
            "program": "gromacs",
            "section": section,
            "page_name": f"gromacs/{section}/{stem}",
            "title": title,
            "category": section,
            "var_type": "",
            "default_val": "",
            "synopsis": title,
            "content": text[:5000],
        }
    )
    return records


# ============================================================================
#  HTML manifest parsing (OpenFOAM / Bioinformatics)
# ============================================================================


def _extract_html_main(text: str) -> str:
    for pattern in (
        r"<main\b[^>]*>(.*?)</main>",
        r"<article\b[^>]*>(.*?)</article>",
        r"<body\b[^>]*>(.*?)</body>",
    ):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            body = m.group(1)
            h1_pos = body.lower().find("<h1")
            if h1_pos > 0:
                body = body[h1_pos:]
            return body
    return text


def _html_to_text(text: str) -> str:
    body = _extract_html_main(text)
    body = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", "", body, flags=re.IGNORECASE | re.DOTALL)

    code_blocks: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        block = unescape(m.group(1))
        block = re.sub(r"<[^>]+>", "", block)
        token = f"__CODE_BLOCK_{len(code_blocks)}__"
        code_blocks.append(block.strip())
        return f"\n{token}\n"

    body = re.sub(r"<pre\b[^>]*>(.*?)</pre>", _stash_code, body, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<code\b[^>]*>(.*?)</code>", _stash_code, body, flags=re.IGNORECASE | re.DOTALL)

    body = re.sub(r"</(h\d|p|div|section|article|li|tr|table|ul|ol)>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<li\b[^>]*>", "- ", body, flags=re.IGNORECASE)
    body = re.sub(r"<[^>]+>", "", body)
    body = unescape(body)

    for idx, block in enumerate(code_blocks):
        body = body.replace(f"__CODE_BLOCK_{idx}__", f"\n{block}\n")

    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    compact = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
    return "\n".join(compact).strip()


def _clean_manifest_text(text: str, title: str, program: str) -> str:
    anchor_patterns: list[tuple[str, bool]] = []
    if "BLAST" in title.upper():
        anchor_patterns.append((r"BLAST[^\n]*User Manual", True))
    anchor_patterns.extend(
        [
            (title, False),
            (program, False),
            (program.replace(".x", ""), False),
        ]
    )

    for anchor, is_regex in anchor_patterns:
        if not anchor:
            continue
        if is_regex:
            m = re.search(anchor, text)
            if m and m.start() > 0:
                text = text[m.start() :]
                break
        elif anchor in text:
            pos = text.find(anchor)
            if pos > 0:
                text = text[pos:]
                break

    stop_markers = (
        "Search results",
        "Found a content problem with this page?",
        "Want to get more involved?",
    )
    for marker in stop_markers:
        pos = text.find(marker)
        if pos > 0:
            text = text[:pos]

    cleaned_lines: list[str] = []
    skip_exact = {
        "Top",
        "Bookshelf",
        "Toggle navigation",
        "Doc",
        "Src",
        "Search",
        "< PrevNext >",
    }
    skip_prefixes = (
        "Copyright",
        "Last updated:",
        "Author(s):",
        "This work is licensed under",
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line in skip_exact:
            continue
        if any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        if line in {"- navigation", "- solvers", "- system", "- incompressible", "- compressible"}:
            continue
        line = line.replace("ð", "").replace("Â©", "©").replace("â", "").strip()
        cleaned_lines.append(line)

    compact: list[str] = []
    blank = False
    for line in cleaned_lines:
        if not line:
            if not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
    return "\n".join(compact).strip()


def _pick_manifest_synopsis(lines: list[str], title: str) -> str:
    for line in lines:
        if not line or line == title:
            continue
        if line.startswith("-"):
            continue
        if line.startswith("/*") or line.startswith("|") or line.startswith("\\"):
            continue
        if line in {"Overview", "Usage", "Further information", "Input requirements", "Boundary conditions"}:
            continue
        return line[:200]
    return ""


def _parse_manifest_html(filepath: Path) -> list[dict]:
    meta = json.loads(filepath.with_suffix(".json").read_text(encoding="utf-8"))
    raw_html = filepath.read_text(encoding="utf-8", errors="replace")
    if meta.get("anchor"):
        raw_html = _extract_html_anchor_fragment(raw_html, meta["anchor"])
    text = _html_to_text(raw_html)

    title = meta.get("title", "")
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        title = unescape(title_match.group(1)).strip() if title_match else meta["page_name"]

    text = _clean_manifest_text(text, title, meta.get("program", ""))

    lines = [line for line in text.splitlines() if line.strip()]
    synopsis = _pick_manifest_synopsis(lines, title)
    if meta.get("section") == "dictionary" and (
        not synopsis or synopsis in {"FoamFile"} or synopsis.startswith("/*") or synopsis.startswith("FoamFile")
    ):
        synopsis = f"{title} dictionary"

    return [
        {
            "program": meta.get("program", ""),
            "section": meta.get("section", ""),
            "page_name": meta["page_name"],
            "title": title,
            "category": meta.get("section", ""),
            "var_type": "",
            "default_val": "",
            "synopsis": synopsis,
            "content": text[:5000],
        }
    ]


# ============================================================================
#  Fetch: clone repo → extract docs → index
# ============================================================================


def toolref_fetch(
    tool: str,
    *,
    version: str | None = None,
    force: bool = False,
    cfg: Config | None = None,
) -> int:
    """Fetch documentation for a tool at a specific version.

    Args:
        tool: Tool name (e.g. 'qe', 'lammps', 'gromacs').
        version: Version string. If None, uses the latest tag.
        cfg: Optional Config.

    Returns:
        Number of pages indexed.
    """
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}。支持的工具：{', '.join(TOOL_REGISTRY)}")

    info = TOOL_REGISTRY[tool]
    source_type = info.get("source_type", "git")

    if version is None:
        version = info.get("default_version")

    if version and not _validate_version(version):
        raise ValueError(f"无效版本号：{version}")

    # check if already fetched
    if version:
        vdir = _version_dir(tool, version, cfg)
        if vdir.exists() and not force:
            if _has_local_docs(tool, version, cfg):
                ui(f"[toolref] {info['display_name']} {version} 文档已存在，跳过拉取")
                count = _index_tool(tool, version, cfg)
                _set_current(tool, version, cfg)
                ui(f"[toolref] {info['display_name']} {version}：已索引 {count} 个文档页面")
                return count

            ui(f"[toolref] 检测到 {info['display_name']} {version} 残缺目录，重新拉取")
        elif vdir.exists() and force:
            ui(f"[toolref] 强制重新拉取 {info['display_name']} {version}")

    if source_type == "git":
        # determine git tag
        tag = None
        if version:
            tag = f"{info['tag_prefix']}{version}"

        # clone to temp dir
        import tempfile

        with tempfile.TemporaryDirectory(prefix=f"toolref-{tool}-") as tmpdir:
            clone_cmd = ["git", "clone", "--depth", "1"]
            if tag:
                clone_cmd += ["--branch", tag]
            clone_cmd += [info["repo"], tmpdir]

            ui(f"[toolref] 正在拉取 {info['display_name']} {version or 'latest'} 文档...")
            try:
                subprocess.run(
                    clone_cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=120,
                )
            except subprocess.CalledProcessError as e:
                _log.error("git clone 失败：%s", e.stderr[:500])
                raise RuntimeError(f"拉取 {tool} 文档失败。请检查版本号和网络。") from e

            # detect version from tag if not specified
            if not version:
                try:
                    result = subprocess.run(
                        ["git", "-C", tmpdir, "describe", "--tags", "--abbrev=0"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    detected_tag = result.stdout.strip()
                    version = detected_tag.removeprefix(info["tag_prefix"])
                except subprocess.CalledProcessError:
                    version = "latest"

            vdir = _version_dir(tool, version, cfg)
            vdir.mkdir(parents=True, exist_ok=True)

            # extract docs based on format
            tmppath = Path(tmpdir)
            if info["format"] == "def":
                dest = vdir / "def"
                dest.mkdir(exist_ok=True)
                for f in tmppath.rglob(info["doc_glob"]):
                    (dest / f.name).write_bytes(f.read_bytes())
                    _log.debug("提取: %s", f.name)
            elif info["doc_path"]:
                src = tmppath / info["doc_path"]
                if src.exists():
                    dest = vdir / "src"
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(src, dest)
                else:
                    _log.warning("文档路径不存在: %s", src)
    elif source_type == "manifest":
        version = version or info["default_version"]
        vdir = _version_dir(tool, version, cfg)
        existing_pages = _manifest_page_count(vdir) if vdir.exists() else 0
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": "ScholarAIO/1.3 toolref-fetch"})
        manifest = _build_manifest(tool, version)
        prefetched_manifest_pages: dict[str, str] = {}
        if tool == "openfoam" and manifest == _build_openfoam_manifest(version):
            discovered_manifest, prefetched_manifest_pages = _discover_openfoam_manifest_bundle(version, session)
            if discovered_manifest:
                manifest = discovered_manifest
        elif tool == "bioinformatics" and manifest == _build_bioinformatics_manifest(version):
            discovered_manifest, prefetched_manifest_pages = _discover_bioinformatics_manifest(
                version,
                session,
                manifest,
                cache_vdir=vdir if vdir.exists() else None,
            )
            if discovered_manifest:
                manifest = discovered_manifest
        ui(f"[toolref] 正在拉取 {info['display_name']} {version} 官方文档页...")
        import tempfile

        failures: list[str] = []
        with tempfile.TemporaryDirectory(prefix=f"toolref-{tool}-") as tmpdir:
            staged_vdir = Path(tmpdir) / version
            dest = staged_vdir / "pages"
            dest.mkdir(parents=True, exist_ok=True)
            for idx, item in enumerate(manifest, start=1):
                urls = [item["url"], *item.get("fallback_urls", [])]
                primary_url = item["url"]
                base_url = primary_url.split("#", 1)[0]
                body_text: str | None = prefetched_manifest_pages.get(primary_url) or prefetched_manifest_pages.get(
                    base_url
                )
                successful_url = primary_url if body_text is not None else None
                last_error: Exception | None = None
                if body_text is None:
                    for url in urls:
                        try:
                            resp = session.get(url, timeout=_MANIFEST_REQUEST_TIMEOUT)
                            resp.raise_for_status()
                            body_text = resp.text
                            successful_url = url
                            break
                        except requests.RequestException as e:
                            last_error = e
                            _log.warning("拉取失败: %s (%s)", url, e)
                if body_text is None:
                    failures.append(item["page_name"])
                    continue
                slug = _slugify(item["page_name"])
                html_path = dest / f"{idx:03d}-{slug}.html"
                html_path.write_text(body_text, encoding="utf-8")
                stored_item = dict(item)
                if successful_url and urls[0] != successful_url:
                    stored_item["fetched_url"] = successful_url
                    if last_error is not None:
                        stored_item["primary_fetch_error"] = str(last_error)
                html_path.with_suffix(".json").write_text(
                    json.dumps(stored_item, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            restored_failures: list[str] = []
            if vdir.exists() and failures:
                for page_name in failures:
                    if _copy_manifest_page_from_cache(vdir, staged_vdir, page_name):
                        restored_failures.append(page_name)

            fetched_pages = _manifest_page_count(staged_vdir)
            if failures and fetched_pages == 0:
                raise RuntimeError(f"拉取 {tool} 文档页失败：{failures[0]}")

            meta = {
                "tool": tool,
                "display_name": info["display_name"],
                "version": version,
                "format": info["format"],
                "repo": info.get("repo", ""),
                "source_type": source_type,
                "force_refreshed": force,
                "fetched_pages": fetched_pages,
                "expected_pages": len(manifest),
                "failed_pages": len(manifest) - fetched_pages,
                "failed_page_names": [name for name in failures if name not in restored_failures],
            }
            if restored_failures:
                meta["last_fetch_failed_page_names"] = failures
                meta["restored_from_cache_page_names"] = restored_failures
            _write_manifest_snapshot(staged_vdir, manifest)
            (staged_vdir / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            if vdir.exists() and fetched_pages < existing_pages:
                ui(
                    f"[toolref] 警告：新抓取仅得到 {fetched_pages}/{len(manifest)} 页，"
                    f"低于现有缓存 {existing_pages} 页；保留现有缓存"
                )
                current_missing = _manifest_missing_page_names(vdir, manifest)
                preserved_meta = {
                    "tool": tool,
                    "display_name": info["display_name"],
                    "version": version,
                    "format": info["format"],
                    "repo": info.get("repo", ""),
                    "source_type": source_type,
                    "force_refreshed": force,
                    "fetched_pages": existing_pages,
                    "expected_pages": len(manifest),
                    "failed_pages": len(current_missing),
                    "failed_page_names": current_missing,
                    "last_fetch_failed_page_names": failures,
                }
                (vdir / "meta.json").write_text(
                    json.dumps(preserved_meta, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            else:
                if vdir.exists():
                    shutil.rmtree(vdir)
                vdir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_vdir), str(vdir))

        if failures and _manifest_page_count(vdir) > 0:
            preview = "、".join(failures[:3])
            suffix = " 等" if len(failures) > 3 else ""
            ui(f"[toolref] 警告：{len(failures)} 个页面拉取失败（{preview}{suffix}），已保留更完整的可用缓存")
    else:
        raise ValueError(f"{tool} 不支持的 source_type: {source_type}")

    # write meta.json
    meta = {
        "tool": tool,
        "display_name": info["display_name"],
        "version": version,
        "format": info["format"],
        "repo": info.get("repo", ""),
        "source_type": source_type,
        "force_refreshed": force,
    }
    if source_type == "manifest":
        meta_path = vdir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            fetched_pages = _manifest_page_count(vdir)
            expected_pages = _expected_manifest_pages(tool, version, cfg)
            meta["fetched_pages"] = fetched_pages
            meta["expected_pages"] = expected_pages
            meta["failed_pages"] = expected_pages - fetched_pages
    (vdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # create/update current symlink
    _set_current(tool, version, cfg)

    # index
    count = _index_tool(tool, version, cfg)
    ui(f"[toolref] {info['display_name']} {version}：已索引 {count} 个文档页面")
    return count


# ============================================================================
#  Indexing
# ============================================================================


def _index_tool(tool: str, version: str, cfg: Config | None = None) -> int:
    """Parse and index all doc pages for a tool version."""
    vdir = _version_dir(tool, version, cfg)
    db = _db_path(tool, cfg)
    conn = _ensure_db(db)

    # clear old entries for this version
    conn.execute(
        "DELETE FROM toolref_pages WHERE tool = ? AND version = ?",
        (tool, version),
    )

    records: list[dict] = []
    info = TOOL_REGISTRY[tool]

    if info["format"] == "def":
        def_dir = vdir / "def"
        if def_dir.exists():
            for f in sorted(def_dir.glob("INPUT_*.def")):
                try:
                    parsed = _parse_qe_def(f)
                    records.extend(parsed)
                    _log.debug("解析 %s: %d 条记录", f.name, len(parsed))
                except Exception as e:
                    _log.warning("解析 %s 失败: %s", f.name, e)

    elif info["format"] == "rst" and tool == "lammps":
        src_dir = vdir / "src"
        if src_dir.exists():
            for f in sorted(src_dir.glob("*.rst")):
                try:
                    parsed = _parse_lammps_rst(f)
                    records.extend(parsed)
                except Exception as e:
                    _log.debug("跳过 %s: %s", f.name, e)

    elif info["format"] == "rst" and tool == "gromacs":
        src_dir = vdir / "src"
        if src_dir.exists():
            for f in sorted(src_dir.rglob("*.rst")):
                try:
                    parsed = _parse_gromacs_rst(f)
                    records.extend(parsed)
                except Exception as e:
                    _log.debug("跳过 %s: %s", f.name, e)
    elif info["format"] == "html":
        pages_dir = vdir / "pages"
        if pages_dir.exists():
            for f in sorted(pages_dir.glob("*.html")):
                try:
                    parsed = _parse_manifest_html(f)
                    records.extend(parsed)
                except Exception as e:
                    _log.warning("解析 %s 失败: %s", f.name, e)

    # insert records
    for r in records:
        conn.execute(
            """INSERT OR REPLACE INTO toolref_pages
               (tool, version, program, section, page_name, title,
                category, var_type, default_val, synopsis, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tool,
                version,
                r.get("program", ""),
                r.get("section", ""),
                r["page_name"],
                r.get("title", ""),
                r.get("category", ""),
                r.get("var_type", ""),
                r.get("default_val", ""),
                r.get("synopsis", ""),
                r["content"],
            ),
        )

    conn.commit()
    conn.close()
    return len(records)


# ============================================================================
#  Version management
# ============================================================================


def _set_current(tool: str, version: str, cfg: Config | None = None) -> None:
    link = _current_link(tool, cfg)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(version)


def toolref_use(tool: str, version: str, *, cfg: Config | None = None) -> None:
    """Set the active version for a tool.

    Args:
        tool: Tool name.
        version: Version to activate.
        cfg: Optional Config.
    """
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}")
    if not _validate_version(version):
        raise ValueError(f"非法版本号：{version}")
    vdir = _version_dir(tool, version, cfg)
    if not vdir.exists():
        raise FileNotFoundError(
            f"{tool} 版本 {version} 未找到。请先运行 `scholaraio toolref fetch {tool} --version {version}`"
        )
    _set_current(tool, version, cfg)
    ui(f"[toolref] {tool} 当前版本已切换为 {version}")


def toolref_list(tool: str | None = None, *, cfg: Config | None = None) -> list[dict]:
    """List available tools and their versions.

    Args:
        tool: If specified, list versions for this tool only.
        cfg: Optional Config.

    Returns:
        List of dicts with tool, version, is_current, page_count fields.
    """
    root = _toolref_root(cfg)
    results: list[dict] = []

    tools = [tool] if tool else list(TOOL_REGISTRY.keys())
    for t in tools:
        tdir = root / t
        if not tdir.exists():
            continue

        # find current symlink target
        link = tdir / "current"
        current_version = None
        if link.is_symlink():
            current_version = link.resolve().name

        for vdir in sorted(tdir.iterdir()):
            if vdir.name == "current" or not vdir.is_dir():
                if vdir.name == "toolref.db":
                    continue
                continue
            # count pages
            db = tdir / "toolref.db"
            page_count = 0
            meta: dict = {}
            if db.exists():
                try:
                    conn = sqlite3.connect(db)
                    row = conn.execute(
                        "SELECT COUNT(*) FROM toolref_pages WHERE tool=? AND version=?",
                        (t, vdir.name),
                    ).fetchone()
                    page_count = row[0] if row else 0
                    conn.close()
                except Exception:
                    pass
            meta_path = vdir / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}

            results.append(
                {
                    "tool": t,
                    "display_name": TOOL_REGISTRY.get(t, {}).get("display_name", t),
                    "version": vdir.name,
                    "is_current": vdir.name == current_version,
                    "page_count": page_count,
                    "source_type": meta.get("source_type", TOOL_REGISTRY.get(t, {}).get("source_type", "git")),
                    "expected_pages": meta.get("expected_pages"),
                    "failed_pages": meta.get("failed_pages"),
                }
            )

    return results


# ============================================================================
#  Show: precise lookup
# ============================================================================


def toolref_show(
    tool: str,
    *args: str,
    cfg: Config | None = None,
) -> list[dict]:
    """Look up a specific command or parameter.

    Args:
        tool: Tool name.
        *args: Lookup path segments. E.g. ("pw", "ecutwfc") for QE,
               or ("fix_npt",) for LAMMPS.
        cfg: Optional Config.

    Returns:
        List of matching records.
    """
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}")

    db = _db_path(tool, cfg)
    if not db.exists():
        raise FileNotFoundError(f"{tool} 文档未索引。请先运行 `scholaraio toolref fetch {tool}`")

    # resolve current version
    link = _current_link(tool, cfg)
    version = None
    if link.is_symlink():
        version = link.resolve().name

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    query_parts = [a.lower() for a in args]
    query_str = "/".join(query_parts)
    alias_phrase = _normalize_alias_phrase(*query_parts)

    # try exact page_name match first
    rows = conn.execute(
        """SELECT * FROM toolref_pages
           WHERE tool = ? AND (version = ? OR ? IS NULL)
           AND (LOWER(page_name) = ? OR LOWER(page_name) = ?)""",
        (tool, version, version, query_str, f"{tool}/{query_str}"),
    ).fetchall()

    if not rows:
        if tool == "qe" and len(query_parts) >= 2:
            program = _normalize_program_filter(tool, query_parts[0])
            title_query = query_parts[-1]
            rows = conn.execute(
                """SELECT * FROM toolref_pages
                   WHERE tool = ? AND (version = ? OR ? IS NULL)
                   AND LOWER(program) = ? AND LOWER(title) = ?
                   ORDER BY LENGTH(page_name)
                   LIMIT 20""",
                (tool, version, version, program, title_query),
            ).fetchall()

    if not rows and alias_phrase:
        exact_alias_key = f"%|{alias_phrase}|%"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(content) LIKE ?
               ORDER BY LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, exact_alias_key),
        ).fetchall()

    if not rows:
        # try exact suffix match (useful for "simpleFoam" -> "openfoam/simpleFoam")
        suffix_pattern = f"%/{query_str}"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(page_name) LIKE ?
               LIMIT 20""",
            (tool, version, version, suffix_pattern),
        ).fetchall()

    if not rows:
        # try partial match (page_name contains query)
        like_pattern = f"%{'%'.join(query_parts)}%"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(page_name) LIKE ?
               LIMIT 20""",
            (tool, version, version, like_pattern),
        ).fetchall()

    if not rows:
        # try title match
        title_query = query_parts[-1] if query_parts else ""
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(title) = ?
               LIMIT 20""",
            (tool, version, version, title_query),
        ).fetchall()

    if not rows and len(query_parts) == 1:
        # try exact program match, preferring manual or top-level pages
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(program) = ?
               ORDER BY
                 CASE
                   WHEN LOWER(page_name) LIKE '%/manual' THEN 0
                   WHEN LOWER(page_name) LIKE '%/command-reference' THEN 1
                   ELSE 2
                 END,
                 LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, query_parts[0]),
        ).fetchall()

    if not rows and alias_phrase:
        like_alias = f"%{alias_phrase}%"
        exact_alias_key = f"%|{alias_phrase}|%"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND (LOWER(synopsis) LIKE ? OR LOWER(content) LIKE ?)
               ORDER BY
                 CASE
                   WHEN LOWER(content) LIKE ? THEN 0
                   WHEN LOWER(synopsis) LIKE ? THEN 1
                   ELSE 2
                 END,
                 LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, like_alias, like_alias, exact_alias_key, like_alias),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
#  Search: FTS5 full-text
# ============================================================================


def toolref_search(
    tool: str,
    query: str,
    *,
    top_k: int = 20,
    program: str | None = None,
    section: str | None = None,
    cfg: Config | None = None,
) -> list[dict]:
    """Full-text search over tool documentation.

    Args:
        tool: Tool name.
        query: Search query string.
        top_k: Maximum results to return.
        program: Filter by program (e.g. 'pw.x').
        section: Filter by section/namelist (e.g. 'SYSTEM').
        cfg: Optional Config.

    Returns:
        List of matching records sorted by relevance.
    """
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}")

    db = _db_path(tool, cfg)
    if not db.exists():
        raise FileNotFoundError(f"{tool} 文档未索引。请先运行 `scholaraio toolref fetch {tool}`")

    link = _current_link(tool, cfg)
    version = None
    if link.is_symlink():
        version = link.resolve().name

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    normalized_query = _normalize_search_query(query)
    expanded_query = _expand_search_query(tool, query)
    alias_phrase = _normalize_alias_phrase(normalized_query)

    # build FTS5 query — auto-convert spaces to OR for better recall
    fts_query = expanded_query
    if " " in expanded_query and not any(kw in expanded_query.upper() for kw in ("OR", "AND", "NOT", '"')):
        words = expanded_query.split()
        fts_query = " OR ".join(words)

    def _build_search_sql(match_query: str) -> tuple[str, list]:
        sql = """
            SELECT p.*, rank
            FROM toolref_fts f
            JOIN toolref_pages p ON f.rowid = p.id
            WHERE toolref_fts MATCH ?
              AND p.tool = ?
        """
        params: list = [match_query, tool]

        if version:
            sql += " AND p.version = ?"
            params.append(version)
        if program:
            prog = _normalize_program_filter(tool, program)
            sql += " AND LOWER(p.program) = ?"
            params.append(prog)
        if section:
            sql += " AND LOWER(p.section) = ?"
            params.append(section.lower())

        sql += """
            ORDER BY
              CASE
                WHEN LOWER(p.title) = ? THEN 0
                WHEN LOWER(p.content) LIKE ? THEN 1
                WHEN LOWER(p.page_name) = ? OR LOWER(p.page_name) LIKE ? THEN 2
                WHEN LOWER(p.synopsis) LIKE ? THEN 3
                ELSE 4
              END,
              rank
            LIMIT ?
        """
        params.extend(
            [
                normalized_query.lower(),
                f"%|{alias_phrase}|%",
                normalized_query.lower(),
                f"%/{normalized_query.lower().replace(' ', '_')}",
                f"%{alias_phrase}%",
                top_k,
            ]
        )
        return sql, params

    try:
        sql, params = _build_search_sql(fts_query)
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        # FTS query syntax error — try quoting
        safe_query = '"' + normalized_query.replace('"', "") + '"'
        try:
            sql, params = _build_search_sql(safe_query)
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            rows = []

    conn.close()
    scored_rows = [
        (_score_search_result(tool, normalized_query.lower(), expanded_query.lower(), row), row) for row in rows
    ]
    scored_rows.sort(key=lambda item: (-item[0][0], item[0][1]))
    return [dict(row) for _, row in scored_rows[:top_k]]
