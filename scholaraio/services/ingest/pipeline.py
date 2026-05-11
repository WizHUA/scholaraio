"""
pipeline.py — 可组合步骤流水线
================================

步骤（scope）：
  inbox  — 每个 PDF 依次执行：mineru → extract → dedup → ingest
  papers — 每篇已入库论文执行：toc → l3
  global — 全局执行一次：index

预设：
  full    = mineru, extract, dedup, ingest, toc, l3, embed, index
  ingest  = mineru, extract, dedup, ingest, embed, index
  enrich  = toc, l3, embed, index
  reindex = embed, index

用法（CLI）：
  scholaraio pipeline full
  scholaraio pipeline enrich --force
  scholaraio pipeline --steps toc,l3
  scholaraio pipeline full --dry-run
"""

from __future__ import annotations

import logging

from scholaraio.core.log import ui as ui
from scholaraio.services.ingest import assets as ingest_assets
from scholaraio.services.ingest import batch_assets as ingest_batch_assets
from scholaraio.services.ingest import batch_convert as ingest_batch_convert
from scholaraio.services.ingest import batch_postprocess as ingest_batch_postprocess
from scholaraio.services.ingest import cleanup as ingest_cleanup
from scholaraio.services.ingest import detection as ingest_detection
from scholaraio.services.ingest import documents as ingest_documents
from scholaraio.services.ingest import external_import as ingest_external_import
from scholaraio.services.ingest import identifiers as ingest_identifiers
from scholaraio.services.ingest import inbox_orchestration as ingest_inbox_orchestration
from scholaraio.services.ingest import inbox_steps as ingest_inbox_steps
from scholaraio.services.ingest import paths as ingest_paths
from scholaraio.services.ingest import pending as ingest_pending
from scholaraio.services.ingest import pipeline_runner as ingest_pipeline_runner
from scholaraio.services.ingest import proceedings as ingest_proceedings
from scholaraio.services.ingest import registry as ingest_registry
from scholaraio.services.ingest import step_registry as ingest_step_registry
from scholaraio.services.ingest import steps as ingest_steps
from scholaraio.services.ingest.types import InboxCtx as InboxCtx
from scholaraio.services.ingest.types import StepDef as StepDef
from scholaraio.services.ingest.types import StepResult as StepResult
from scholaraio.services.metrics import timer as timer

_log = logging.getLogger("scholaraio.ingest.pipeline")

# Legacy private helper aliases remain available during the compatibility window.
_cfg_dir = ingest_paths.cfg_dir
_inbox_dir = ingest_paths.inbox_dir
_doc_inbox_dir = ingest_paths.doc_inbox_dir
_thesis_inbox_dir = ingest_paths.thesis_inbox_dir
_patent_inbox_dir = ingest_paths.patent_inbox_dir
_proceedings_inbox_dir = ingest_paths.proceedings_inbox_dir
_pending_dir = ingest_paths.pending_dir
_proceedings_dir = ingest_paths.proceedings_dir

# Legacy private helper aliases remain available while pure asset helpers move out.
_find_assets = ingest_assets.find_assets
_asset_stem_candidates = ingest_assets.asset_stem_candidates
_safe_pdf_artifact_stem_from_stem = ingest_assets.safe_pdf_artifact_stem_from_stem
_path_is_dir = ingest_assets.path_is_dir
_safe_glob = ingest_assets.safe_glob
_strip_artifact_prefix = ingest_assets.strip_artifact_prefix
_move_assets = ingest_assets.move_assets
_cleanup_assets = ingest_assets.cleanup_assets

# Legacy private identifier helpers remain available for callers and tests.
_collect_existing_ids = ingest_identifiers.collect_existing_ids
_collect_existing_dois = ingest_identifiers.collect_existing_dois
_normalize_arxiv_id = ingest_identifiers.normalize_arxiv_id
_parse_detect_json = ingest_detection.parse_detect_json
_load_doc_sidecar_metadata = ingest_documents.load_doc_sidecar_metadata
_repair_abstract = ingest_documents.repair_abstract
_registry_migrated = ingest_registry.registry_migrated
_ensure_registry_schema = ingest_registry.ensure_registry_schema
_update_registry = ingest_registry.update_registry
_cleanup_inbox = ingest_cleanup.cleanup_inbox
_move_to_pending = ingest_pending.move_to_pending
_detect_patent = ingest_detection.detect_patent
_detect_thesis = ingest_detection.detect_thesis
_detect_book = ingest_detection.detect_book
_ingest_proceedings_ctx = ingest_proceedings.ingest_proceedings_ctx
_move_batch_images = ingest_batch_assets.move_batch_images
_flatten_cloud_batch_output = ingest_batch_assets.flatten_cloud_batch_output
_postprocess_convert = ingest_batch_postprocess.postprocess_convert
_batch_postprocess = ingest_batch_postprocess.batch_postprocess
batch_convert_pdfs = ingest_batch_convert.batch_convert_pdfs
import_external = ingest_external_import.import_external
_process_inbox = ingest_inbox_orchestration.process_inbox
run_pipeline = ingest_pipeline_runner.run_pipeline

step_mineru = ingest_inbox_steps.step_mineru
step_office_convert = ingest_inbox_steps.step_office_convert
step_extract_doc = ingest_inbox_steps.step_extract_doc
step_extract = ingest_inbox_steps.step_extract
step_dedup = ingest_inbox_steps.step_dedup
step_ingest = ingest_inbox_steps.step_ingest
step_toc = ingest_steps.step_toc
step_l3 = ingest_steps.step_l3
step_translate = ingest_steps.step_translate
step_embed = ingest_steps.step_embed
step_index = ingest_steps.step_index
step_refetch = ingest_steps.step_refetch

STEPS = ingest_step_registry.STEPS
PRESETS = ingest_step_registry.PRESETS
_DOC_INBOX_STEPS = ingest_step_registry.DOC_INBOX_STEPS
_OFFICE_EXTENSIONS = ingest_step_registry.OFFICE_EXTENSIONS
