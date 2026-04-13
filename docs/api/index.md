# API Reference

::: scholaraio.index
    options:
      members:
        - build_index
        - build_proceedings_index
        - search
        - search_author
        - top_cited
        - unified_search
        - search_proceedings
        - lookup_paper
        - get_references
        - get_citing_papers
        - get_shared_references

::: scholaraio.loader
    options:
      members:
        - load_l1
        - load_l2
        - load_l3
        - load_l4
        - load_notes
        - append_notes
        - enrich_toc
        - enrich_l3

::: scholaraio.export
    options:
      members:
        - meta_to_bibtex
        - export_bibtex

::: scholaraio.audit
    options:
      members:
        - Issue
        - audit_papers

::: scholaraio.workspace
    options:
      members:
        - create
        - add
        - remove
        - list_workspaces
        - read_paper_ids

::: scholaraio.papers
    options:
      members:
        - paper_dir
        - meta_path
        - md_path
        - iter_paper_dirs

::: scholaraio.proceedings
    options:
      members:
        - proceedings_db_path
        - iter_proceedings_dirs
        - iter_proceedings_papers

::: scholaraio.vectors
    options:
      members:
        - build_vectors
        - vsearch

::: scholaraio.topics
    options:
      members:
        - build_topics
        - load_model
        - get_topic_overview
        - get_topic_papers
        - get_outliers
        - reduce_topics_to
        - merge_topics_by_ids

::: scholaraio.translate
    options:
      members:
        - translate_paper
        - batch_translate
        - detect_language

::: scholaraio.explore
    options:
      members:
        - fetch_explore
        - build_explore_vectors
        - build_explore_topics
        - explore_search
        - explore_vsearch
        - explore_unified_search
        - list_explore_libs
        - explore_db_path
        - validate_explore_name

::: scholaraio.insights
    options:
      members:
        - extract_hot_keywords
        - aggregate_most_read_titles
        - build_weekly_read_trend
        - recent_unique_read_names
        - recommend_unread_neighbors
        - list_workspace_counts

::: scholaraio.ingest.extractor
    options:
      members:
        - get_extractor

::: scholaraio.ingest.metadata
    options:
      members:
        - PaperMetadata
        - enrich_metadata
        - extract_abstract_from_md
        - fetch_abstract_by_doi
        - backfill_abstracts
        - generate_new_stem
        - metadata_to_dict
        - refetch_metadata
        - rename_paper
        - write_metadata_json

::: scholaraio.ingest.pipeline
    options:
      members:
        - StepResult
        - InboxCtx
        - run_pipeline
        - import_external
        - batch_convert_pdfs
        - step_embed
        - step_index
