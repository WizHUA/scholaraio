"""Ingest pipeline step registry and presets."""

from __future__ import annotations

from scholaraio.services.ingest import inbox_steps, steps
from scholaraio.services.ingest.types import StepDef

STEPS: dict[str, StepDef] = {
    "office_convert": StepDef(
        fn=inbox_steps.step_office_convert,
        scope="inbox",
        desc="Office documents (DOCX/XLSX/PPTX) -> Markdown (MarkItDown)",
    ),
    "mineru": StepDef(fn=inbox_steps.step_mineru, scope="inbox", desc="PDF -> Markdown (MinerU)"),
    "extract": StepDef(fn=inbox_steps.step_extract, scope="inbox", desc="Markdown -> metadata extraction"),
    "extract_doc": StepDef(fn=inbox_steps.step_extract_doc, scope="inbox", desc="Document -> LLM metadata extraction"),
    "dedup": StepDef(fn=inbox_steps.step_dedup, scope="inbox", desc="API lookup + DOI deduplication"),
    "ingest": StepDef(fn=inbox_steps.step_ingest, scope="inbox", desc="Write to configured papers library"),
    "toc": StepDef(fn=steps.step_toc, scope="papers", desc="Extract TOC with LLM and write JSON"),
    "l3": StepDef(fn=steps.step_l3, scope="papers", desc="Extract conclusion with LLM and write JSON"),
    "translate": StepDef(
        fn=steps.step_translate, scope="papers", desc="Translate paper Markdown to the target language"
    ),
    "refetch": StepDef(
        fn=steps.step_refetch, scope="papers", desc="Re-query APIs to fill citation counts and related fields"
    ),
    "embed": StepDef(fn=steps.step_embed, scope="global", desc="Generate semantic vectors into index.db"),
    "index": StepDef(fn=steps.step_index, scope="global", desc="Update SQLite FTS5 index"),
}

# Document inbox uses a different step sequence (no DOI dedup).
# office_convert runs before mineru; for PDF entries it is a no-op (office_path not set).
DOC_INBOX_STEPS = ["office_convert", "mineru", "extract_doc", "ingest"]

# Office formats scanned in any inbox when office_convert is in the step list.
# Regular inbox presets don't include office_convert, so Office files there are ignored.
OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pptx")

PRESETS: dict[str, list[str]] = {
    "full": ["mineru", "extract", "dedup", "ingest", "toc", "l3", "embed", "index"],
    "ingest": ["mineru", "extract", "dedup", "ingest", "embed", "index"],
    "enrich": ["toc", "l3", "embed", "index"],
    "reindex": ["embed", "index"],
}
