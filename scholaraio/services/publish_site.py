"""Generate a static site from audited ``published/`` paper archives."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PublishSiteResult:
    paper_count: int
    output_dir: Path
    index_path: Path


def slugify(text: str) -> str:
    """Create a stable URL path segment from folder or title text."""
    slug = "".join(ch.lower() if ch.isalnum() or ch == "-" else "-" for ch in text)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "paper"


def load_papers(published_dir: Path | str) -> list[dict]:
    """Load metadata from ``published/*/metadata.json`` in reverse folder order."""
    root = Path(published_dir)
    if not root.exists():
        return []

    papers: list[dict] = []
    for folder in sorted(root.iterdir(), key=lambda path: path.name, reverse=True):
        if not folder.is_dir():
            continue
        meta_path = folder / "metadata.json"
        if not meta_path.exists():
            continue
        with meta_path.open(encoding="utf-8") as handle:
            meta = json.load(handle) or {}
        if not isinstance(meta, dict):
            continue
        meta["_source_dir"] = folder.name
        meta["_slug"] = slugify(folder.name)
        papers.append(meta)
    return papers


def build_source_zips(papers: list[dict], published_dir: Path | str) -> None:
    """Create source ZIP archives beside each published paper's metadata."""
    root = Path(published_dir).resolve()
    for paper in papers:
        src_dir = (root / paper["_source_dir"]).resolve()
        zip_name = f"{paper['_slug']}-source.zip"
        zip_path = src_dir / zip_name

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for tex_file in _string_list(paper.get("tex_files")):
                tex_path = _safe_child(src_dir, tex_file)
                if tex_path and tex_path.is_file():
                    archive.write(tex_path, arcname=Path(tex_file).as_posix())

            for dir_key, default_name in (("images_dir", "images"), ("misc_dir", "misc")):
                rel_dir = str(paper.get(dir_key) or default_name)
                src_subdir = _safe_child(src_dir, rel_dir)
                if src_subdir and src_subdir.is_dir():
                    _write_tree(archive, src_subdir, Path(rel_dir).as_posix())

            metadata_path = src_dir / "metadata.json"
            if metadata_path.is_file():
                archive.write(metadata_path, arcname="metadata.json")

        paper["_source_zip_url"] = f"assets/papers/{paper['_slug']}/{zip_name}"


def link_or_copy_assets(papers: list[dict], published_dir: Path | str, out_dir: Path | str, copy_assets: bool) -> None:
    """Copy deployable assets or symlink published folders for local preview."""
    root = Path(published_dir).resolve()
    assets_root = Path(out_dir).resolve() / "assets" / "papers"
    assets_root.mkdir(parents=True, exist_ok=True)

    for paper in papers:
        src_dir = (root / paper["_source_dir"]).resolve()
        dest_dir = assets_root / paper["_slug"]
        _remove_path(dest_dir)

        if copy_assets:
            dest_dir.mkdir(parents=True, exist_ok=True)
            pdf_name = str(paper.get("pdf_filename") or "")
            src_pdf = _safe_child(src_dir, pdf_name) if pdf_name else None
            if src_pdf and src_pdf.is_file():
                shutil.copy2(src_pdf, dest_dir / src_pdf.name)
                paper["_pdf_url"] = f"assets/papers/{paper['_slug']}/{src_pdf.name}"
            else:
                paper["_pdf_url"] = ""

            zip_name = f"{paper['_slug']}-source.zip"
            src_zip = src_dir / zip_name
            if src_zip.is_file():
                shutil.copy2(src_zip, dest_dir / zip_name)
        else:
            rel = os.path.relpath(src_dir, assets_root)
            dest_dir.symlink_to(rel, target_is_directory=True)
            pdf_name = str(paper.get("pdf_filename") or "")
            src_pdf = _safe_child(src_dir, pdf_name) if pdf_name else None
            paper["_pdf_url"] = f"assets/papers/{paper['_slug']}/{pdf_name}" if src_pdf and src_pdf.exists() else ""


def generate_site(published_dir: Path | str, out_dir: Path | str, copy_assets: bool = True) -> PublishSiteResult:
    """Generate a GitHub Pages-ready static site from published archives."""
    published_root = Path(published_dir).expanduser().resolve()
    output_root = Path(out_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    papers = load_papers(published_root)
    assets_root = output_root / "assets" / "papers"
    if assets_root.exists():
        shutil.rmtree(assets_root)

    if papers:
        build_source_zips(papers, published_root)
        link_or_copy_assets(papers, published_root, output_root, copy_assets=copy_assets)

    _generate_html(papers, output_root)
    _generate_css(output_root)
    _generate_js(output_root)
    _generate_readme(output_root)
    return PublishSiteResult(paper_count=len(papers), output_dir=output_root, index_path=output_root / "index.html")


def _generate_html(papers: list[dict], out_dir: Path) -> None:
    subjects = sorted({_text(paper.get("subject"), "Uncategorized") for paper in papers})
    years = sorted({_text(paper.get("date"))[:4] for paper in papers if _text(paper.get("date"))}, reverse=True)
    cards = "\n".join(_paper_card(paper) for paper in papers)
    subject_options = "\n".join(
        f'<option value="{_esc_attr(subject)}">{_esc(subject)}</option>' for subject in subjects
    )
    year_options = "\n".join(f'<option value="{_esc_attr(year)}">{_esc(year)}</option>' for year in years)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Published Papers | ScholarAIO</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header class="site-header">
    <div class="shell header-grid">
      <div>
        <p class="eyebrow">ScholarAIO Archive</p>
        <h1>Published Papers</h1>
      </div>
      <p class="paper-count" id="paper-count">{len(papers)} papers</p>
    </div>
  </header>
  <main class="shell">
    <section class="controls" aria-label="Filters">
      <input id="search-input" type="search" placeholder="Search title, author, keyword" aria-label="Search papers">
      <select id="filter-year" aria-label="Filter by year">
        <option value="">All years</option>
        {year_options}
      </select>
      <select id="filter-subject" aria-label="Filter by subject">
        <option value="">All subjects</option>
        {subject_options}
      </select>
    </section>
    <section class="papers-list" id="papers-list" aria-live="polite">
      {cards}
    </section>
  </main>
  <footer class="site-footer">
    <div class="shell">Generated by ScholarAIO on {_esc(datetime.now().strftime("%Y-%m-%d"))}</div>
  </footer>
  <script src="js/main.js"></script>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")


def _paper_card(paper: dict) -> str:
    title = _text(paper.get("title"), "Untitled")
    date = _text(paper.get("date"))
    subject = _text(paper.get("subject"), "Uncategorized")
    keywords = _string_list(paper.get("keywords"))
    authors = _string_list(paper.get("authors"))
    note = _text(paper.get("note"))
    slug = _text(paper.get("_slug"), "paper")
    source_dir = _text(paper.get("_source_dir"))
    pdf_url = _text(paper.get("_pdf_url"))
    zip_url = _text(paper.get("_source_zip_url"))

    tags = "".join(f'<span class="tag">{_esc(keyword)}</span>' for keyword in keywords[:8])
    pdf_action = (
        f'<a class="action primary" href="{_esc_attr(pdf_url)}" target="_blank" rel="noopener">PDF</a>'
        if pdf_url
        else ""
    )
    zip_action = f'<a class="action" href="{_esc_attr(zip_url)}" download>Source ZIP</a>' if zip_url else ""
    year = date[:4] if date else ""
    searchable = " ".join([title, subject, " ".join(keywords), " ".join(authors), note]).lower()

    return f"""<article class="paper-card" data-year="{_esc_attr(year)}" data-subject="{_esc_attr(subject)}" data-search="{_esc_attr(searchable)}">
  <div class="paper-meta">
    <span>{_esc(date or "Undated")}</span>
    <span>{_esc(subject)}</span>
  </div>
  <h2>{_esc(title)}</h2>
  <p class="authors">{_esc(", ".join(authors))}</p>
  <div class="tags">{tags}</div>
  <p class="note">{_esc(note)}</p>
  <div class="actions">
    {pdf_action}
    {zip_action}
    <button class="action" type="button" data-details="{_esc_attr(slug)}">Details</button>
  </div>
  <div class="details" id="details-{_esc_attr(slug)}" hidden>
    <p><strong>Keywords:</strong> {_esc(", ".join(keywords))}</p>
    <p><strong>Source:</strong> {_esc(source_dir)}</p>
  </div>
</article>"""


def _generate_css(out_dir: Path) -> None:
    css = """:root {
  color-scheme: light dark;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --ink: #202124;
  --muted: #61666f;
  --line: #dfe3e8;
  --accent: #0f766e;
  --accent-strong: #115e59;
  --warm: #9a3412;
  --shadow: 0 8px 24px rgba(22, 27, 34, 0.08);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111418;
    --panel: #181c21;
    --ink: #f3f5f7;
    --muted: #a8b0ba;
    --line: #2a3038;
    --accent: #5eead4;
    --accent-strong: #99f6e4;
    --warm: #fdba74;
    --shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
  }
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, "Aptos", "Segoe UI", sans-serif;
  line-height: 1.55;
}
.shell { width: min(1040px, calc(100vw - 32px)); margin: 0 auto; }
.site-header {
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  position: sticky;
  top: 0;
  z-index: 1;
}
.header-grid {
  min-height: 120px;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 24px;
  align-items: center;
}
.eyebrow {
  color: var(--warm);
  font-size: 0.82rem;
  font-weight: 700;
  margin: 0 0 4px;
  text-transform: uppercase;
}
h1 { font-family: ui-serif, Georgia, serif; font-size: clamp(2rem, 5vw, 4rem); margin: 0; }
.paper-count { color: var(--muted); font-weight: 700; }
.controls {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(140px, 180px) minmax(160px, 220px);
  gap: 12px;
  margin: 24px 0;
}
input, select {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--panel);
  color: var(--ink);
  font: inherit;
}
input:focus, select:focus { outline: 2px solid color-mix(in srgb, var(--accent) 40%, transparent); }
.papers-list { display: grid; gap: 14px; padding-bottom: 40px; }
.paper-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 20px;
  box-shadow: var(--shadow);
}
.paper-meta { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: 0.88rem; }
.paper-card h2 { font-family: ui-serif, Georgia, serif; margin: 8px 0 4px; font-size: 1.35rem; line-height: 1.35; }
.authors, .note { color: var(--muted); margin: 6px 0; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
.tag { border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; font-size: 0.8rem; color: var(--accent-strong); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.action {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--ink);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 7px 12px;
  text-decoration: none;
  font: inherit;
  font-weight: 700;
}
.action.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.details {
  border-top: 1px dashed var(--line);
  color: var(--muted);
  margin-top: 14px;
  padding-top: 12px;
}
.details p { margin: 4px 0; }
.site-footer { border-top: 1px solid var(--line); color: var(--muted); padding: 18px 0 28px; }

@media (max-width: 720px) {
  .header-grid, .controls { grid-template-columns: 1fr; }
  .header-grid { min-height: 104px; }
}
"""
    css_path = out_dir / "css" / "style.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")


def _generate_js(out_dir: Path) -> None:
    js = """(() => {
  const search = document.getElementById("search-input");
  const year = document.getElementById("filter-year");
  const subject = document.getElementById("filter-subject");
  const count = document.getElementById("paper-count");
  const cards = Array.from(document.querySelectorAll(".paper-card"));

  function applyFilters() {
    const term = search.value.trim().toLowerCase();
    let visible = 0;
    for (const card of cards) {
      const okText = !term || card.dataset.search.includes(term);
      const okYear = !year.value || card.dataset.year === year.value;
      const okSubject = !subject.value || card.dataset.subject === subject.value;
      const show = okText && okYear && okSubject;
      card.hidden = !show;
      if (show) visible += 1;
    }
    count.textContent = visible + (visible === 1 ? " paper" : " papers");
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-details]");
    if (!button) return;
    const details = document.getElementById("details-" + button.dataset.details);
    if (!details) return;
    details.hidden = !details.hidden;
    button.textContent = details.hidden ? "Details" : "Hide Details";
  });

  search.addEventListener("input", applyFilters);
  year.addEventListener("change", applyFilters);
  subject.addEventListener("change", applyFilters);
  applyFilters();
})();
"""
    js_path = out_dir / "js" / "main.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text(js, encoding="utf-8")


def _generate_readme(out_dir: Path) -> None:
    readme = """# ScholarAIO Published Papers Site

This directory is generated by `scholaraio publish-site`.
Commit the generated files to a separate GitHub Pages repository when you are ready to publish.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def _write_tree(archive: zipfile.ZipFile, root: Path, archive_root: str) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        archive.write(path, arcname=f"{archive_root}/{relative.as_posix()}")


def _safe_child(root: Path, relative: str) -> Path | None:
    if not relative:
        return None
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return None
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _text(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def _esc_attr(value: str) -> str:
    return html.escape(value, quote=True)
