"""Asset normalization helpers for batch PDF conversion."""

from __future__ import annotations

import shutil
from pathlib import Path

from scholaraio.services.ingest.assets import asset_stem_candidates, path_is_dir


def move_batch_images(paper_md: Path, pdir: Path, stem: str, md_src: Path | None, tmp_dir: Path) -> None:
    """Move images produced by cloud batch conversion into ``pdir/images``."""
    image_sources: list[Path] = []

    for candidate_stem in asset_stem_candidates(stem, ""):
        legacy_images_src = tmp_dir / f"{candidate_stem}_images"
        if path_is_dir(legacy_images_src):
            image_sources.append(legacy_images_src)

    if md_src is not None:
        candidates = [md_src.parent / "images"]
        candidates.extend(
            md_src.parent / f"{candidate_stem}_images" for candidate_stem in asset_stem_candidates(stem, "")
        )
        for candidate in candidates:
            if path_is_dir(candidate) and candidate not in image_sources:
                image_sources.append(candidate)

    if not image_sources:
        return

    images_dst = pdir / "images"
    if images_dst.exists():
        shutil.rmtree(str(images_dst))
    images_dst.mkdir(parents=True, exist_ok=True)

    for images_src in image_sources:
        for child in images_src.iterdir():
            dst_child = images_dst / child.name
            if dst_child.exists():
                if dst_child.is_dir():
                    shutil.rmtree(str(dst_child))
                else:
                    dst_child.unlink()
            shutil.move(str(child), str(dst_child))
        images_src.rmdir()

    if paper_md.exists():
        md_text = paper_md.read_text(encoding="utf-8")
        fixed = md_text
        for candidate_stem in asset_stem_candidates(stem, ""):
            fixed = fixed.replace(f"{candidate_stem}_images/", "images/")
        if fixed != md_text:
            paper_md.write_text(fixed, encoding="utf-8")


def flatten_cloud_batch_output(inbox_dir: Path, stem: str, md_src: Path) -> Path:
    """Move isolated cloud batch output back into inbox root for mineru-only flows."""
    flat_md = inbox_dir / f"{stem}.md"
    if md_src != flat_md:
        if flat_md.exists():
            flat_md.unlink()
        shutil.move(str(md_src), str(flat_md))

    images_src = md_src.parent / "images"
    if images_src.is_dir():
        images_dst = inbox_dir / "images"
        images_dst.mkdir(parents=True, exist_ok=True)
        for child in images_src.iterdir():
            dst_child = images_dst / child.name
            if dst_child.exists():
                if dst_child.is_dir():
                    shutil.rmtree(str(dst_child))
                else:
                    dst_child.unlink()
            shutil.move(str(child), str(dst_child))
        images_src.rmdir()

    md_src_parent = md_src.parent
    if md_src_parent != inbox_dir and md_src_parent.is_dir() and not any(md_src_parent.iterdir()):
        md_src_parent.rmdir()
    return flat_md
