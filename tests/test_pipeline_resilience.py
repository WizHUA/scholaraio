"""Resilience tests for ingest pipeline fault tolerance."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio.core.config import Config
from scholaraio.services.ingest.pipeline import (
    STEPS,
    InboxCtx,
    StepResult,
    _process_inbox,
    step_dedup,
    step_extract,
)
from scholaraio.services.ingest_metadata._models import PaperMetadata


@pytest.fixture(autouse=True)
def silence_ui(monkeypatch):
    monkeypatch.setattr("scholaraio.services.ingest.pipeline.ui", lambda *a, **k: None)


def test_step_dedup_treats_stale_registry_as_new(tmp_path: Path):
    """When duplicate DOI points to a deleted directory, treat as new paper."""
    existing_json = tmp_path / "Deleted-Dir" / "meta.json"
    pdf = tmp_path / "new.pdf"
    pdf.write_bytes(b"%PDF")
    md = tmp_path / "new.md"
    md.write_text("markdown", encoding="utf-8")
    meta = PaperMetadata(
        title="Test",
        doi="10.1234/stale",
        first_author_lastname="Test",
        year=2024,
    )
    ctx = InboxCtx(
        pdf_path=pdf,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        pending_dir=tmp_path / "pending",
        existing_dois={"10.1234/stale": existing_json},
        existing_pub_nums={},
        cfg=Config(_root=tmp_path),
        opts={},
        md_path=md,
        meta=meta,
    )

    assert step_dedup(ctx) == StepResult.OK
    assert ctx.status == "pending"
    assert md.exists()


def test_process_inbox_isolates_step_exceptions(tmp_path: Path, monkeypatch):
    """When one file crashes in a step, the rest of the batch continues."""
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()

    md1 = inbox_dir / "crash.md"
    md1.write_text("# Crash\n", encoding="utf-8")
    md2 = inbox_dir / "ok.md"
    md2.write_text("# OK\n", encoding="utf-8")

    real_step_extract = step_extract
    call_count = [0]

    def crashing_step_extract(ctx):
        call_count[0] += 1
        if ctx.md_path and ctx.md_path.name == "crash.md":
            raise RuntimeError("simulated extract crash")
        return real_step_extract(ctx)

    monkeypatch.setattr(STEPS["extract"], "fn", crashing_step_extract, raising=False)
    monkeypatch.setattr(
        "scholaraio.services.ingest_metadata.enrich_metadata",
        lambda meta: meta,
    )
    monkeypatch.setattr(
        "scholaraio.services.ingest_metadata.extractor.get_extractor",
        lambda cfg: SimpleNamespace(
            extract=lambda md_path: PaperMetadata(
                doi=f"10.1234/{Path(md_path).stem}",
                title=f"Paper {Path(md_path).stem}",
                first_author_lastname="Smith",
                year=2024,
            )
        ),
    )

    ingested = []
    _process_inbox(
        inbox_dir,
        papers_dir,
        pending_dir,
        {},
        ["extract", "dedup", "ingest"],
        Config(_root=tmp_path),
        {},
        False,
        ingested,
    )
    assert len(ingested) == 1
    assert ingested[0].parent.name.startswith("Smith-2024-Paper-ok")
    assert md1.exists()
