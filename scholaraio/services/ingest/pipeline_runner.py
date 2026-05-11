"""Top-level ingest pipeline runner."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from scholaraio.core.config import Config
from scholaraio.core.log import ui as _base_ui
from scholaraio.services.ingest import identifiers, inbox_orchestration, paths
from scholaraio.services.ingest.types import StepDef, StepResult
from scholaraio.services.metrics import timer

_log = logging.getLogger(__name__)
_DOC_INBOX_STEPS = ["office_convert", "mineru", "extract_doc", "ingest"]


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


def run_pipeline(
    step_names: list[str],
    cfg: Config,
    opts: dict[str, Any],
) -> None:
    """执行指定步骤序列。

    按 scope 分三阶段依次执行:
      1. **inbox** — 逐个文件: mineru → extract → dedup → ingest
      2. **papers** — 逐篇已入库论文: toc → l3 → translate（auto_translate 开启时自动注入）
      3. **global** — 全局执行一次: embed → index

    当 ``config.translate.auto_translate`` 为 ``True`` 且 pipeline 包含 inbox 步骤时，
    会在 papers scope 阶段自动注入 translate 步骤（位于 embed/index 之前）。

    Args:
        step_names: 步骤名称列表，如 ``["extract", "dedup", "ingest"]``。
            可用步骤见 ``STEPS``。
        cfg: 全局配置。
        opts: 运行选项字典，支持的键:

            - ``dry_run`` (bool): 预览模式，不写文件。
            - ``no_api`` (bool): 跳过外部 API 查询。
            - ``force`` (bool): 强制重新处理（toc/l3）。
            - ``inspect`` (bool): 展示处理详情。
            - ``max_retries`` (int): l3 最大重试次数。
            - ``rebuild`` (bool): 重建索引（index/embed）。
            - ``inbox_dir`` (Path): 自定义 inbox 目录。
            - ``doc_inbox_dir`` (Path): 自定义 document inbox 目录。
            - ``papers_dir`` (Path): 自定义 papers 目录。
    """
    steps = _steps()
    # Auto-inject translate step when config.translate.auto_translate is enabled.
    # Only inject when the pipeline includes inbox steps (i.e. new papers are being ingested),
    # to avoid triggering LLM translation on unrelated runs like reindex/embed.
    has_inbox = any(n in steps and steps[n].scope == "inbox" for n in step_names)
    if cfg.translate.auto_translate and has_inbox and "translate" not in step_names and "translate" in steps:
        # Insert translate before global-scope steps (embed/index)
        first_global = next(
            (i for i, n in enumerate(step_names) if n in steps and steps[n].scope == "global"),
            len(step_names),
        )
        step_names = [*step_names[:first_global], "translate", *step_names[first_global:]]

    # Validate steps
    for name in step_names:
        if name not in steps:
            _logger().error("unknown step '%s'. available: %s", name, ", ".join(steps))
            sys.exit(1)

    inbox_dir_fn = _pipeline_attr("_inbox_dir", paths.inbox_dir)
    doc_inbox_dir_fn = _pipeline_attr("_doc_inbox_dir", paths.doc_inbox_dir)
    thesis_inbox_dir_fn = _pipeline_attr("_thesis_inbox_dir", paths.thesis_inbox_dir)
    patent_inbox_dir_fn = _pipeline_attr("_patent_inbox_dir", paths.patent_inbox_dir)
    proceedings_inbox_dir_fn = _pipeline_attr("_proceedings_inbox_dir", paths.proceedings_inbox_dir)
    pending_dir_fn = _pipeline_attr("_pending_dir", paths.pending_dir)

    inbox_dir: Path = opts.get("inbox_dir", inbox_dir_fn(cfg))
    doc_inbox: Path = opts.get("doc_inbox_dir", doc_inbox_dir_fn(cfg))
    has_custom_doc_inbox = "doc_inbox_dir" in opts
    papers_dir: Path = opts.get("papers_dir", cfg.papers_dir)
    pending_dir: Path = pending_dir_fn(cfg)
    include_aux_inboxes: bool = opts.get("include_aux_inboxes", True)

    inbox_steps = [n for n in step_names if steps[n].scope == "inbox"]
    papers_steps = [n for n in step_names if steps[n].scope == "papers"]
    global_steps = [n for n in step_names if steps[n].scope == "global"]

    dry_run = opts.get("dry_run", False)
    ingested_jsons: list[Path] = []  # track newly ingested papers

    # ---- Inbox scope ----
    if inbox_steps:
        collect_existing_ids = _pipeline_attr("_collect_existing_ids", identifiers.collect_existing_ids)
        process_inbox = _pipeline_attr("_process_inbox", inbox_orchestration.process_inbox)
        existing_dois, existing_pub_nums, existing_arxiv_ids = collect_existing_ids(papers_dir)

        # Process regular inbox
        _result = process_inbox(
            inbox_dir,
            papers_dir,
            pending_dir,
            existing_dois,
            inbox_steps,
            cfg,
            opts,
            dry_run,
            ingested_jsons,
            is_thesis=False,
            existing_pub_nums=existing_pub_nums,
            existing_arxiv_ids=existing_arxiv_ids,
        )

        # Process thesis inbox.
        thesis_inbox = thesis_inbox_dir_fn(cfg)
        if include_aux_inboxes and thesis_inbox.exists():
            process_inbox(
                thesis_inbox,
                papers_dir,
                pending_dir,
                existing_dois,
                inbox_steps,
                cfg,
                opts,
                dry_run,
                ingested_jsons,
                is_thesis=True,
                existing_pub_nums=existing_pub_nums,
                existing_arxiv_ids=existing_arxiv_ids,
            )

        # Process patent inbox.
        patent_inbox = patent_inbox_dir_fn(cfg)
        if include_aux_inboxes and patent_inbox.exists():
            process_inbox(
                patent_inbox,
                papers_dir,
                pending_dir,
                existing_dois,
                inbox_steps,
                cfg,
                opts,
                dry_run,
                ingested_jsons,
                is_patent=True,
                existing_pub_nums=existing_pub_nums,
                existing_arxiv_ids=existing_arxiv_ids,
            )

        # Process document inbox.
        if (include_aux_inboxes or has_custom_doc_inbox) and doc_inbox.exists():
            # Documents use extract_doc + ingest (skip dedup/API queries)
            doc_inbox_steps = _pipeline_attr("_DOC_INBOX_STEPS", _DOC_INBOX_STEPS)
            doc_steps = [s for s in doc_inbox_steps if s in steps]
            process_inbox(
                doc_inbox,
                papers_dir,
                pending_dir,
                existing_dois,
                doc_steps,
                cfg,
                opts,
                dry_run,
                ingested_jsons,
                is_thesis=False,
                existing_pub_nums=existing_pub_nums,
                existing_arxiv_ids=existing_arxiv_ids,
            )

        proceedings_inbox = proceedings_inbox_dir_fn(cfg)
        if include_aux_inboxes and proceedings_inbox.exists():
            process_inbox(
                proceedings_inbox,
                papers_dir,
                pending_dir,
                existing_dois,
                inbox_steps,
                cfg,
                opts,
                dry_run,
                ingested_jsons,
                is_proceedings=True,
                existing_pub_nums=existing_pub_nums,
                existing_arxiv_ids=existing_arxiv_ids,
            )

    # ---- Papers scope ----
    if papers_steps:
        if inbox_steps and ingested_jsons:
            # Only enrich newly ingested papers, not the whole library
            json_paths = sorted(ingested_jsons)
            _ui(f"\nRunning {', '.join(papers_steps)} on {len(json_paths)} new papers")
        elif inbox_steps and not ingested_jsons:
            # Inbox ran but nothing was ingested — skip papers scope
            json_paths = []
        else:
            # No inbox steps (e.g. `pipeline enrich`) — process all
            from scholaraio.stores.papers import iter_paper_dirs

            json_paths = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
        if not json_paths:
            if not inbox_steps:
                _ui(f"No papers in: {papers_dir}")
        else:
            ok_total = fail_total = skip_total = 0
            step_times: dict[str, float] = {}

            # Concurrent execution for papers_steps when LLM-bound steps
            # (toc, l3, translate) are present. All papers_steps run per-paper
            # inside _process_one_paper(); different papers execute in parallel.
            llm_steps = {"toc", "l3", "translate"}
            has_llm_steps = bool(set(papers_steps) & llm_steps)
            if has_llm_steps and "translate" in papers_steps:
                # When translate coexists with other LLM steps (toc/l3), use the
                # lower of the two limits to avoid exceeding backend rate limits.
                workers = min(cfg.translate.concurrency, cfg.llm.concurrency)
            elif has_llm_steps:
                workers = cfg.llm.concurrency
            else:
                workers = 1

            def _process_one_paper(json_path: Path) -> tuple[str, dict[str, float]]:
                """Process all papers_steps for one paper. Returns (status, timings)."""
                paper_ok = True
                paper_skipped = False
                timings: dict[str, float] = {}
                timer_func = _pipeline_attr("timer", timer)
                for step_name in papers_steps:
                    with timer_func(f"pipeline.papers.{step_name}", "step") as t:
                        result = steps[step_name].fn(json_path, cfg, opts)
                    timings[step_name] = t.elapsed
                    if result == StepResult.SKIP:
                        _logger().debug("%s: skipped", step_name)
                        paper_skipped = True
                    elif result == StepResult.FAIL:
                        _logger().debug("%s: %.1fs FAIL", step_name, t.elapsed)
                        paper_ok = False
                    else:
                        _logger().debug("%s: %.1fs OK", step_name, t.elapsed)
                if paper_skipped and paper_ok:
                    return "skip", timings
                return ("ok" if paper_ok else "fail"), timings

            if workers > 1 and len(json_paths) > 1:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                _ui(f"  (concurrency: {workers} workers)")
                with ThreadPoolExecutor(max_workers=min(workers, len(json_paths))) as pool:
                    futures = {pool.submit(_process_one_paper, jp): jp for jp in json_paths}
                    for done_count, fut in enumerate(as_completed(futures), 1):
                        jp = futures[fut]
                        try:
                            status, timings = fut.result()
                        except Exception:
                            _logger().exception("paper failed: %s", jp.parent.name)
                            status, timings = "fail", {}
                        _ui(f"  [{done_count}/{len(json_paths)}] {jp.parent.name} [{status}]")
                        if status == "skip":
                            skip_total += 1
                        elif status == "ok":
                            ok_total += 1
                        else:
                            fail_total += 1
                        for sn, st in timings.items():
                            step_times[sn] = step_times.get(sn, 0) + st
            else:
                for json_path in json_paths:
                    _ui(f"\n{json_path.parent.name}")
                    try:
                        status, timings = _process_one_paper(json_path)
                    except Exception:
                        _logger().exception("paper failed: %s", json_path.parent.name)
                        status, timings = "fail", {}
                    if status == "skip":
                        skip_total += 1
                    elif status == "ok":
                        ok_total += 1
                    else:
                        fail_total += 1
                    for sn, st in timings.items():
                        step_times[sn] = step_times.get(sn, 0) + st

            _ui(f"\nPapers done: {ok_total} ok | {fail_total} failed | {skip_total} skipped")
            if step_times:
                _ui("Step timing:")
                for sn, st in step_times.items():
                    _ui(f"  {sn:12s} {st:6.1f}s")
                _ui(f"  {'total':12s} {sum(step_times.values()):6.1f}s")

    # ---- Global scope ----
    for step_name in global_steps:
        timer_func = _pipeline_attr("timer", timer)
        with timer_func(f"pipeline.global.{step_name}", "step") as t:
            steps[step_name].fn(papers_dir, cfg, opts)
        _logger().debug("%s: %.1fs", step_name, t.elapsed)
