from __future__ import annotations

import json
import sqlite3

import pytest

from scholaraio.core.config import _build_config
from scholaraio.services.index import build_index, build_proceedings_index
from scholaraio.services.migration_control import (
    append_migration_journal_step,
    clear_migration_lock,
    describe_migration_lock,
    ensure_instance_metadata,
    ensure_migration_journal,
    run_migration_cleanup,
    run_migration_finalize,
    run_migration_plan,
    run_migration_store,
    run_migration_upgrade,
    run_migration_verification,
    write_instance_metadata,
    write_migration_lock,
)
from scholaraio.stores.toolref.constants import TOOL_REGISTRY


def _write_toolref_fixture(toolref_root):
    tool_name = next(iter(TOOL_REGISTRY))
    tool_version_dir = toolref_root / tool_name / "v1"
    tool_version_dir.mkdir(parents=True, exist_ok=True)
    (tool_version_dir / "meta.json").write_text(json.dumps({"source_type": "git"}), encoding="utf-8")
    (toolref_root / tool_name / "current").symlink_to("v1")

    conn = sqlite3.connect(toolref_root / tool_name / "toolref.db")
    try:
        conn.execute(
            """
            CREATE TABLE toolref_pages (
                id INTEGER PRIMARY KEY,
                tool TEXT NOT NULL,
                version TEXT NOT NULL,
                program TEXT,
                section TEXT,
                page_name TEXT NOT NULL,
                title TEXT,
                category TEXT,
                var_type TEXT,
                default_val TEXT,
                synopsis TEXT,
                content TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO toolref_pages
                (tool, version, program, section, page_name, title, synopsis, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tool_name, "v1", "pw", "input", "pw/scf", "scf", "pw scf", "Self-consistent field"),
        )
        conn.commit()
    finally:
        conn.close()
    return tool_name


def _write_explore_fixture(explore_root):
    explore_dir = explore_root / "demo-explore"
    explore_dir.mkdir(parents=True, exist_ok=True)
    (explore_dir / "papers.jsonl").write_text(
        json.dumps(
            {
                "openalex_id": "W1",
                "title": "Explore turbulence library",
                "abstract": "Exploration token for verify search.",
                "authors": ["Explore Author"],
                "year": 2026,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sqlite3.connect(explore_dir / "explore.db").close()
    return explore_dir.name


def _write_proceedings_fixture(proceedings_root):
    proceeding_dir = proceedings_root / "Proc-2026-Test"
    child_dir = proceeding_dir / "papers" / "Wave-2026-Test"
    child_dir.mkdir(parents=True, exist_ok=True)
    (proceeding_dir / "meta.json").write_text(
        json.dumps({"id": "proc-1", "title": "Proceedings of Verification 2026"}),
        encoding="utf-8",
    )
    (child_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "proc-paper-1",
                "title": "Granular proceedings verification",
                "abstract": "Granular proceedings verification token.",
                "authors": ["Pat Chen"],
                "year": 2026,
                "paper_type": "conference-paper",
                "proceeding_title": "Proceedings of Verification 2026",
            }
        ),
        encoding="utf-8",
    )
    (child_dir / "paper.md").write_text("# Granular proceedings verification\n", encoding="utf-8")
    build_proceedings_index(proceedings_root, proceedings_root / "proceedings.db", rebuild=True)
    return proceeding_dir.name


def _write_spool_fixture(data_root):
    fixtures = {
        "inbox": ("paper.md", "# Paper queued for ingest\n"),
        "inbox-thesis": ("thesis.md", "# Thesis queued for ingest\n"),
        "inbox-patent": ("patent.md", "# Patent queued for ingest\n"),
        "inbox-doc": ("report.md", "# Document queued for ingest\n"),
        "inbox-proceedings": ("volume.md", "# Proceedings queued for ingest\n"),
        "pending/Needs-Review": ("pending.json", json.dumps({"issue": "no_doi", "title": "Needs Review"})),
    }
    for rel_dir, (filename, content) in fixtures.items():
        path = data_root / rel_dir
        path.mkdir(parents=True, exist_ok=True)
        (path / filename).write_text(content, encoding="utf-8")


def _write_papers_fixture(papers_root):
    paper_dir = papers_root / "Doe-2026-Paper-Migration"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "paper-1",
                "title": "Paper migration verification",
                "authors": ["Jane Doe"],
                "year": 2026,
                "journal": "Migration Journal",
                "doi": "10.1234/paper.migration",
                "abstract": "Durable paper migration keyword.",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "paper.md").write_text("# Paper migration verification\n", encoding="utf-8")
    return paper_dir.name


def test_ensure_instance_metadata_creates_legacy_implicit_record(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    meta = ensure_instance_metadata(cfg)

    assert cfg.instance_meta_path.exists()
    assert meta["instance_meta_version"] == 1
    assert meta["layout_version"] == 0
    assert meta["layout_state"] == "legacy_implicit"
    assert meta["writer_version"]
    assert meta["instance_id"]
    assert meta["last_successful_migration_id"] is None


def test_ensure_instance_metadata_is_idempotent_and_preserves_instance_id(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    first = ensure_instance_metadata(cfg)
    second = ensure_instance_metadata(cfg)
    stored = json.loads(cfg.instance_meta_path.read_text(encoding="utf-8"))

    assert second["instance_id"] == first["instance_id"]
    assert stored["instance_id"] == first["instance_id"]
    assert stored["layout_state"] == "legacy_implicit"


def test_write_and_clear_migration_lock(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    payload = write_migration_lock(cfg, migration_id="mig-001", pid=999999, hostname="test-host")
    status = describe_migration_lock(cfg)

    assert payload["migration_id"] == "mig-001"
    assert cfg.migration_lock_path.exists()
    assert status["status"] == "active"
    assert status["lock"]["hostname"] == "test-host"

    assert clear_migration_lock(cfg) is True
    assert clear_migration_lock(cfg) is False
    assert describe_migration_lock(cfg)["status"] == "absent"


def test_ensure_migration_journal_scaffolds_expected_files(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    journal_dir = ensure_migration_journal(cfg, migration_id="mig-001")

    assert journal_dir == cfg.migration_journals_root / "mig-001"
    assert (journal_dir / "plan.json").exists()
    assert (journal_dir / "steps.jsonl").exists()
    assert (journal_dir / "verify.json").exists()
    assert (journal_dir / "rollback.json").exists()
    assert (journal_dir / "summary.md").exists()

    verify = json.loads((journal_dir / "verify.json").read_text(encoding="utf-8"))
    assert verify["status"] == "not_run"


def test_append_migration_journal_step_writes_jsonl(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_migration_journal(cfg, migration_id="mig-001")

    append_migration_journal_step(
        cfg,
        migration_id="mig-001",
        step_name="inventory",
        status="ok",
        message="planned runtime surfaces",
        details={"stores": 4},
    )

    lines = (cfg.migration_journals_root / "mig-001" / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["step"] == "inventory"
    assert payload["status"] == "ok"
    assert payload["message"] == "planned runtime surfaces"
    assert payload["details"]["stores"] == 4


def test_run_migration_verification_refreshes_verify_json(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    ensure_migration_journal(cfg, migration_id="mig-001")

    result = run_migration_verification(cfg, migration_id="mig-001")

    assert result["status"] == "passed"
    assert result["summary"]["failed"] == 0
    assert result["summary"]["total"] >= 4
    check_names = {check["name"] for check in result["checks"]}
    assert "instance_metadata_readable" in check_names
    assert "papers_dir_accessible" in check_names
    assert "workspace_root_accessible" in check_names

    stored = json.loads((cfg.migration_journals_root / "mig-001" / "verify.json").read_text(encoding="utf-8"))
    assert stored["status"] == "passed"

    steps = (cfg.migration_journals_root / "mig-001" / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
    last_step = json.loads(steps[-1])
    assert last_step["step"] == "verify"
    assert last_step["status"] == "ok"

    summary = (cfg.migration_journals_root / "mig-001" / "summary.md").read_text(encoding="utf-8")
    assert "verify_status: passed" in summary
    assert "checks_passed:" in summary


def test_run_migration_verification_covers_runtime_component_inventories(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    ensure_migration_journal(cfg, migration_id="mig-001")

    paper_dir = cfg.papers_dir / "Doe-2026-Test"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "paper-1",
                "title": "Turbulence verification test",
                "authors": ["Jane Doe"],
                "year": 2026,
                "journal": "Journal of Verification",
                "abstract": "Turbulence search token for migration verification.",
            }
        ),
        encoding="utf-8",
    )
    workdir = paper_dir / ".translate_zh"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "state.json").write_text(json.dumps({"completed_chunks": 1}), encoding="utf-8")
    build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

    ws_dir = cfg.workspace_dir / "demo-ws"
    (ws_dir / "refs").mkdir(parents=True, exist_ok=True)
    (ws_dir / "refs" / "papers.json").write_text(
        json.dumps([{"id": "paper-1", "dir_name": paper_dir.name}]),
        encoding="utf-8",
    )

    style_path = cfg.citation_styles_dir / "custom.py"
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text(
        "def format_ref(meta, idx=None):\n"
        '    prefix = f"{idx}. " if idx is not None else "- "\n'
        "    return prefix + (meta.get('title') or 'untitled')\n",
        encoding="utf-8",
    )

    explore_dir = cfg.explore_root / "demo-explore"
    explore_dir.mkdir(parents=True, exist_ok=True)
    (explore_dir / "papers.jsonl").write_text(
        json.dumps(
            {
                "openalex_id": "W1",
                "title": "Explore turbulence library",
                "abstract": "Exploration token for verify search.",
                "authors": ["Explore Author"],
                "year": 2026,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sqlite3.connect(explore_dir / "explore.db").close()

    tool_name = next(iter(TOOL_REGISTRY))
    tool_version_dir = cfg.toolref_root / tool_name / "v1"
    tool_version_dir.mkdir(parents=True, exist_ok=True)
    (cfg.toolref_root / tool_name / "current").symlink_to("v1")

    conn = sqlite3.connect(cfg.toolref_root / tool_name / "toolref.db")
    try:
        conn.execute(
            """
            CREATE TABLE toolref_pages (
                id INTEGER PRIMARY KEY,
                tool TEXT NOT NULL,
                version TEXT NOT NULL,
                program TEXT,
                section TEXT,
                page_name TEXT NOT NULL,
                title TEXT,
                category TEXT,
                var_type TEXT,
                default_val TEXT,
                synopsis TEXT,
                content TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO toolref_pages
                (tool, version, program, section, page_name, title, synopsis, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tool_name, "v1", "pw", "input", "pw/scf", "scf", "pw scf", "Self-consistent field"),
        )
        conn.commit()
    finally:
        conn.close()

    proceeding_dir = cfg.proceedings_dir / "Proc-2026-Test"
    child_dir = proceeding_dir / "papers" / "Wave-2026-Test"
    child_dir.mkdir(parents=True, exist_ok=True)
    (proceeding_dir / "meta.json").write_text(
        json.dumps({"id": "proc-1", "title": "Proceedings of Verification 2026"}),
        encoding="utf-8",
    )
    (child_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "proc-paper-1",
                "title": "Granular verification wave",
                "authors": ["Alice Zheng"],
                "year": 2026,
                "journal": "Proc. Verification",
                "abstract": "Granular proceedings verification token.",
            }
        ),
        encoding="utf-8",
    )
    build_proceedings_index(cfg.proceedings_dir, cfg.proceedings_dir / "proceedings.db", rebuild=True)

    result = run_migration_verification(cfg, migration_id="mig-001")

    checks = {check["name"]: check for check in result["checks"]}
    assert checks["papers_inventory"]["details"]["paper_dir_count"] == 1
    assert checks["workspace_inventory"]["details"]["workspace_count"] == 1
    assert checks["index_registry_accessible"]["details"]["sample_hit"] is True
    assert checks["keyword_search_accessible"]["details"]["result_count"] == 1
    assert checks["citation_styles_accessible"]["details"]["sample_style"] == "custom"
    assert checks["explore_inventory"]["details"]["explore_lib_count"] == 1
    assert checks["explore_search_accessible"]["details"]["result_count"] == 1
    assert checks["toolref_inventory"]["details"]["version_count"] == 1
    assert checks["toolref_current_version_accessible"]["details"]["result_count"] == 1
    assert checks["proceedings_search_accessible"]["details"]["result_count"] == 1
    assert checks["spool_roots_accessible"]["details"]["root_count"] == 6
    assert checks["translation_resume_inventory"]["details"]["resume_state_count"] == 1

    summary = (cfg.migration_journals_root / "mig-001" / "summary.md").read_text(encoding="utf-8")
    assert "verify_status: passed" in summary
    assert "checks_passed: 18/18" in summary


