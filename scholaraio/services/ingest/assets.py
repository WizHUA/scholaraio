"""MinerU transient asset discovery helpers for ingest orchestration."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)


def find_assets(inbox_dir: Path, asset_prefix: str, md_stem: str) -> tuple[Path | None, list[Path], list[Path]]:
    """Locate MinerU artifacts in inbox.

    Returns:
        (images_dir, json_files, origin_pdfs) — images_dir may be None.
    """
    images_dir = None
    for candidate_stem in asset_stem_candidates(asset_prefix, md_stem):
        for suffix in ("_mineru_images", "_images"):
            candidate = inbox_dir / f"{candidate_stem}{suffix}"
            if path_is_dir(candidate):
                images_dir = candidate
                break
        if images_dir is not None:
            break
    if images_dir is None and path_is_dir(inbox_dir / "images"):
        images_dir = inbox_dir / "images"

    json_files: list[Path] = []
    origin_pdfs: list[Path] = []
    for prefix in asset_stem_candidates(asset_prefix, md_stem):
        if not prefix:
            continue
        json_files.extend(safe_glob(inbox_dir, f"{prefix}_*.json"))
        origin_pdfs.extend(safe_glob(inbox_dir, f"{prefix}_*_origin.pdf"))
    return images_dir, json_files, origin_pdfs


def asset_stem_candidates(asset_prefix: str, md_stem: str) -> list[str]:
    """Return safe-first legacy stem candidates for MinerU transient assets."""
    candidates: list[str] = []

    def add(stem: str) -> None:
        if stem and stem not in candidates:
            candidates.append(stem)

    for stem in (asset_prefix, md_stem):
        if not stem:
            continue
        add(safe_pdf_artifact_stem_from_stem(stem))
        add(stem)
    return candidates


def safe_pdf_artifact_stem_from_stem(stem: str) -> str:
    from scholaraio.providers.mineru import _safe_pdf_artifact_stem

    return _safe_pdf_artifact_stem(Path(f"{stem}.pdf"))


def path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def safe_glob(parent: Path, pattern: str) -> list[Path]:
    try:
        return list(parent.glob(pattern))
    except OSError:
        return []


def strip_artifact_prefix(name: str, candidate_stems: list[str]) -> str:
    for stem in candidate_stems:
        marker = f"{stem}_"
        if stem and name.startswith(marker):
            return name.removeprefix(marker)
    return name


def move_assets(inbox_dir: Path, dest_dir: Path, asset_prefix: str, md_stem: str) -> None:
    """Move MinerU assets (images, layout.json, etc.) from inbox to dest."""
    images_dir, json_files, origin_pdfs = find_assets(inbox_dir, asset_prefix, md_stem)
    candidate_stems = asset_stem_candidates(asset_prefix, md_stem)
    if images_dir:
        shutil.move(str(images_dir), str(dest_dir / "images"))
        paper_md = dest_dir / "paper.md"
        if paper_md.exists():
            md_text = paper_md.read_text(encoding="utf-8")
            fixed = md_text
            for stem in candidate_stems:
                fixed = fixed.replace(f"{stem}_mineru_images/", "images/")
                fixed = fixed.replace(f"{stem}_images/", "images/")
            if fixed != md_text:
                paper_md.write_text(fixed, encoding="utf-8")
    for f in json_files:
        dest_name = strip_artifact_prefix(f.name, candidate_stems)
        shutil.move(str(f), str(dest_dir / dest_name))
    for f in origin_pdfs:
        dest_name = strip_artifact_prefix(f.name, candidate_stems)
        shutil.move(str(f), str(dest_dir / dest_name))


def cleanup_assets(inbox_dir: Path, pdf_stem: str, md_stem: str) -> None:
    """Remove MinerU artifacts left in inbox (layout.json, content_list, origin.pdf, images)."""
    images_dir, json_files, origin_pdfs = find_assets(inbox_dir, pdf_stem, md_stem)
    if images_dir:
        shutil.rmtree(images_dir)
        _log.debug("deleted asset dir: %s", images_dir.name)
    for f in json_files:
        f.unlink(missing_ok=True)
        _log.debug("deleted asset: %s", f.name)
    for f in origin_pdfs:
        f.unlink(missing_ok=True)
        _log.debug("deleted asset: %s", f.name)
