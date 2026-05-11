"""Per-inbox ingest pipeline orchestration."""

from __future__ import annotations

import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from scholaraio.core.config import Config
from scholaraio.core.log import ui as _base_ui
from scholaraio.services.ingest import assets, batch_assets, proceedings
from scholaraio.services.ingest.types import InboxCtx, StepDef, StepResult
from scholaraio.services.metrics import timer

_log = logging.getLogger(__name__)
_OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pptx")


def _pipeline_module():
    from scholaraio.services.ingest import pipeline as pipeline_mod

    return pipeline_mod


def _pipeline_attr(name: str, fallback):
    return getattr(_pipeline_module(), name, fallback)


def _steps() -> dict[str, StepDef]:
    return _pipeline_attr("STEPS", {})


def _logger() -> logging.Logger:
    return _pipeline_attr("_log", _log)


def _ui(message: str = "") -> None:
    legacy_ui = _pipeline_attr("ui", _base_ui)
    legacy_ui(message)


def process_inbox(
    inbox_dir: Path,
    papers_dir: Path,
    pending_dir: Path,
    existing_dois: dict[str, Path],
    inbox_steps: list[str],
    cfg: Config,
    opts: dict[str, Any],
    dry_run: bool,
    ingested_jsons: list[Path],
    *,
    is_thesis: bool = False,
    is_patent: bool = False,
    is_proceedings: bool = False,
    existing_pub_nums: dict[str, Path] | None = None,
    existing_arxiv_ids: dict[str, Path] | None = None,
) -> None:
    """处理单个 inbox 目录中的所有文件。

    Args:
        inbox_dir: inbox 目录路径。
        papers_dir: 已入库论文目录。
        pending_dir: 待审目录。
        existing_dois: 已入库 DOI 映射（会被原地更新）。
        inbox_steps: inbox 作用域步骤名列表。
        cfg: 全局配置。
        opts: 运行选项。
        dry_run: 是否预览模式。
        ingested_jsons: 新入库的 JSON 路径列表（会被原地追加）。
        is_thesis: 是否为 thesis inbox（跳过 DOI 去重，标记 paper_type）。
        is_patent: 是否为 patent inbox（跳过 DOI 去重，用公开号去重）。
        is_proceedings: 是否为 proceedings inbox。
        existing_pub_nums: 已入库专利公开号映射（用于去重）。
        existing_arxiv_ids: 已入库 arXiv ID 映射（用于预印本去重）。
    """
    if not inbox_dir.exists():
        return

    label_prefix = "[thesis] " if is_thesis else ("[proceedings] " if is_proceedings else "")

    entries: dict[str, dict[str, Path | None]] = {}
    for pdf in sorted(inbox_dir.glob("*.pdf")):
        entries.setdefault(pdf.stem, {"pdf": None, "md": None, "office": None})["pdf"] = pdf
    for md in sorted(inbox_dir.glob("*.md")):
        entries.setdefault(md.stem, {"pdf": None, "md": None, "office": None})["md"] = md
    # Scan Office files only when office_convert step is in the pipeline
    has_office_step = "office_convert" in inbox_steps
    if has_office_step:
        office_extensions = _pipeline_attr("_OFFICE_EXTENSIONS", _OFFICE_EXTENSIONS)
        for ext in office_extensions:
            for office_file in sorted(inbox_dir.glob(f"*{ext}")):
                entries.setdefault(office_file.stem, {"pdf": None, "md": None, "office": None})["office"] = office_file

    if not entries:
        if not is_thesis:
            msg = "No PDF, .md, or Office file" if has_office_step else "No PDF or .md file"
            _ui(f"{msg} in inbox: {inbox_dir}")
        return

    has_pdfs = any(e["pdf"] for e in entries.values())
    office_count = sum(1 for e in entries.values() if e.get("office") and not e["pdf"] and not e["md"])
    md_only_count = sum(1 for e in entries.values() if not e["pdf"] and e["md"])

    needs_mineru = has_pdfs and "mineru" in inbox_steps
    use_cloud_batch = False
    if needs_mineru and not dry_run:
        from scholaraio.providers.mineru import check_server
        from scholaraio.providers.pdf_fallback import prefers_fallback_parser

        preferred_parser = getattr(cfg.ingest, "pdf_preferred_parser", "mineru")
        if prefers_fallback_parser(preferred_parser):
            _logger().debug("preferred parser %s bypasses MinerU cloud batch preflight", preferred_parser)
        elif not check_server(cfg.ingest.mineru_endpoint):
            if cfg.resolved_mineru_api_key():
                _logger().debug("local MinerU unreachable, will use MinerU cloud CLI")
                use_cloud_batch = True
            else:
                _logger().error("MinerU unreachable (local: %s, no MinerU token)", cfg.ingest.mineru_endpoint)
                sys.exit(1)

    extra_info = []
    if md_only_count:
        extra_info.append(f"{md_only_count} md-only")
    if office_count:
        extra_info.append(f"{office_count} Office")
    _ui(f"{label_prefix}Found {len(entries)} items" + (f" ({', '.join(extra_info)})" if extra_info else ""))
    if not is_thesis:
        _ui(f"papers library has {len(existing_dois)} papers (by DOI)")

    # ---- Batch MinerU preflight (cloud only) ----
    mineru_time = 0.0
    long_pdf_stems: set[str] = set()  # stems of long PDFs excluded from batch
    batch_retry_stems: set[str] = set()
    batch_completed_stems: set[str] = set()
    if use_cloud_batch and needs_mineru and not dry_run:
        from scholaraio.providers.mineru import _plan_cloud_chunking

        normalize_batch_assets = any(step_name != "mineru" for step_name in inbox_steps)
        default_chunk_size = getattr(cfg.ingest, "chunk_page_limit", 100)
        pdfs_to_convert = []
        for e in entries.values():
            pdf = e["pdf"]
            if not pdf or (inbox_dir / (pdf.stem + ".md")).exists():
                continue
            should_chunk, _chunk_size, reason = _plan_cloud_chunking(
                pdf,
                default_chunk_size=default_chunk_size,
            )
            if should_chunk:
                long_pdf_stems.add(pdf.stem)
                _logger().info("cloud-split PDF excluded from batch (%s): %s", reason, pdf.name)
                continue
            pdfs_to_convert.append(pdf)
        if pdfs_to_convert:
            from scholaraio.providers.mineru import ConvertOptions, convert_pdfs_cloud_batch, is_pdf_validation_error

            mineru_opts = ConvertOptions(
                output_dir=inbox_dir,
                backend=cfg.ingest.mineru_backend_local,
                cloud_model_version=cfg.ingest.mineru_model_version_cloud,
                lang=cfg.ingest.mineru_lang,
                parse_method=cfg.ingest.mineru_parse_method,
                formula_enable=cfg.ingest.mineru_enable_formula,
                table_enable=cfg.ingest.mineru_enable_table,
                upload_workers=cfg.ingest.mineru_upload_workers,
                upload_retries=cfg.ingest.mineru_upload_retries,
                download_retries=cfg.ingest.mineru_download_retries,
                poll_timeout=cfg.ingest.mineru_poll_timeout,
            )
            t_batch_start = time.time()
            batch_results = convert_pdfs_cloud_batch(
                pdfs_to_convert,
                mineru_opts,
                api_key=cfg.resolved_mineru_api_key(),
                cloud_url=cfg.ingest.mineru_cloud_url,
                batch_size=cfg.ingest.mineru_batch_size,
            )
            mineru_time = time.time() - t_batch_start
            expected_batch_stems = {pdf.stem for pdf in pdfs_to_convert}
            # Move namespaced assets back to per-stem structure
            for br in batch_results:
                did = br.pdf_path.stem
                safe_stem = _pipeline_attr(
                    "_safe_pdf_artifact_stem_from_stem",
                    assets.safe_pdf_artifact_stem_from_stem,
                )
                asset_stem = safe_stem(did)
                target = inbox_dir / f"{asset_stem}_mineru_images"
                if normalize_batch_assets:
                    # Normalize cloud assets into the legacy inbox layout so later
                    # extract/dedup/ingest steps can reuse the existing asset mover.
                    asset_candidates = _pipeline_attr("_asset_stem_candidates", assets.asset_stem_candidates)
                    path_is_dir = _pipeline_attr("_path_is_dir", assets.path_is_dir)
                    for candidate_stem in asset_candidates(did, ""):
                        namespaced_images = inbox_dir / f"{candidate_stem}_images"
                        if path_is_dir(namespaced_images):
                            if target.exists():
                                shutil.rmtree(target)
                            namespaced_images.rename(target)
                            break
                    nested_images = br.md_path.parent / "images" if br.md_path else None
                    if nested_images and path_is_dir(nested_images) and nested_images != target:
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.move(str(nested_images), str(target))
                if not br.success:
                    batch_retry_stems.add(did)
                    _logger().error("MinerU batch failed for %s: %s", br.pdf_path.name, br.error)
                    if is_pdf_validation_error(br):
                        _ui(f"  {br.pdf_path.name}: PDF validation failed; fallback parsing will not run")
                    else:
                        _ui(f"  {br.pdf_path.name}: MinerU batch preprocessing failed; retrying via the per-file flow")
                    continue
                entry = entries.get(did)
                if entry is not None and entry["md"] is None and br.md_path and br.md_path.exists():
                    flatten_batch_output = _pipeline_attr(
                        "_flatten_cloud_batch_output",
                        batch_assets.flatten_cloud_batch_output,
                    )
                    entry["md"] = (
                        br.md_path if normalize_batch_assets else flatten_batch_output(inbox_dir, did, br.md_path)
                    )
                    batch_completed_stems.add(did)
                else:
                    batch_retry_stems.add(did)
                    _ui(
                        f"  {br.pdf_path.name}: MinerU batch preprocessing did not produce valid Markdown; "
                        "retrying via the per-file flow"
                    )

            missing_batch_stems = expected_batch_stems - batch_completed_stems - batch_retry_stems
            if missing_batch_stems:
                batch_retry_stems.update(missing_batch_stems)
                for stem in sorted(missing_batch_stems):
                    _logger().error("MinerU batch missing result for %s.pdf", stem)
                    _ui(f"  {stem}.pdf: MinerU batch preprocessing result is missing; retrying via the per-file flow")

    # ---- Per-file pipeline (remaining steps, or all steps if local MinerU) ----
    per_file_steps = inbox_steps
    batch_skip_mineru = use_cloud_batch and "mineru" in per_file_steps

    has_api = "dedup" in per_file_steps and not dry_run and not opts.get("no_api") and not is_thesis
    api_delay = 2.0 if has_api else 0

    stats: dict[str, int] = {"ingested": 0, "duplicate": 0, "needs_review": 0, "failed": 0, "skipped": 0}
    step_times: dict[str, float] = {}
    if mineru_time:
        step_times["mineru"] = mineru_time
    sorted_entries = sorted(entries.items())
    for idx, (stem, paths) in enumerate(sorted_entries):
        office_path = paths.get("office")
        if paths["pdf"]:
            file_label = paths["pdf"].name
            file_type = "PDF"
        elif paths["md"]:
            # Prefer .md over Office when both exist (Office file will still be cleaned up)
            file_label = paths["md"].name
            file_type = "MD"
        elif office_path:
            file_label = office_path.name
            file_type = office_path.suffix.lstrip(".").upper()
        else:
            file_label = paths["md"].name
            file_type = "MD"
        _ui(f"\n{label_prefix}[{idx + 1}/{len(sorted_entries)}] {file_type}: {file_label}")

        file_steps = per_file_steps
        if batch_skip_mineru:
            needs_single_file_mineru = stem in long_pdf_stems or stem in batch_retry_stems
            if not needs_single_file_mineru and paths["md"] is not None:
                file_steps = [s for s in per_file_steps if s != "mineru"]

        # Inject office_path for office-only entries (no PDF) so downstream steps can clean up the source file
        file_opts = dict(opts)
        if office_path and not paths["pdf"]:
            file_opts["office_path"] = office_path

        ctx = InboxCtx(
            pdf_path=paths["pdf"],
            inbox_dir=inbox_dir,
            papers_dir=papers_dir,
            existing_dois=existing_dois,
            cfg=cfg,
            opts=file_opts,
            pending_dir=pending_dir,
            md_path=paths["md"],
            is_thesis=is_thesis,
            is_patent=is_patent,
            existing_pub_nums=existing_pub_nums,
            existing_arxiv_ids=existing_arxiv_ids,
        )
        ingest_proceedings_ctx = _pipeline_attr("_ingest_proceedings_ctx", proceedings.ingest_proceedings_ctx)
        if is_proceedings and ctx.md_path and ingest_proceedings_ctx(ctx, force=True):
            final_status = ctx.status if ctx.status != "pending" else "skipped"
            stats[final_status] += 1
            continue
        for step_name in file_steps:
            try:
                timer_func = _pipeline_attr("timer", timer)
                with timer_func(f"pipeline.inbox.{step_name}", "step") as t:
                    result = _steps()[step_name].fn(ctx)
                step_times[step_name] = step_times.get(step_name, 0) + t.elapsed
                _logger().debug("%s: %.1fs", step_name, t.elapsed)
            except Exception as exc:
                _logger().exception("step %s failed for %s: %s", step_name, file_label, exc)
                ctx.status = "failed"
                result = StepResult.FAIL
                break
            if is_proceedings and step_name == "mineru" and result == StepResult.OK and ctx.md_path:
                if ingest_proceedings_ctx(ctx, force=True):
                    result = StepResult.FAIL
                    break
            if result != StepResult.OK:
                break

        final_status = ctx.status if ctx.status != "pending" else "skipped"
        stats[final_status] += 1
        if final_status == "ingested" and ctx.ingested_json:
            ingested_jsons.append(ctx.ingested_json)

        if api_delay and idx < len(sorted_entries) - 1:
            time.sleep(api_delay)

    # Clean up stray MinerU artifacts left in inbox
    for pattern in ["*_layout.json", "*_content_list.json", "*_origin.pdf", "layout.json"]:
        for stray in list(inbox_dir.glob(pattern)):
            stray.unlink(missing_ok=True)
            _logger().debug("stray cleanup: %s", stray.name)
    for stray_dir in list(inbox_dir.glob("*_mineru_images")):
        if stray_dir.is_dir():
            shutil.rmtree(stray_dir)
            _logger().debug("stray cleanup dir: %s", stray_dir.name)
    for stray_dir in list(inbox_dir.glob("[0-9][0-9][0-9][0-9]_*")):
        if stray_dir.is_dir() and not any(stray_dir.iterdir()):
            stray_dir.rmdir()
            _logger().debug("stray cleanup empty batch dir: %s", stray_dir.name)

    _ui(
        f"\n{label_prefix}inbox done: {stats['ingested']} ingested | {stats['duplicate']} duplicate | {stats['needs_review']} review | {stats['failed']} failed | {stats['skipped']} skipped"
    )
    if step_times:
        _ui("Step timing:")
        for sn, st in step_times.items():
            _ui(f"  {sn:12s} {st:6.1f}s")
        _ui(f"  {'total':12s} {sum(step_times.values()):6.1f}s")