def test_run_migration_verification_keyword_probe_handles_common_leading_tokens(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    ensure_migration_journal(cfg, migration_id="mig-keyword-probe-001")

    target_dir = cfg.papers_dir / "A-2026-Alpha-Target-Verification"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "paper-target",
                "title": "Alpha Target Verification",
                "authors": ["Verify, Alice"],
                "year": 2026,
                "journal": "Verification Journal",
                "abstract": "A focused verification paper.",
            }
        ),
        encoding="utf-8",
    )

    for idx in range(1, 4):
        distractor_dir = cfg.papers_dir / f"B{idx}-2026-Alpha-Distractor-{idx}"
        distractor_dir.mkdir(parents=True, exist_ok=True)
        (distractor_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": f"paper-distractor-{idx}",
                    "title": f"Alpha Distractor {idx}",
                    "authors": ["Noise, Bob"],
                    "year": 2026,
                    "journal": "Distractor Journal",
                    "abstract": ("Alpha " * 40).strip(),
                }
            ),
            encoding="utf-8",
        )

    build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

    result = run_migration_verification(cfg, migration_id="mig-keyword-probe-001")

    checks = {check["name"]: check for check in result["checks"]}
    assert result["status"] == "passed"
    assert checks["keyword_search_accessible"]["details"]["sample_ref"] == target_dir.name
    assert checks["keyword_search_accessible"]["details"]["sample_hit"] is True
    assert checks["keyword_search_accessible"]["details"]["query"] == "Alpha Target Verification"


