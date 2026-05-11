"""Proceedings routing helpers for ingest."""

from __future__ import annotations

from scholaraio.core.log import ui
from scholaraio.services.ingest.cleanup import cleanup_inbox
from scholaraio.services.ingest.paths import proceedings_dir
from scholaraio.services.ingest.types import InboxCtx


def ingest_proceedings_ctx(ctx: InboxCtx, *, force: bool) -> bool:
    """Route a markdown entry into the proceedings library."""
    from scholaraio.services.ingest.proceedings_volume import ingest_proceedings_markdown

    if not ctx.md_path or not ctx.md_path.exists():
        return False

    dry_run = bool(ctx.opts.get("dry_run", False))
    proceedings_root = proceedings_dir(ctx.cfg)
    source_name = ctx.pdf_path.name if ctx.pdf_path else ctx.md_path.name
    if dry_run:
        ctx.status = "skipped"
        ui(f"Detected proceedings; dry-run skipped writing to {proceedings_root}.")
        ui("Dry-run mode will not generate proceeding.md or split_candidates.json.")
        ui("Rerun without --dry-run to generate proceedings split files for review.")
        return True

    ingest_proceedings_markdown(proceedings_root, ctx.md_path, source_name=source_name)
    cleanup_inbox(ctx.pdf_path, ctx.md_path, dry_run=dry_run)
    ctx.status = "ingested"
    ui("Detected proceedings; generated proceeding.md and split_candidates.json.")
    ui(
        "Waiting for an agent to review split_candidates.json and create split_plan.json before splitting and ingesting."
    )
    return True