def test_run_migration_plan_writes_inventory_to_plan_json(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    (cfg.workspace_dir / "demo-ws").mkdir(parents=True, exist_ok=True)
    paper_dir = cfg.papers_dir / "Doe-2026-Test"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "meta.json").write_text("{}", encoding="utf-8")

    result = run_migration_plan(cfg, migration_id="mig-plan-001")

    assert result["migration_id"] == "mig-plan-001"
    assert result["plan_state"] == "planned"
    assert result["stores"]["papers"]["item_count"] == 1
    assert result["stores"]["workspace"]["item_count"] == 1

    stored = json.loads((cfg.migration_journals_root / "mig-plan-001" / "plan.json").read_text(encoding="utf-8"))
    assert stored["stores"]["papers"]["item_count"] == 1

    steps = (
        (cfg.migration_journals_root / "mig-plan-001" / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
    )
    last_step = json.loads(steps[-1])
    assert last_step["step"] == "plan"
    assert last_step["status"] == "ok"

    summary = (cfg.migration_journals_root / "mig-plan-001" / "summary.md").read_text(encoding="utf-8")
    assert "plan_state: planned" in summary
    assert "blockers: 0" in summary


def test_run_migration_plan_excludes_reserved_workspace_output_dirs(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    (cfg.workspace_dir / "demo-ws").mkdir(parents=True, exist_ok=True)

    result = run_migration_plan(cfg, migration_id="mig-plan-outputs-001")

    workspace_store = result["stores"]["workspace"]
    assert workspace_store["item_count"] == 1
    assert workspace_store["workspace_names"] == ["demo-ws"]
    assert "_system" in workspace_store["ignored_dir_names"]


def test_run_migration_plan_records_store_targets_and_planned_legacy_moves(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)

    legacy_explore = tmp_path / "data" / "explore" / "demo-explore"
    legacy_explore.mkdir(parents=True, exist_ok=True)
    (legacy_explore / "papers.jsonl").write_text('{"openalex_id":"W1"}\n', encoding="utf-8")

    tool_name = next(iter(TOOL_REGISTRY))
    (tmp_path / "data" / "toolref" / tool_name / "v1").mkdir(parents=True, exist_ok=True)

    proceeding_dir = tmp_path / "data" / "proceedings" / "Proc-2026-Test"
    child_dir = proceeding_dir / "papers" / "Wave-2026-Test"
    child_dir.mkdir(parents=True, exist_ok=True)
    (proceeding_dir / "meta.json").write_text(
        json.dumps({"id": "proc-1", "title": "Plan Proceedings"}), encoding="utf-8"
    )
    (child_dir / "meta.json").write_text(json.dumps({"id": "proc-paper-1", "title": "Plan Wave"}), encoding="utf-8")

    style_path = tmp_path / "data" / "citation_styles" / "custom.py"
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text("def format_entry(entry):\n    return 'custom'\n", encoding="utf-8")

    result = run_migration_plan(cfg, migration_id="mig-plan-002")

    assert result["stores"]["citation_styles"]["target_path"] == str(
        tmp_path / "data" / "libraries" / "citation_styles"
    )
    assert result["stores"]["papers"]["target_path"] == str(tmp_path / "data" / "libraries" / "papers")
    assert result["stores"]["papers"]["migration_phase"] == "A10"
    assert result["stores"]["citation_styles"]["migration_phase"] == "A7"
    assert result["stores"]["toolref"]["version_count"] == 1
    assert result["stores"]["toolref"]["migration_phase"] == "A7"
    assert result["stores"]["explore"]["library_count"] == 1
    assert result["stores"]["explore"]["migration_phase"] == "A7"
    assert result["stores"]["proceedings"]["volume_count"] == 1
    assert result["stores"]["proceedings"]["child_paper_count"] == 1
    assert result["stores"]["proceedings"]["migration_phase"] == "A8"
    assert result["stores"]["spool"]["migration_phase"] == "A9"
    assert result["stores"]["spool"]["root_count"] == 6
    assert result["cleanup_candidates"] == []
    assert len(result["planned_cleanup_candidates"]) == 4
    assert {item["store"] for item in result["planned_cleanup_candidates"]} == {
        "citation_styles",
        "explore",
        "proceedings",
        "toolref",
    }

    stored = json.loads((cfg.migration_journals_root / "mig-plan-002" / "plan.json").read_text(encoding="utf-8"))
    assert stored["planned_cleanup_candidates"] == result["planned_cleanup_candidates"]


def test_run_migration_cleanup_requires_successful_verify(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    ensure_migration_journal(cfg, migration_id="mig-cleanup-001")

    with pytest.raises(RuntimeError, match="successful verification"):
        run_migration_cleanup(cfg, migration_id="mig-cleanup-001", confirm=False)


def test_run_migration_cleanup_records_preview_and_safe_noop_confirm(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    ensure_migration_journal(cfg, migration_id="mig-cleanup-001")
    run_migration_verification(cfg, migration_id="mig-cleanup-001")

    preview = run_migration_cleanup(cfg, migration_id="mig-cleanup-001", confirm=False)
    confirmed = run_migration_cleanup(cfg, migration_id="mig-cleanup-001", confirm=True)

    assert preview["status"] == "preview"
    assert preview["candidate_count"] == 0
    assert preview["removed_count"] == 0
    assert confirmed["status"] == "completed_noop"
    assert confirmed["removed_count"] == 0

    steps = (
        (cfg.migration_journals_root / "mig-cleanup-001" / "steps.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    preview_step = json.loads(steps[-2])
    cleanup_step = json.loads(steps[-1])
    assert preview_step["step"] == "cleanup_preview"
    assert preview_step["status"] == "ok"
    assert cleanup_step["step"] == "cleanup"
    assert cleanup_step["status"] == "ok"

    summary = (cfg.migration_journals_root / "mig-cleanup-001" / "summary.md").read_text(encoding="utf-8")
    assert "cleanup_status: completed_noop" in summary
    assert "cleanup_candidates: 0" in summary


def test_run_migration_cleanup_archives_recorded_candidates_after_successful_run(tmp_path):
    from scholaraio.stores.citation_styles import get_formatter

    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=True)

    result = run_migration_cleanup(cfg, migration_id="mig-run-001", confirm=True)

    archive_styles = cfg.migration_journals_root / "mig-run-001" / "archive" / "data" / "citation_styles"
    assert result["status"] == "completed_archived"
    assert result["candidate_count"] == 1
    assert result["archived_count"] == 1
    assert result["removed_count"] == 0
    assert result["confirm_required"] is False
    assert not legacy_styles.exists()
    assert (archive_styles / "custom.py").read_text(encoding="utf-8").endswith("return 'legacy'\n")
    assert get_formatter("custom", cfg)({}, None) == "legacy"

    steps = (
        (cfg.migration_journals_root / "mig-run-001" / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
    )
    cleanup_step = json.loads(steps[-1])
    assert cleanup_step["step"] == "cleanup"
    assert cleanup_step["status"] == "ok"
    assert cleanup_step["details"]["archived_count"] == 1

    summary = (cfg.migration_journals_root / "mig-run-001" / "summary.md").read_text(encoding="utf-8")
    assert "cleanup_status: completed_archived" in summary
    assert "cleanup_archived: 1" in summary


def test_run_migration_cleanup_blocks_active_lock_before_archiving(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=True)
    write_migration_lock(cfg, migration_id="mig-other")

    with pytest.raises(RuntimeError, match=r"migration\.lock"):
        run_migration_cleanup(cfg, migration_id="mig-run-001", confirm=True)

    assert (legacy_styles / "custom.py").exists()
    assert not (cfg.migration_journals_root / "mig-run-001" / "archive" / "data" / "citation_styles").exists()


def test_run_migration_cleanup_blocks_unsupported_future_layout_before_archiving(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=True)
    meta = ensure_instance_metadata(cfg)
    meta["layout_version"] = 999
    write_instance_metadata(cfg, meta)

    with pytest.raises(RuntimeError, match="unsupported_future_layout"):
        run_migration_cleanup(cfg, migration_id="mig-run-001", confirm=True)

    assert (legacy_styles / "custom.py").exists()
    assert not (cfg.migration_journals_root / "mig-run-001" / "archive" / "data" / "citation_styles").exists()


def test_run_migration_cleanup_preview_does_not_archive_recorded_candidates(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=True)

    result = run_migration_cleanup(cfg, migration_id="mig-run-001", confirm=False)

    archive_styles = cfg.migration_journals_root / "mig-run-001" / "archive" / "data" / "citation_styles"
    assert result["status"] == "preview"
    assert result["candidate_count"] == 1
    assert result["archived_count"] == 0
    assert result["confirm_required"] is True
    assert legacy_styles.exists()
    assert not archive_styles.exists()


def test_run_migration_cleanup_blocks_candidates_outside_runtime_root(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    ensure_instance_metadata(cfg)
    journal_dir = ensure_migration_journal(
        cfg,
        migration_id="mig-cleanup-escape",
        plan={
            "migration_id": "mig-cleanup-escape",
            "plan_state": "planned",
            "cleanup_candidates": [
                {
                    "store": "citation_styles",
                    "legacy_path": str(tmp_path.parent / "outside-citation-styles"),
                    "target_path": str(tmp_path / "data" / "libraries" / "citation_styles"),
                    "cleanup_action": "archive",
                }
            ],
        },
    )
    (tmp_path / "data" / "libraries" / "citation_styles").mkdir(parents=True, exist_ok=True)
    run_migration_verification(cfg, migration_id="mig-cleanup-escape")

    result = run_migration_cleanup(cfg, migration_id="mig-cleanup-escape", confirm=True)

    assert result["status"] == "blocked"
    assert result["removed_count"] == 0
    assert result["archived_count"] == 0
    assert "outside runtime root" in result["blocked_reason"]

    cleanup_step = json.loads(journal_dir.joinpath("steps.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert cleanup_step["status"] == "blocked"


def test_run_migration_store_requires_confirm_for_citation_styles(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    with pytest.raises(RuntimeError, match="--confirm"):
        run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=False)


def test_run_migration_store_blocks_plan_blockers_before_copying_data(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    meta = ensure_instance_metadata(cfg)
    meta["layout_version"] = 999
    write_instance_metadata(cfg, meta)

    with pytest.raises(RuntimeError, match="migrate run blocked: unsupported_future_layout"):
        run_migration_store(cfg, store="citation_styles", migration_id="mig-run-blocked-001", confirm=True)

    assert not (cfg.citation_styles_dir / "custom.py").exists()
    assert describe_migration_lock(cfg)["status"] == "absent"


def test_run_migration_store_copies_legacy_citation_styles_and_records_cleanup_candidate(tmp_path):
    from scholaraio.stores.citation_styles import get_formatter

    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text(
        "def format_ref(meta, idx=None):\n    return 'legacy ' + (meta.get('title') or '')\n",
        encoding="utf-8",
    )

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    result = run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=True)

    target_styles = tmp_path / "data" / "libraries" / "citation_styles"
    assert result["status"] == "passed"
    assert result["store"] == "citation_styles"
    assert result["copied_count"] == 1
    assert result["cleanup_candidate_count"] == 1
    assert (target_styles / "custom.py").read_text(encoding="utf-8") == (legacy_styles / "custom.py").read_text(
        encoding="utf-8"
    )
    assert (legacy_styles / "custom.py").exists()
    assert cfg.citation_styles_dir == target_styles.resolve()
    assert get_formatter("custom", cfg)({"title": "Smoke"}, None) == "legacy Smoke"

    plan = json.loads((cfg.migration_journals_root / "mig-run-001" / "plan.json").read_text(encoding="utf-8"))
    assert plan["cleanup_candidates"][0]["store"] == "citation_styles"
    assert plan["cleanup_candidates"][0]["cleanup_action"] == "archive"

    verify = json.loads((cfg.migration_journals_root / "mig-run-001" / "verify.json").read_text(encoding="utf-8"))
    assert verify["status"] == "passed"
    assert not cfg.migration_lock_path.exists()
    meta = json.loads(cfg.instance_meta_path.read_text(encoding="utf-8"))
    assert meta["last_successful_migration_id"] == "mig-run-001"


def test_run_migration_store_tolerates_missing_derived_search_state_for_non_search_stores(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text(
        "def format_ref(meta, idx=None):\n    return 'legacy ' + (meta.get('title') or '')\n",
        encoding="utf-8",
    )

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    # Simulate a real legacy root where durable paper data exists but derived
    # search state has not been rebuilt yet.
    _write_papers_fixture(cfg.papers_dir)

    result = run_migration_store(cfg, store="citation_styles", migration_id="mig-run-derived-001", confirm=True)

    assert result["status"] == "passed"
    assert result["store"] == "citation_styles"
    assert result["verify_status"] == "passed_with_warnings"

    verify = json.loads(
        (cfg.migration_journals_root / "mig-run-derived-001" / "verify.json").read_text(encoding="utf-8")
    )
    assert verify["status"] == "passed_with_warnings"
    assert verify["summary"]["failed"] == 2
    assert verify["summary"]["blocking_failed"] == 0
    assert verify["summary"]["non_blocking_failed"] == 2
    failed = {check["name"] for check in verify["checks"] if check["status"] == "failed"}
    assert failed == {"index_registry_accessible", "keyword_search_accessible"}


def test_run_migration_store_copies_toolref_tree_and_cleanup_archives_legacy(tmp_path):
    from scholaraio.stores.toolref.search import toolref_show
    from scholaraio.stores.toolref.storage import toolref_list

    legacy_toolref = tmp_path / "data" / "toolref"
    tool_name = _write_toolref_fixture(legacy_toolref)

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    result = run_migration_store(cfg, store="toolref", migration_id="mig-toolref-001", confirm=True)

    target_toolref = tmp_path / "data" / "libraries" / "toolref"
    current_link = target_toolref / tool_name / "current"
    assert result["status"] == "passed"
    assert result["store"] == "toolref"
    assert result["cleanup_candidate_count"] == 1
    assert current_link.is_symlink()
    assert current_link.readlink().as_posix() == "v1"
    assert cfg.toolref_root == target_toolref.resolve()
    assert toolref_list(tool_name, cfg=cfg)[0]["is_current"] is True
    assert toolref_show(tool_name, "pw", "scf", cfg=cfg)[0]["content"] == "Self-consistent field"

    cleanup = run_migration_cleanup(cfg, migration_id="mig-toolref-001", confirm=True)

    archive_toolref = cfg.migration_journals_root / "mig-toolref-001" / "archive" / "data" / "toolref"
    assert cleanup["status"] == "completed_archived"
    assert cleanup["archived_count"] == 1
    assert not legacy_toolref.exists()
    assert (archive_toolref / tool_name / "toolref.db").exists()
    assert (archive_toolref / tool_name / "current").is_symlink()
    assert toolref_show(tool_name, "pw", "scf", cfg=cfg)[0]["title"] == "scf"


def test_run_migration_store_copies_explore_tree_and_cleanup_archives_legacy(tmp_path):
    from scholaraio.stores.explore import explore_search, list_explore_libs

    legacy_explore = tmp_path / "data" / "explore"
    explore_name = _write_explore_fixture(legacy_explore)

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    result = run_migration_store(cfg, store="explore", migration_id="mig-explore-001", confirm=True)

    target_explore = tmp_path / "data" / "libraries" / "explore"
    assert result["status"] == "passed"
    assert result["store"] == "explore"
    assert result["cleanup_candidate_count"] == 1
    assert cfg.explore_root == target_explore.resolve()
    assert list_explore_libs(cfg) == [explore_name]
    assert explore_search(explore_name, "turbulence", cfg=cfg)[0]["openalex_id"] == "W1"

    cleanup = run_migration_cleanup(cfg, migration_id="mig-explore-001", confirm=True)

    archive_explore = cfg.migration_journals_root / "mig-explore-001" / "archive" / "data" / "explore"
    assert cleanup["status"] == "completed_archived"
    assert cleanup["archived_count"] == 1
    assert not legacy_explore.exists()
    assert (archive_explore / explore_name / "papers.jsonl").exists()
    assert explore_search(explore_name, "turbulence", cfg=cfg)[0]["title"] == "Explore turbulence library"


def test_run_migration_store_copies_proceedings_tree_and_cleanup_archives_legacy(tmp_path):
    from scholaraio.services.index import search_proceedings
    from scholaraio.stores.proceedings import iter_proceedings_papers

    legacy_proceedings = tmp_path / "data" / "proceedings"
    proceeding_name = _write_proceedings_fixture(legacy_proceedings)

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    result = run_migration_store(cfg, store="proceedings", migration_id="mig-proceedings-001", confirm=True)

    target_proceedings = tmp_path / "data" / "libraries" / "proceedings"
    assert result["status"] == "passed"
    assert result["store"] == "proceedings"
    assert result["cleanup_candidate_count"] == 1
    assert cfg.proceedings_dir == target_proceedings.resolve()
    assert [paper["paper_id"] for paper in iter_proceedings_papers(cfg.proceedings_dir)] == ["proc-paper-1"]
    assert (
        search_proceedings("granular", cfg.proceedings_dir / "proceedings.db", top_k=3)[0]["paper_id"] == "proc-paper-1"
    )

    cleanup = run_migration_cleanup(cfg, migration_id="mig-proceedings-001", confirm=True)

    archive_proceedings = cfg.migration_journals_root / "mig-proceedings-001" / "archive" / "data" / "proceedings"
    assert cleanup["status"] == "completed_archived"
    assert cleanup["archived_count"] == 1
    assert not legacy_proceedings.exists()
    assert (archive_proceedings / proceeding_name / "meta.json").exists()
    assert search_proceedings("granular", cfg.proceedings_dir / "proceedings.db", top_k=3)[0]["title"] == (
        "Granular proceedings verification"
    )


def test_run_migration_store_copies_spool_tree_and_cleanup_archives_legacy(tmp_path):
    _write_spool_fixture(tmp_path / "data")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    result = run_migration_store(cfg, store="spool", migration_id="mig-spool-001", confirm=True)

    target_spool = tmp_path / "data" / "spool"
    assert result["status"] == "passed"
    assert result["store"] == "spool"
    assert result["copied_count"] == 6
    assert result["cleanup_candidate_count"] == 6
    assert cfg.inbox_dir == (target_spool / "inbox").resolve()
    assert cfg.doc_inbox_dir == (target_spool / "inbox-doc").resolve()
    assert cfg.pending_dir == (target_spool / "pending").resolve()
    assert (target_spool / "inbox" / "paper.md").read_text(encoding="utf-8") == "# Paper queued for ingest\n"
    assert (
        json.loads((target_spool / "pending" / "Needs-Review" / "pending.json").read_text(encoding="utf-8"))["issue"]
        == "no_doi"
    )

    cleanup = run_migration_cleanup(cfg, migration_id="mig-spool-001", confirm=True)

    archive_root = cfg.migration_journals_root / "mig-spool-001" / "archive" / "data"
    assert cleanup["status"] == "completed_archived"
    assert cleanup["archived_count"] == 6
    assert not (tmp_path / "data" / "inbox").exists()
    assert not (tmp_path / "data" / "pending").exists()
    assert (archive_root / "inbox" / "paper.md").exists()
    assert (archive_root / "pending" / "Needs-Review" / "pending.json").exists()
    assert (target_spool / "inbox" / "paper.md").exists()
    assert (target_spool / "pending" / "Needs-Review" / "pending.json").exists()


def test_run_migration_store_copies_papers_tree_and_cleanup_archives_legacy(tmp_path):
    from scholaraio.services.index import search
    from scholaraio.stores.papers import iter_paper_dirs

    legacy_papers = tmp_path / "data" / "papers"
    paper_name = _write_papers_fixture(legacy_papers)

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

    result = run_migration_store(cfg, store="papers", migration_id="mig-papers-001", confirm=True)

    target_papers = tmp_path / "data" / "libraries" / "papers"
    assert result["status"] == "passed"
    assert result["store"] == "papers"
    assert result["copied_count"] == 2
    assert result["cleanup_candidate_count"] == 1
    assert cfg.papers_dir == target_papers.resolve()
    assert [path.name for path in iter_paper_dirs(cfg.papers_dir)] == [paper_name]
    assert search("migration", cfg.index_db, cfg=cfg)[0]["paper_id"] == "paper-1"

    cleanup = run_migration_cleanup(cfg, migration_id="mig-papers-001", confirm=True)

    archive_papers = cfg.migration_journals_root / "mig-papers-001" / "archive" / "data" / "papers"
    assert cleanup["status"] == "completed_archived"
    assert cleanup["archived_count"] == 1
    assert not legacy_papers.exists()
    assert (archive_papers / paper_name / "meta.json").exists()
    assert search("migration", cfg.index_db, cfg=cfg)[0]["title"] == "Paper migration verification"


def test_run_migration_finalize_migrates_workspace_indexes_and_archives_all_legacy_roots(tmp_path):
    from scholaraio.stores.citation_styles import get_formatter
    from scholaraio.stores.papers import iter_paper_dirs

    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    legacy_papers = tmp_path / "data" / "papers"
    paper_name = _write_papers_fixture(legacy_papers)

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    target_styles = cfg.citation_styles_dir
    target_styles.mkdir(parents=True, exist_ok=True)
    (target_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    target_papers = cfg.papers_dir
    target_papers.mkdir(parents=True, exist_ok=True)
    _write_papers_fixture(target_papers)
    build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

    ws_dir = cfg.workspace_dir / "demo-ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "papers.json").write_text(json.dumps([{"id": "paper-1", "dir_name": paper_name}]), encoding="utf-8")

    legacy_translation = tmp_path / "workspace" / "translation-ws" / paper_name
    legacy_translation.mkdir(parents=True, exist_ok=True)
    (legacy_translation / "paper_zh.md").write_text("legacy translation\n", encoding="utf-8")

    legacy_figures = tmp_path / "workspace" / "figures"
    legacy_figures.mkdir(parents=True, exist_ok=True)
    (legacy_figures / "legacy.svg").write_text("<svg/>", encoding="utf-8")

    legacy_output = tmp_path / "workspace" / "output.docx"
    legacy_output.parent.mkdir(parents=True, exist_ok=True)
    legacy_output.write_text("legacy docx placeholder", encoding="utf-8")

    result = run_migration_finalize(cfg, migration_id="mig-finalize-001", confirm=True)

    assert result["status"] == "completed"
    assert result["workspace_migration"]["status"] == "passed"
    assert result["workspace_output_migration"]["status"] == "copied"
    assert result["cleanup"]["status"] == "completed_archived"
    assert result["cleanup"]["candidate_count"] == 6
    assert result["verify_before_cleanup"]["status"] == "passed_with_warnings"
    assert result["verify_after_cleanup"]["status"] == "passed"
    meta = ensure_instance_metadata(cfg)
    assert meta["layout_state"] == "normal"
    assert meta["layout_version"] == 1
    assert meta["last_successful_migration_id"] == "mig-finalize-001"

    assert not legacy_styles.exists()
    assert not legacy_papers.exists()
    assert not (ws_dir / "papers.json").exists()
    assert not (tmp_path / "workspace" / "translation-ws").exists()
    assert not (tmp_path / "workspace" / "figures").exists()
    assert not legacy_output.exists()
    assert (ws_dir / "refs" / "papers.json").exists()
    assert (cfg.translation_bundle_root / paper_name / "paper_zh.md").exists()
    assert (cfg.workspace_figures_dir / "legacy.svg").exists()
    assert (cfg.workspace_docx_output_path.parent / "output.docx").exists()
    assert get_formatter("custom", cfg)({}, None) == "legacy"
    assert [path.name for path in iter_paper_dirs(cfg.papers_dir)] == [paper_name]

    archive_root = cfg.migration_journals_root / "mig-finalize-001" / "archive"
    assert (archive_root / "data" / "citation_styles" / "custom.py").exists()
    assert (archive_root / "data" / "papers" / paper_name / "meta.json").exists()
    assert (archive_root / "workspace" / "demo-ws" / "papers.json").exists()
    assert (archive_root / "workspace" / "translation-ws" / paper_name / "paper_zh.md").exists()
    assert (archive_root / "workspace" / "figures" / "legacy.svg").exists()
    assert (archive_root / "workspace" / "output.docx").exists()


def test_run_migration_finalize_blocks_when_fresh_layout_targets_are_missing(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    with pytest.raises(RuntimeError, match="missing durable target data"):
        run_migration_finalize(cfg, migration_id="mig-finalize-blocked-001", confirm=True)


def test_run_migration_finalize_blocks_plan_blockers_before_metadata_update(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()
    meta = ensure_instance_metadata(cfg)
    meta["layout_version"] = 999
    write_instance_metadata(cfg, meta)

    with pytest.raises(RuntimeError, match="migrate finalize blocked: unsupported_future_layout"):
        run_migration_finalize(cfg, migration_id="mig-finalize-plan-blocked-001", confirm=True)

    stored = ensure_instance_metadata(cfg)
    assert stored["layout_version"] == 999
    assert stored["layout_state"] == "legacy_implicit"
    assert describe_migration_lock(cfg)["status"] == "absent"


def test_run_migration_upgrade_runs_store_migrations_then_finalize(tmp_path):
    from scholaraio.stores.citation_styles import get_formatter
    from scholaraio.stores.papers import iter_paper_dirs

    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    legacy_papers = tmp_path / "data" / "papers"
    paper_name = _write_papers_fixture(legacy_papers)

    legacy_inbox = tmp_path / "data" / "inbox"
    legacy_inbox.mkdir(parents=True, exist_ok=True)
    (legacy_inbox / "queued.pdf").write_text("pdf placeholder", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    ws_dir = cfg.workspace_dir / "demo-ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "papers.json").write_text(json.dumps([{"id": "paper-1", "dir_name": paper_name}]), encoding="utf-8")

    result = run_migration_upgrade(cfg, migration_id="mig-upgrade-001", confirm=True)

    assert result["status"] == "completed"
    assert [item["store"] for item in result["store_runs"]] == ["workspace", "citation_styles", "spool", "papers"]
    assert result["finalize"]["status"] == "completed"

    meta = ensure_instance_metadata(cfg)
    assert meta["layout_state"] == "normal"
    assert meta["layout_version"] == 1
    assert meta["last_successful_migration_id"] == "mig-upgrade-001"

    assert not legacy_styles.exists()
    assert not legacy_papers.exists()
    assert not legacy_inbox.exists()
    assert not (ws_dir / "papers.json").exists()
    assert (ws_dir / "refs" / "papers.json").exists()
    assert get_formatter("custom", cfg)({}, None) == "legacy"
    assert [path.name for path in iter_paper_dirs(cfg.papers_dir)] == [paper_name]
    assert (cfg.inbox_dir / "queued.pdf").exists()

    archive_root = cfg.migration_journals_root / "mig-upgrade-001" / "archive"
    assert (archive_root / "data" / "citation_styles" / "custom.py").exists()
    assert (archive_root / "data" / "papers" / paper_name / "meta.json").exists()
    assert (archive_root / "data" / "inbox" / "queued.pdf").exists()
    assert (archive_root / "workspace" / "demo-ws" / "papers.json").exists()


def test_run_migration_upgrade_requires_confirm(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    with pytest.raises(RuntimeError, match="migrate upgrade requires --confirm"):
        run_migration_upgrade(cfg, migration_id="mig-upgrade-confirm", confirm=False)


def test_run_migration_upgrade_archives_empty_legacy_roots(tmp_path):
    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    empty_legacy_roots = [
        tmp_path / "data" / "papers",
        tmp_path / "data" / "explore",
        tmp_path / "data" / "proceedings",
        tmp_path / "data" / "inbox-doc",
    ]
    for path in empty_legacy_roots:
        path.mkdir(parents=True, exist_ok=True)

    result = run_migration_upgrade(cfg, migration_id="mig-upgrade-empty-roots", confirm=True)

    assert result["status"] == "completed"
    assert result["store_runs"] == []
    for path in empty_legacy_roots:
        assert not path.exists()

    archive_root = cfg.migration_journals_root / "mig-upgrade-empty-roots" / "archive"
    assert (archive_root / "data" / "papers").is_dir()
    assert (archive_root / "data" / "explore").is_dir()
    assert (archive_root / "data" / "proceedings").is_dir()
    assert (archive_root / "data" / "inbox-doc").is_dir()


def test_run_migration_store_blocks_conflicting_citation_style_targets(tmp_path):
    legacy_styles = tmp_path / "data" / "citation_styles"
    legacy_styles.mkdir(parents=True, exist_ok=True)
    (legacy_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8")

    target_styles = tmp_path / "data" / "libraries" / "citation_styles"
    target_styles.mkdir(parents=True, exist_ok=True)
    (target_styles / "custom.py").write_text("def format_ref(meta, idx=None):\n    return 'target'\n", encoding="utf-8")

    cfg = _build_config({}, tmp_path)
    cfg.ensure_dirs()

    with pytest.raises(RuntimeError, match="conflicting citation style target"):
        run_migration_store(cfg, store="citation_styles", migration_id="mig-run-001", confirm=True)

    assert (target_styles / "custom.py").read_text(encoding="utf-8").endswith("return 'target'\n")
