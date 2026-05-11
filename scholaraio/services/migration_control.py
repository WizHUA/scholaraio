"""Migration control-plane helpers for runtime-layout upgrades."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import uuid
from datetime import datetime, timezone
from filecmp import cmp as filecmp
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from scholaraio import __version__

if TYPE_CHECKING:
    from scholaraio.core.config import Config


INSTANCE_META_VERSION = 1
LEGACY_LAYOUT_VERSION = 0
FRESH_LAYOUT_VERSION = 1
SUPPORTED_LAYOUT_VERSION = FRESH_LAYOUT_VERSION
LEGACY_LAYOUT_STATE = "legacy_implicit"
SPOOL_QUEUE_SPECS = (
    ("inbox", "inbox", "inbox"),
    ("inbox-thesis", "inbox-thesis", "inbox-thesis"),
    ("inbox-patent", "inbox-patent", "inbox-patent"),
    ("inbox-doc", "inbox-doc", "inbox-doc"),
    ("inbox-proceedings", "inbox-proceedings", "inbox-proceedings"),
    ("pending", "pending", "pending"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _resolve_migration_lock_path(cfg: Config) -> Path:
    path = getattr(cfg, "migration_lock_path", None)
    if path is not None:
        return Path(path)

    instance_meta_path = getattr(cfg, "instance_meta_path", None)
    if instance_meta_path is None:
        msg = "cfg must provide migration_lock_path or instance_meta_path"
        raise AttributeError(msg)
    return Path(instance_meta_path).with_name("migration.lock")


def _resolve_journal_root(cfg: Config) -> Path:
    path = getattr(cfg, "migration_journals_root", None)
    if path is not None:
        return Path(path)

    instance_meta_path = getattr(cfg, "instance_meta_path", None)
    if instance_meta_path is None:
        msg = "cfg must provide migration_journals_root or instance_meta_path"
        raise AttributeError(msg)
    return Path(instance_meta_path).with_name("migrations")


def _journal_activity_key(path: Path) -> tuple[float, str]:
    """Return a stable sort key reflecting the latest activity inside one journal."""
    latest_mtime = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            latest_mtime = max(latest_mtime, child.stat().st_mtime)
        except FileNotFoundError:
            # Ignore files that disappear during a concurrent cleanup/archive.
            continue
    return (latest_mtime, path.name)


def list_migration_journals(cfg: Config) -> list[Path]:
    """Return known journal directories in activity order."""
    root = _resolve_journal_root(cfg)
    if not root.exists():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=_journal_activity_key)


def resolve_migration_journal(cfg: Config, migration_id: str | None = None) -> Path | None:
    """Resolve one journal directory by id, or return the latest one when omitted."""
    if migration_id:
        journal_dir = _resolve_journal_root(cfg) / migration_id
        if journal_dir.is_dir():
            return journal_dir
        return None

    journals = list_migration_journals(cfg)
    if not journals:
        return None
    return journals[-1]


def read_instance_metadata(cfg: Config) -> dict[str, Any] | None:
    """Return parsed instance metadata when present."""
    if not cfg.instance_meta_path.exists():
        return None
    return json.loads(cfg.instance_meta_path.read_text(encoding="utf-8"))


def write_instance_metadata(cfg: Config, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist instance metadata and return the stored payload."""
    _write_json(cfg.instance_meta_path, payload)
    return payload


def ensure_instance_metadata(cfg: Config) -> dict[str, Any]:
    """Create the minimal control-plane instance metadata when missing."""
    existing = read_instance_metadata(cfg)
    if existing is not None:
        return existing

    payload = {
        "instance_meta_version": INSTANCE_META_VERSION,
        "layout_version": LEGACY_LAYOUT_VERSION,
        "layout_state": LEGACY_LAYOUT_STATE,
        "writer_version": __version__,
        "instance_id": str(uuid.uuid4()),
        "updated_at": _now_iso(),
        "last_successful_migration_id": None,
    }
    return write_instance_metadata(cfg, payload)


def mark_instance_layout_state(cfg: Config, new_state: str) -> dict[str, Any]:
    """Update the instance layout state in-place."""
    payload = ensure_instance_metadata(cfg)
    payload["layout_state"] = new_state
    payload["updated_at"] = _now_iso()
    return write_instance_metadata(cfg, payload)


def layout_version_is_supported(layout_version: Any) -> bool:
    """Return whether the stored layout version is supported by this program."""
    if isinstance(layout_version, int):
        return layout_version <= SUPPORTED_LAYOUT_VERSION
    if isinstance(layout_version, str) and layout_version.isdigit():
        return int(layout_version) <= SUPPORTED_LAYOUT_VERSION
    return False


def read_migration_lock(cfg: Config) -> dict[str, Any] | None:
    """Return parsed migration lock payload when present."""
    path = _resolve_migration_lock_path(cfg)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_migration_lock(
    cfg: Config,
    migration_id: str,
    *,
    pid: int | None = None,
    hostname: str | None = None,
    mode: str = "run",
) -> dict[str, Any]:
    """Persist a migration lock payload for offline migration flows."""
    payload = {
        "migration_id": migration_id,
        "pid": os.getpid() if pid is None else pid,
        "hostname": socket.gethostname() if hostname is None else hostname,
        "started_at": _now_iso(),
        "writer_version": __version__,
        "mode": mode,
    }
    _write_json(_resolve_migration_lock_path(cfg), payload)
    return payload


def _pid_is_alive(pid: int) -> bool:
    """Best-effort process liveness check for same-host lock inspection."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def describe_migration_lock(cfg: Config) -> dict[str, Any]:
    """Describe the current migration lock and whether it appears stale."""
    payload = read_migration_lock(cfg)
    if payload is None:
        return {"status": "absent", "lock": None, "stale": False}

    stale = False
    hostname = str(payload.get("hostname") or "")
    pid = payload.get("pid")
    if hostname and hostname == socket.gethostname() and isinstance(pid, int):
        stale = not _pid_is_alive(pid)

    return {
        "status": "stale" if stale else "active",
        "lock": payload,
        "stale": stale,
    }


def clear_migration_lock(cfg: Config) -> bool:
    """Remove the migration lock when present."""
    path = _resolve_migration_lock_path(cfg)
    if not path.exists():
        return False
    path.unlink()
    return True


def ensure_migration_journal(
    cfg: Config,
    migration_id: str,
    *,
    plan: dict[str, Any] | None = None,
) -> Path:
    """Create the minimal journal scaffold for one migration run."""
    journal_dir = _resolve_journal_root(cfg) / migration_id
    journal_dir.mkdir(parents=True, exist_ok=True)

    if not (journal_dir / "plan.json").exists():
        plan_payload = {
            "migration_id": migration_id,
            "plan_state": "draft",
            "created_at": _now_iso(),
            "writer_version": __version__,
        }
        if plan:
            plan_payload.update(plan)
        _write_json(journal_dir / "plan.json", plan_payload)

    steps_path = journal_dir / "steps.jsonl"
    if not steps_path.exists():
        steps_path.write_text("", encoding="utf-8")

    if not (journal_dir / "verify.json").exists():
        _write_json(
            journal_dir / "verify.json",
            {
                "migration_id": migration_id,
                "status": "not_run",
                "checks": [],
                "updated_at": _now_iso(),
            },
        )

    if not (journal_dir / "rollback.json").exists():
        _write_json(
            journal_dir / "rollback.json",
            {
                "migration_id": migration_id,
                "status": "not_planned",
                "updated_at": _now_iso(),
            },
        )

    summary_path = journal_dir / "summary.md"
    if not summary_path.exists():
        summary_path.write_text(
            "\n".join(
                [
                    "# Migration Summary",
                    "",
                    f"- migration_id: {migration_id}",
                    "- status: draft",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return journal_dir


def append_migration_journal_step(
    cfg: Config,
    migration_id: str,
    *,
    step_name: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> Path:
    """Append one structured entry to the journal step log."""
    journal_dir = ensure_migration_journal(cfg, migration_id)
    payload: dict[str, Any] = {
        "timestamp": _now_iso(),
        "step": step_name,
        "status": status,
        "message": message,
    }
    if details is not None:
        payload["details"] = details

    steps_path = journal_dir / "steps.jsonl"
    with steps_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return steps_path


def refresh_migration_summary(cfg: Config, migration_id: str) -> Path:
    """Refresh the human-readable summary.md from current journal state."""
    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        raise FileNotFoundError(f"migration journal not found: {migration_id}")

    plan = (
        json.loads((journal_dir / "plan.json").read_text(encoding="utf-8"))
        if (journal_dir / "plan.json").exists()
        else {}
    )
    verify = (
        json.loads((journal_dir / "verify.json").read_text(encoding="utf-8"))
        if (journal_dir / "verify.json").exists()
        else {}
    )
    cleanup_step = read_latest_cleanup_step(cfg, migration_id)

    lines = [
        "# Migration Summary",
        "",
        f"- migration_id: {migration_id}",
        f"- plan_state: {plan.get('plan_state', 'unknown')}",
    ]

    blockers = plan.get("blockers")
    if isinstance(blockers, list):
        lines.append(f"- blockers: {len(blockers)}")
    planned_cleanup_candidates = plan.get("planned_cleanup_candidates")
    if isinstance(planned_cleanup_candidates, list):
        lines.append(f"- planned_cleanup_candidates: {len(planned_cleanup_candidates)}")

    if verify:
        verify_status = verify.get("status", "unknown")
        lines.append(f"- verify_status: {verify_status}")
        summary = verify.get("summary") or {}
        total = summary.get("total")
        passed = summary.get("passed")
        if total is not None and passed is not None:
            lines.append(f"- checks_passed: {passed}/{total}")
        follow_up = verify.get("follow_up")
        if follow_up:
            lines.append(f"- follow_up: {follow_up}")

    if cleanup_step is not None:
        details = cleanup_step.get("details") or {}
        cleanup_status = details.get("cleanup_status") or cleanup_step.get("step")
        lines.append(f"- cleanup_status: {cleanup_status}")
        candidate_count = details.get("candidate_count")
        if candidate_count is not None:
            lines.append(f"- cleanup_candidates: {candidate_count}")
        removed_count = details.get("removed_count")
        if removed_count is not None:
            lines.append(f"- cleanup_removed: {removed_count}")
        archived_count = details.get("archived_count")
        if archived_count is not None:
            lines.append(f"- cleanup_archived: {archived_count}")

    lines.append("")
    summary_path = journal_dir / "summary.md"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def read_migration_verify(cfg: Config, migration_id: str) -> dict[str, Any] | None:
    """Read verify.json for one journal when present."""
    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        return None

    path = journal_dir / "verify.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_migration_steps(cfg: Config, migration_id: str) -> list[dict[str, Any]]:
    """Read structured journal steps for one migration."""
    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        return []

    path = journal_dir / "steps.jsonl"
    if not path.exists():
        return []

    steps: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        steps.append(json.loads(line))
    return steps


def read_latest_cleanup_step(cfg: Config, migration_id: str) -> dict[str, Any] | None:
    """Return the latest cleanup-related journal step when present."""
    for step in reversed(read_migration_steps(cfg, migration_id)):
        if step.get("step") in {"cleanup_preview", "cleanup"}:
            return step
    return None


def _path_relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"migration cleanup path is outside runtime root: {path}") from exc


def _spool_store_dirs(cfg: Config) -> list[dict[str, Path | str]]:
    runtime_root = cfg.control_root.parent
    data_root = runtime_root / "data"
    return [
        {
            "name": name,
            "source": (data_root / legacy_name).resolve(),
            "target": (data_root / "spool" / target_name).resolve(),
        }
        for name, legacy_name, target_name in SPOOL_QUEUE_SPECS
    ]


def _legacy_workspace_output_roots(cfg: Config) -> list[dict[str, Any]]:
    workspace_root = (cfg.control_root.parent / "workspace").resolve()
    roots: list[dict[str, Any]] = []

    translation_legacy = (workspace_root / "translation-ws").resolve()
    translation_target = cfg.translation_bundle_root.resolve()
    if translation_legacy != translation_target and translation_legacy.exists():
        roots.append(
            {
                "name": "translation_bundles",
                "kind": "dir",
                "source": translation_legacy,
                "target": translation_target,
            }
        )

    figures_legacy = (workspace_root / "figures").resolve()
    figures_target = cfg.workspace_figures_dir.resolve()
    if figures_legacy != figures_target and figures_legacy.exists():
        roots.append(
            {
                "name": "figures",
                "kind": "dir",
                "source": figures_legacy,
                "target": figures_target,
            }
        )

    output_target_root = cfg.workspace_docx_output_path.parent.resolve()
    for legacy_output in sorted(workspace_root.glob("output.*")):
        if not legacy_output.is_file():
            continue
        target_file = (output_target_root / legacy_output.name).resolve()
        if legacy_output.resolve() == target_file:
            continue
        roots.append(
            {
                "name": f"output:{legacy_output.name}",
                "kind": "file",
                "source": legacy_output.resolve(),
                "target": target_file,
            }
        )

    return roots


def _migrate_legacy_workspace_outputs(cfg: Config) -> dict[str, Any]:
    roots = _legacy_workspace_output_roots(cfg)
    if not roots:
        return {
            "status": "not_needed",
            "copied_count": 0,
            "skipped_count": 0,
            "cleanup_candidate_count": 0,
            "cleanup_candidates": [],
            "roots": [],
        }

    copied_count = 0
    skipped_count = 0
    conflict_count = 0
    cleanup_candidates: list[dict[str, Any]] = []
    migrated_roots: list[dict[str, Any]] = []

    for item in roots:
        source = Path(item["source"])
        target = Path(item["target"])
        kind = str(item["kind"])

        if kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            plan = _store_copy_plan(source, target)
            _copy_store_without_overwrite(source, target, plan)
            root_copied = len(plan["to_copy"]) + len(plan["to_copy_symlinks"])
            root_skipped = len(plan["skipped"]) + len(plan["skipped_symlinks"])
            root_conflicts = len(plan["conflicts"])
            item_count = plan["source_item_count"]
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or not filecmp(source, target, shallow=False):
                    root_copied = 0
                    root_skipped = 0
                    root_conflicts = 1
                else:
                    root_copied = 0
                    root_skipped = 1
                    root_conflicts = 0
            else:
                shutil.copy2(source, target)
                root_copied = 1
                root_skipped = 0
                root_conflicts = 0
            item_count = 1

        copied_count += root_copied
        skipped_count += root_skipped
        conflict_count += root_conflicts
        migrated_roots.append(
            {
                "name": item["name"],
                "kind": kind,
                "source_path": str(source),
                "target_path": str(target),
                "copied_count": root_copied,
                "skipped_count": root_skipped,
                "conflict_count": root_conflicts,
                "source_item_count": item_count,
            }
        )
        cleanup_candidates.append(
            {
                "store": "workspace_system_outputs",
                "legacy_path": str(source),
                "target_path": str(target),
                "cleanup_action": "archive",
                "migration_phase": "A10",
                "item_count": item_count,
                "output_name": item["name"],
            }
        )

    return {
        "status": "copied",
        "copied_count": copied_count,
        "skipped_count": skipped_count,
        "conflict_count": conflict_count,
        "cleanup_candidate_count": len(cleanup_candidates),
        "cleanup_candidates": cleanup_candidates,
        "roots": migrated_roots,
    }


def _cleanup_archive_plan(
    cfg: Config,
    migration_id: str,
    cleanup_candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    runtime_root = cfg.control_root.parent.resolve()
    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        raise FileNotFoundError(f"migration journal not found: {migration_id}")
    archive_root = (journal_dir / "archive").resolve()

    archives: list[dict[str, str]] = []
    skipped_missing: list[dict[str, str]] = []
    for candidate in cleanup_candidates:
        if candidate.get("cleanup_action") != "archive":
            raise RuntimeError(f"unsupported cleanup action: {candidate.get('cleanup_action')}")

        source_text = candidate.get("legacy_path") or candidate.get("source_path")
        if not source_text:
            raise RuntimeError("cleanup candidate is missing legacy_path")

        source = Path(source_text).resolve()
        rel_source = _path_relative_to(source, runtime_root)

        target_text = candidate.get("target_path")
        if target_text:
            target = Path(target_text).resolve()
            _path_relative_to(target, runtime_root)
            if not target.exists():
                raise RuntimeError(f"cleanup target is missing: {target}")

        archive_path = (archive_root / rel_source).resolve()
        _path_relative_to(archive_path, archive_root)

        if not source.exists():
            skipped_missing.append({"source_path": str(source), "archive_path": str(archive_path)})
            continue
        if archive_path.exists():
            raise RuntimeError(f"cleanup archive target already exists: {archive_path}")

        archives.append({"source_path": str(source), "archive_path": str(archive_path)})

    return archives, skipped_missing


def _archive_cleanup_candidates(archives: list[dict[str, str]]) -> None:
    for item in archives:
        source = Path(item["source_path"])
        archive_path = Path(item["archive_path"])
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(archive_path))


NON_BLOCKING_DERIVED_STATE_CHECKS = {
    "index_registry_accessible",
    "keyword_search_accessible",
}


def run_migration_verification(
    cfg: Config,
    migration_id: str,
    *,
    non_blocking_checks: set[str] | None = None,
) -> dict[str, Any]:
    """Run the component-aware migration verification contract and refresh verify.json."""
    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        raise FileNotFoundError(f"migration journal not found: {migration_id}")
    non_blocking = set(non_blocking_checks or set())

    checks: list[dict[str, Any]] = []

    def _record_check(name: str, fn) -> None:
        blocking = name not in non_blocking
        try:
            details = fn()
        except Exception as exc:
            checks.append(
                {
                    "name": name,
                    "status": "failed",
                    "blocking": blocking,
                    "details": {"error": str(exc)},
                }
            )
            return

        checks.append(
            {
                "name": name,
                "status": "passed",
                "blocking": blocking,
                "details": details or {},
            }
        )

    def _instance_metadata_check() -> dict[str, Any]:
        meta = read_instance_metadata(cfg)
        if meta is None:
            raise RuntimeError("instance metadata missing")
        return {"layout_state": meta.get("layout_state"), "layout_version": meta.get("layout_version")}

    def _control_root_check() -> dict[str, Any]:
        if not cfg.control_root.is_dir():
            raise RuntimeError(f"control root missing: {cfg.control_root}")
        return {"path": str(cfg.control_root)}

    def _papers_dir_check() -> dict[str, Any]:
        if not cfg.papers_dir.is_dir():
            raise RuntimeError(f"papers dir missing: {cfg.papers_dir}")
        count = sum(1 for path in cfg.papers_dir.iterdir() if path.is_dir())
        return {"path": str(cfg.papers_dir), "paper_dir_count": count}

    def _workspace_root_check() -> dict[str, Any]:
        if not cfg.workspace_dir.is_dir():
            raise RuntimeError(f"workspace root missing: {cfg.workspace_dir}")
        count = sum(1 for path in cfg.workspace_dir.iterdir() if path.is_dir())
        return {"path": str(cfg.workspace_dir), "workspace_count": count}

    def _journal_dir_check() -> dict[str, Any]:
        if not journal_dir.is_dir():
            raise RuntimeError(f"journal missing: {journal_dir}")
        return {"path": str(journal_dir)}

    def _sample_query(*texts: str | None) -> str | None:
        title = texts[0] if texts else None
        if title:
            title_tokens: list[str] = []
            for token in re.findall(r"[\w-]{2,}", title, flags=re.UNICODE):
                token = token.strip("_-")
                if len(token) >= 2 and not token.isdigit():
                    title_tokens.append(token)
            if title_tokens:
                return " ".join(title_tokens[:8])
        for text in texts:
            if not text:
                continue
            for token in re.findall(r"[\w-]{2,}", text, flags=re.UNICODE):
                token = token.strip("_-")
                if len(token) >= 2 and not token.isdigit():
                    return token
        return None

    def _papers_inventory_check() -> dict[str, Any]:
        from scholaraio.stores.papers import iter_paper_dirs

        paper_dirs = list(iter_paper_dirs(cfg.papers_dir))
        return {"path": str(cfg.papers_dir), "paper_dir_count": len(paper_dirs)}

    def _workspace_inventory_check() -> dict[str, Any]:
        workspace_names: list[str] = []
        if cfg.workspace_dir.is_dir():
            for child in sorted(cfg.workspace_dir.iterdir()):
                if not child.is_dir() or child.name == "_system":
                    continue
                workspace_names.append(child.name)
        return {
            "path": str(cfg.workspace_dir),
            "workspace_count": len(workspace_names),
            "workspace_names": workspace_names[:10],
        }

    def _workspace_index_layout_check() -> dict[str, Any]:
        from scholaraio.projects.workspace import has_legacy_paper_index, has_paper_index

        legacy_names: list[str] = []
        current_names: list[str] = []
        if cfg.workspace_dir.is_dir():
            for child in sorted(cfg.workspace_dir.iterdir()):
                if not child.is_dir() or child.name == "_system":
                    continue
                if has_legacy_paper_index(child):
                    legacy_names.append(child.name)
                if has_paper_index(child):
                    current_names.append(child.name)
        if legacy_names:
            raise RuntimeError(f"legacy workspace paper indexes still present: {', '.join(legacy_names[:10])}")
        return {
            "path": str(cfg.workspace_dir),
            "current_workspace_index_count": len(current_names),
            "workspace_names": current_names[:10],
        }

    def _index_registry_check() -> dict[str, Any]:
        from scholaraio.services.index import lookup_paper
        from scholaraio.stores.papers import iter_paper_dirs

        paper_dirs = list(iter_paper_dirs(cfg.papers_dir))
        db_exists = cfg.index_db.exists()
        if paper_dirs and not db_exists:
            raise RuntimeError(f"index db missing while papers exist: {cfg.index_db}")

        sample_ref = paper_dirs[0].name if paper_dirs else None
        sample_hit = None
        if sample_ref and db_exists:
            sample_hit = lookup_paper(cfg.index_db, sample_ref) is not None
            if not sample_hit:
                raise RuntimeError(f"papers_registry lookup failed for {sample_ref}")
        return {
            "path": str(cfg.index_db),
            "db_exists": db_exists,
            "sample_ref": sample_ref,
            "sample_hit": sample_hit,
        }

    def _keyword_search_check() -> dict[str, Any]:
        from scholaraio.services.index import search
        from scholaraio.stores.papers import iter_paper_dirs, read_meta

        paper_dirs = list(iter_paper_dirs(cfg.papers_dir))
        db_exists = cfg.index_db.exists()
        if not paper_dirs:
            return {"path": str(cfg.index_db), "db_exists": db_exists, "available": False, "reason": "no papers"}
        if not db_exists:
            raise RuntimeError(f"index db missing while papers exist: {cfg.index_db}")

        sample_dir = paper_dirs[0]
        meta = read_meta(sample_dir)
        query = _sample_query(
            meta.get("title"),
            meta.get("abstract"),
            meta.get("l3_conclusion"),
            sample_dir.name,
        )
        if not query:
            raise RuntimeError(f"could not derive keyword-search probe for {sample_dir.name}")

        results = search(query, cfg.index_db, top_k=3, cfg=cfg)
        sample_id = meta.get("id")
        sample_hit = any(row.get("paper_id") == sample_id for row in results) if sample_id else bool(results)
        if not sample_hit:
            raise RuntimeError(f"keyword search failed to find {sample_dir.name} via query {query!r}")

        return {
            "path": str(cfg.index_db),
            "query": query,
            "result_count": len(results),
            "sample_ref": sample_dir.name,
            "sample_hit": sample_hit,
        }

    def _citation_styles_check() -> dict[str, Any]:
        from scholaraio.stores.citation_styles import get_formatter, list_styles

        styles = list_styles(cfg)
        custom_styles = [style["name"] for style in styles if style.get("source") != "built-in"]
        sample_style = custom_styles[0] if custom_styles else "apa"
        formatter = get_formatter(sample_style, cfg)
        rendered = formatter(
            {
                "title": "Migration Verify Style Smoke",
                "authors": ["Doe, Jane"],
                "year": 2026,
                "journal": "Verification Journal",
            },
            1,
        )
        if not isinstance(rendered, str) or not rendered.strip():
            raise RuntimeError(f"citation style {sample_style} produced an empty reference")

        return {
            "path": str(cfg.citation_styles_dir),
            "available_style_count": len(styles),
            "custom_style_count": len(custom_styles),
            "sample_style": sample_style,
            "sample_output_preview": rendered[:80],
        }

    def _explore_inventory_check() -> dict[str, Any]:
        from scholaraio.stores.explore import list_explore_libs

        libs = list_explore_libs(cfg)
        return {
            "path": str(cfg.explore_root),
            "explore_lib_count": len(libs),
            "explore_libs": libs[:10],
        }

    def _explore_search_check() -> dict[str, Any]:
        from scholaraio.stores.explore import explore_search, iter_papers, list_explore_libs

        libs = list_explore_libs(cfg)
        if not libs:
            return {
                "path": str(cfg.explore_root),
                "available": False,
                "reason": "no explore libraries",
            }

        name = libs[0]
        try:
            sample = next(iter_papers(name, cfg))
        except StopIteration as exc:
            raise RuntimeError(f"explore library {name} has no papers") from exc

        query = _sample_query(sample.get("title"), sample.get("abstract"), sample.get("openalex_id"))
        if not query:
            raise RuntimeError(f"could not derive explore-search probe for {name}")

        results = explore_search(name, query, top_k=3, cfg=cfg)
        sample_ref = sample.get("doi") or sample.get("openalex_id")
        sample_hit = any((row.get("doi") or row.get("openalex_id")) == sample_ref for row in results)
        if not sample_hit:
            raise RuntimeError(f"explore search failed to find {sample_ref or name} via query {query!r}")

        return {
            "path": str(cfg.explore_root / name),
            "library": name,
            "query": query,
            "result_count": len(results),
            "sample_ref": sample_ref,
            "sample_hit": sample_hit,
        }

    def _toolref_inventory_check() -> dict[str, Any]:
        from scholaraio.stores.toolref.storage import toolref_list

        records = toolref_list(cfg=cfg)
        return {
            "path": str(cfg.toolref_root),
            "version_count": len(records),
            "tools": sorted({record["tool"] for record in records})[:10],
        }

    def _toolref_current_version_check() -> dict[str, Any]:
        from scholaraio.stores.toolref.paths import _current_link, _db_path
        from scholaraio.stores.toolref.search import toolref_show
        from scholaraio.stores.toolref.storage import toolref_list

        records = toolref_list(cfg=cfg)
        if not records:
            return {
                "path": str(cfg.toolref_root),
                "available": False,
                "reason": "no toolref versions",
            }

        current = next((record for record in records if record.get("is_current")), None)
        if current is None:
            raise RuntimeError("toolref versions exist but no current version is selected")

        tool = str(current["tool"])
        version = str(current["version"])
        link = _current_link(tool, cfg)
        if not link.is_symlink():
            raise RuntimeError(f"current toolref link missing for {tool}")

        db_path = _db_path(tool, cfg)
        if not db_path.exists():
            raise RuntimeError(f"toolref db missing for {tool}: {db_path}")

        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                """
                SELECT page_name
                FROM toolref_pages
                WHERE tool = ? AND version = ?
                ORDER BY page_name
                LIMIT 1
                """,
                (tool, version),
            ).fetchone()
        finally:
            conn.close()

        if row is None or not row[0]:
            raise RuntimeError(f"toolref db has no pages for {tool} {version}")

        page_name = str(row[0])
        results = toolref_show(tool, *page_name.split("/"), cfg=cfg)
        sample_hit = any(record.get("page_name") == page_name for record in results)
        if not sample_hit:
            raise RuntimeError(f"toolref current-version lookup failed for {tool} {version} {page_name}")

        return {
            "path": str(db_path),
            "tool": tool,
            "current_version": version,
            "sample_page": page_name,
            "result_count": len(results),
            "sample_hit": sample_hit,
        }

    def _proceedings_search_check() -> dict[str, Any]:
        from scholaraio.services.index import search_proceedings
        from scholaraio.stores.proceedings import iter_proceedings_papers

        papers = list(iter_proceedings_papers(cfg.proceedings_dir))
        db_path = cfg.proceedings_dir / "proceedings.db"
        if not papers:
            return {
                "path": str(db_path),
                "available": False,
                "reason": "no proceedings papers",
            }
        if not db_path.exists():
            raise RuntimeError(f"proceedings db missing while proceedings papers exist: {db_path}")

        sample = papers[0]
        query = _sample_query(sample.get("title"), sample.get("abstract"), sample.get("conclusion"))
        if not query:
            raise RuntimeError(f"could not derive proceedings-search probe for {sample.get('paper_id')}")

        results = search_proceedings(query, db_path, top_k=3)
        sample_ref = sample.get("paper_id")
        sample_hit = any(row.get("paper_id") == sample_ref for row in results)
        if not sample_hit:
            raise RuntimeError(f"proceedings search failed to find {sample_ref} via query {query!r}")

        return {
            "path": str(db_path),
            "query": query,
            "result_count": len(results),
            "sample_ref": sample_ref,
            "sample_hit": sample_hit,
        }

    def _spool_roots_check() -> dict[str, Any]:
        roots = {
            "inbox": cfg.inbox_dir,
            "inbox-thesis": cfg.thesis_inbox_dir,
            "inbox-patent": cfg.patent_inbox_dir,
            "inbox-doc": cfg.doc_inbox_dir,
            "inbox-proceedings": cfg.proceedings_inbox_dir,
            "pending": cfg.pending_dir,
        }
        details: dict[str, Any] = {"root_count": len(roots), "roots": {}}
        for name, path in roots.items():
            if not path.is_dir():
                raise RuntimeError(f"spool root missing for {name}: {path}")
            details["roots"][name] = {
                "path": str(path),
                "item_count": sum(1 for _child in path.iterdir()),
            }
        return details

    def _translation_resume_inventory_check() -> dict[str, Any]:
        from scholaraio.stores.papers import iter_paper_dirs

        count = 0
        for paper_dir in iter_paper_dirs(cfg.papers_dir):
            for child in paper_dir.iterdir():
                if not child.is_dir() or not child.name.startswith(".translate_"):
                    continue
                if (child / "state.json").exists():
                    count += 1
        return {
            "papers_root": str(cfg.papers_dir),
            "resume_state_count": count,
        }

    _record_check("instance_metadata_readable", _instance_metadata_check)
    _record_check("control_root_accessible", _control_root_check)
    _record_check("papers_dir_accessible", _papers_dir_check)
    _record_check("papers_inventory", _papers_inventory_check)
    _record_check("workspace_root_accessible", _workspace_root_check)
    _record_check("workspace_index_layout", _workspace_index_layout_check)
    _record_check("workspace_inventory", _workspace_inventory_check)
    _record_check("index_registry_accessible", _index_registry_check)
    _record_check("keyword_search_accessible", _keyword_search_check)
    _record_check("citation_styles_accessible", _citation_styles_check)
    _record_check("explore_inventory", _explore_inventory_check)
    _record_check("explore_search_accessible", _explore_search_check)
    _record_check("toolref_inventory", _toolref_inventory_check)
    _record_check("toolref_current_version_accessible", _toolref_current_version_check)
    _record_check("proceedings_search_accessible", _proceedings_search_check)
    _record_check("spool_roots_accessible", _spool_roots_check)
    _record_check("translation_resume_inventory", _translation_resume_inventory_check)
    _record_check("journal_dir_present", _journal_dir_check)

    passed = sum(1 for check in checks if check["status"] == "passed")
    failed = len(checks) - passed
    blocking_failed = sum(1 for check in checks if check["status"] == "failed" and check.get("blocking", True))
    non_blocking_failed = failed - blocking_failed
    if failed == 0:
        status = "passed"
    elif blocking_failed == 0:
        status = "passed_with_warnings"
    else:
        status = "failed"
    payload = {
        "migration_id": migration_id,
        "status": status,
        "checks": checks,
        "summary": {
            "passed": passed,
            "failed": failed,
            "blocking_failed": blocking_failed,
            "non_blocking_failed": non_blocking_failed,
            "total": len(checks),
        },
        "follow_up": (
            "ready_for_cleanup_gate"
            if status == "passed"
            else "rebuild_derived_state_then_retry"
            if status == "passed_with_warnings"
            else "inspect_failed_checks"
        ),
        "updated_at": _now_iso(),
    }
    _write_json(journal_dir / "verify.json", payload)
    append_migration_journal_step(
        cfg,
        migration_id,
        step_name="verify",
        status="ok" if blocking_failed == 0 else "failed",
        message="verification completed",
        details={
            "verify_status": status,
            "failed_checks": failed,
            "blocking_failed_checks": blocking_failed,
            "non_blocking_failed_checks": non_blocking_failed,
        },
    )
    refresh_migration_summary(cfg, migration_id)
    return payload


def run_migration_plan(cfg: Config, migration_id: str | None = None) -> dict[str, Any]:
    """Build a non-executing migration plan and persist it into one journal."""
    meta = ensure_instance_metadata(cfg)
    if not migration_id:
        migration_id = datetime.now(timezone.utc).strftime("mig-plan-%Y%m%d-%H%M%S")

    def _dir_inventory(path: Path, *, count_dirs_only: bool = True) -> dict[str, Any]:
        exists = path.exists()
        is_dir = path.is_dir()
        item_count = 0
        if is_dir:
            if count_dirs_only:
                item_count = sum(1 for child in path.iterdir() if child.is_dir())
            else:
                item_count = sum(1 for _child in path.iterdir())
        return {
            "path": str(path),
            "exists": exists,
            "item_count": item_count,
        }

    def _workspace_store_inventory(path: Path) -> dict[str, Any]:
        exists = path.exists()
        is_dir = path.is_dir()
        workspace_names: list[str] = []
        ignored_dir_names: list[str] = []
        legacy_index_count = 0
        current_index_count = 0
        if is_dir:
            from scholaraio.projects.workspace import has_legacy_paper_index, has_paper_index

            ignored_roots = {"_system"}
            for output_path in (
                cfg.translation_bundle_root,
                cfg.workspace_figures_dir,
                cfg.workspace_docx_output_path.parent,
            ):
                try:
                    rel = output_path.resolve().relative_to(path.resolve())
                except ValueError:
                    continue
                if rel.parts:
                    ignored_roots.add(rel.parts[0])

            for child in sorted(path.iterdir()):
                if not child.is_dir():
                    continue
                if child.name in ignored_roots:
                    ignored_dir_names.append(child.name)
                    continue
                workspace_names.append(child.name)
                if has_legacy_paper_index(child):
                    legacy_index_count += 1
                if has_paper_index(child):
                    current_index_count += 1
        return {
            "path": str(path),
            "exists": exists,
            "item_count": len(workspace_names),
            "workspace_names": workspace_names[:10],
            "legacy_index_count": legacy_index_count,
            "current_index_count": current_index_count,
            "ignored_dir_names": ignored_dir_names[:10],
            "ignored_dir_count": len(ignored_dir_names),
        }

    libraries_root = (cfg.control_root.parent / "data" / "libraries").resolve()
    spool_root = (cfg.control_root.parent / "data" / "spool").resolve()

    def _target_path(name: str) -> Path:
        return (libraries_root / name).resolve()

    def _planned_cleanup_entry(
        *,
        store: str,
        source_path: Path,
        target_path: Path,
        phase: str,
        item_count: int,
    ) -> dict[str, Any]:
        return {
            "store": store,
            "legacy_path": str(source_path),
            "target_path": str(target_path),
            "migration_phase": phase,
            "item_count": item_count,
        }

    lock_status = describe_migration_lock(cfg)
    blockers: list[dict[str, Any]] = []
    if lock_status["status"] != "absent":
        blockers.append(
            {
                "code": "active_migration_lock",
                "detail": lock_status["status"],
            }
        )
    if not layout_version_is_supported(meta.get("layout_version")):
        blockers.append(
            {
                "code": "unsupported_future_layout",
                "layout_version": meta.get("layout_version"),
            }
        )
    if meta.get("layout_state") == "migrating":
        blockers.append({"code": "migration_in_progress"})

    from scholaraio.stores.explore import list_explore_libs
    from scholaraio.stores.proceedings import iter_proceedings_dirs, iter_proceedings_papers
    from scholaraio.stores.toolref.storage import toolref_list

    planned_cleanup_candidates: list[dict[str, Any]] = []

    legacy_papers_dir = (cfg.control_root.parent / "data" / "papers").resolve()
    papers_store = _dir_inventory(cfg.papers_dir)
    legacy_papers_inventory = _dir_inventory(legacy_papers_dir)
    papers_store.update(
        {
            "target_path": str(_target_path("papers")),
            "migration_phase": "A10",
            "migration_group": "durable_library",
            "legacy_path": str(legacy_papers_dir),
            "legacy_exists": legacy_papers_inventory["exists"],
            "legacy_item_count": legacy_papers_inventory["item_count"],
        }
    )
    if legacy_papers_inventory["exists"]:
        planned_cleanup_candidates.append(
            _planned_cleanup_entry(
                store="papers",
                source_path=legacy_papers_dir,
                target_path=_target_path("papers"),
                phase="A10",
                item_count=legacy_papers_inventory["item_count"],
            )
        )

    legacy_citation_styles_dir = _legacy_store_dir(cfg, "citation_styles")
    citation_styles_store = _dir_inventory(cfg.citation_styles_dir, count_dirs_only=False)
    legacy_citation_styles_inventory = _dir_inventory(legacy_citation_styles_dir, count_dirs_only=False)
    citation_styles_store.update(
        {
            "target_path": str(_target_path("citation_styles")),
            "migration_phase": "A7",
            "migration_group": "durable_library",
            "file_count": citation_styles_store["item_count"],
            "legacy_path": str(legacy_citation_styles_dir),
            "legacy_exists": legacy_citation_styles_inventory["exists"],
            "legacy_item_count": legacy_citation_styles_inventory["item_count"],
        }
    )
    if legacy_citation_styles_inventory["exists"]:
        planned_cleanup_candidates.append(
            _planned_cleanup_entry(
                store="citation_styles",
                source_path=legacy_citation_styles_dir,
                target_path=_target_path("citation_styles"),
                phase="A7",
                item_count=legacy_citation_styles_inventory["item_count"],
            )
        )

    legacy_toolref_root = _legacy_store_dir(cfg, "toolref")
    toolref_records = toolref_list(cfg=cfg)
    legacy_tool_dirs = (
        sorted(child.name for child in legacy_toolref_root.iterdir() if child.is_dir())
        if legacy_toolref_root.is_dir()
        else []
    )
    toolref_store = _dir_inventory(cfg.toolref_root)
    legacy_toolref_inventory = _dir_inventory(legacy_toolref_root)
    toolref_store.update(
        {
            "target_path": str(_target_path("toolref")),
            "migration_phase": "A7",
            "migration_group": "durable_library",
            "version_count": len(toolref_records) if toolref_records else legacy_toolref_inventory["item_count"],
            "tool_count": len({record["tool"] for record in toolref_records})
            if toolref_records
            else len(legacy_tool_dirs),
            "legacy_path": str(legacy_toolref_root),
            "legacy_exists": legacy_toolref_inventory["exists"],
            "legacy_item_count": legacy_toolref_inventory["item_count"],
        }
    )
    if legacy_toolref_inventory["exists"]:
        planned_cleanup_candidates.append(
            _planned_cleanup_entry(
                store="toolref",
                source_path=legacy_toolref_root,
                target_path=_target_path("toolref"),
                phase="A7",
                item_count=legacy_toolref_inventory["item_count"],
            )
        )

    legacy_explore_root = _legacy_store_dir(cfg, "explore")
    explore_libs = list_explore_libs(cfg)
    legacy_explore_libs = (
        sorted(child.name for child in legacy_explore_root.iterdir() if child.is_dir())
        if legacy_explore_root.is_dir()
        else []
    )
    explore_store = _dir_inventory(cfg.explore_root)
    legacy_explore_inventory = _dir_inventory(legacy_explore_root)
    explore_store.update(
        {
            "target_path": str(_target_path("explore")),
            "migration_phase": "A7",
            "migration_group": "durable_library",
            "library_count": len(explore_libs) if explore_libs else len(legacy_explore_libs),
            "libraries": (explore_libs or legacy_explore_libs)[:10],
            "legacy_path": str(legacy_explore_root),
            "legacy_exists": legacy_explore_inventory["exists"],
            "legacy_item_count": legacy_explore_inventory["item_count"],
        }
    )
    if legacy_explore_inventory["exists"]:
        planned_cleanup_candidates.append(
            _planned_cleanup_entry(
                store="explore",
                source_path=legacy_explore_root,
                target_path=_target_path("explore"),
                phase="A7",
                item_count=legacy_explore_inventory["item_count"],
            )
        )

    legacy_proceedings_dir = _legacy_store_dir(cfg, "proceedings")
    proceeding_dirs = list(iter_proceedings_dirs(cfg.proceedings_dir))
    proceedings_papers = list(iter_proceedings_papers(cfg.proceedings_dir))
    legacy_proceeding_dirs = (
        sorted(child for child in legacy_proceedings_dir.iterdir() if child.is_dir())
        if legacy_proceedings_dir.is_dir()
        else []
    )
    legacy_proceedings_papers = (
        [
            child
            for volume in legacy_proceeding_dirs
            if (volume / "papers").is_dir()
            for child in (volume / "papers").iterdir()
            if child.is_dir()
        ]
        if legacy_proceedings_dir.is_dir()
        else []
    )
    proceedings_store = _dir_inventory(cfg.proceedings_dir)
    legacy_proceedings_inventory = _dir_inventory(legacy_proceedings_dir)
    proceedings_store.update(
        {
            "target_path": str(_target_path("proceedings")),
            "migration_phase": "A8",
            "migration_group": "durable_library",
            "volume_count": len(proceeding_dirs) if proceeding_dirs else len(legacy_proceeding_dirs),
            "child_paper_count": len(proceedings_papers) if proceedings_papers else len(legacy_proceedings_papers),
            "legacy_path": str(legacy_proceedings_dir),
            "legacy_exists": legacy_proceedings_inventory["exists"],
            "legacy_item_count": legacy_proceedings_inventory["item_count"],
        }
    )
    if legacy_proceedings_inventory["exists"]:
        planned_cleanup_candidates.append(
            _planned_cleanup_entry(
                store="proceedings",
                source_path=legacy_proceedings_dir,
                target_path=_target_path("proceedings"),
                phase="A8",
                item_count=legacy_proceedings_inventory["item_count"],
            )
        )

    spool_roots: list[dict[str, Any]] = []
    spool_item_count = 0
    for item in _spool_store_dirs(cfg):
        name = str(item["name"])
        source_path = Path(item["source"])
        target_path = Path(item["target"])
        source_inventory = _dir_inventory(source_path, count_dirs_only=False)
        target_inventory = _dir_inventory(target_path, count_dirs_only=False)
        active_path = target_path if target_path.exists() or not source_path.exists() else source_path
        active_inventory = _dir_inventory(active_path, count_dirs_only=False)
        spool_item_count += active_inventory["item_count"]
        spool_roots.append(
            {
                "name": name,
                "legacy_path": str(source_path),
                "target_path": str(target_path),
                "active_path": str(active_path),
                "legacy_exists": source_inventory["exists"],
                "legacy_item_count": source_inventory["item_count"],
                "target_exists": target_inventory["exists"],
                "target_item_count": target_inventory["item_count"],
                "active_item_count": active_inventory["item_count"],
            }
        )
        if source_path.is_dir():
            planned_cleanup_candidates.append(
                _planned_cleanup_entry(
                    store="spool",
                    source_path=source_path,
                    target_path=target_path,
                    phase="A9",
                    item_count=source_inventory["item_count"],
                )
                | {"queue_root": name}
            )

    spool_store = {
        "path": str(spool_root),
        "exists": spool_root.exists(),
        "item_count": spool_item_count,
        "target_path": str(spool_root),
        "migration_phase": "A9",
        "migration_group": "queue_spool",
        "root_count": len(spool_roots),
        "roots": spool_roots,
    }

    stores = {
        "papers": papers_store,
        "workspace": _workspace_store_inventory(cfg.workspace_dir),
        "explore": explore_store,
        "toolref": toolref_store,
        "proceedings": proceedings_store,
        "citation_styles": citation_styles_store,
        "spool": spool_store,
    }

    workspace_store = stores["workspace"]
    if workspace_store["legacy_index_count"] > 0:
        planned_cleanup_candidates.append(
            {
                "store": "workspace",
                "legacy_path": str(cfg.workspace_dir),
                "target_path": str(cfg.workspace_dir),
                "migration_phase": "A10",
                "item_count": workspace_store["legacy_index_count"],
                "cleanup_scope": "workspace_index_layout",
            }
        )

    for output_root in _legacy_workspace_output_roots(cfg):
        source_path = Path(output_root["source"])
        target_path = Path(output_root["target"])
        if output_root["kind"] == "dir":
            item_count = _dir_inventory(source_path, count_dirs_only=False)["item_count"]
        else:
            item_count = 1
        planned_cleanup_candidates.append(
            _planned_cleanup_entry(
                store="workspace_system_outputs",
                source_path=source_path,
                target_path=target_path,
                phase="A10",
                item_count=item_count,
            )
            | {"output_name": output_root["name"]}
        )

    payload = {
        "migration_id": migration_id,
        "plan_state": "planned",
        "created_at": _now_iso(),
        "writer_version": __version__,
        "runtime_root": str(cfg.control_root.parent),
        "source_layout_version": meta.get("layout_version"),
        "source_layout_state": meta.get("layout_state"),
        "target_layout_version": FRESH_LAYOUT_VERSION,
        "target_layout_status": "finalizable_in_code",
        "stores": stores,
        "estimated_rebuilds": {
            "search_index_present": cfg.index_db.exists(),
            "topics_model_present": cfg.topics_model_dir.exists(),
            "explore_silos": stores["explore"]["item_count"],
            "planned_store_moves": len(planned_cleanup_candidates),
        },
        "blockers": blockers,
        "planned_cleanup_candidates": planned_cleanup_candidates,
        "cleanup_candidates": [],
    }

    journal_dir = ensure_migration_journal(cfg, migration_id, plan=payload)
    _write_json(journal_dir / "plan.json", payload)
    append_migration_journal_step(
        cfg,
        migration_id,
        step_name="plan",
        status="ok",
        message="plan recorded",
        details={
            "blocker_count": len(blockers),
            "paper_count": stores["papers"]["item_count"],
            "workspace_count": stores["workspace"]["item_count"],
            "planned_move_count": len(planned_cleanup_candidates),
        },
    )
    refresh_migration_summary(cfg, migration_id)
    return payload


def run_migration_cleanup(cfg: Config, migration_id: str, *, confirm: bool = False) -> dict[str, Any]:
    """Run the safe cleanup gate without deleting user data by default."""
    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        raise FileNotFoundError(f"migration journal not found: {migration_id}")
    if describe_migration_lock(cfg)["status"] != "absent":
        raise RuntimeError("migrate cleanup blocked because migration.lock already exists")
    meta = ensure_instance_metadata(cfg)
    if not layout_version_is_supported(meta.get("layout_version")):
        raise RuntimeError("migrate cleanup blocked: unsupported_future_layout")
    if meta.get("layout_state") == "migrating":
        raise RuntimeError("migrate cleanup blocked: migration_in_progress")

    verify = read_migration_verify(cfg, migration_id)
    if verify is None:
        raise RuntimeError("migrate cleanup requires a successful verification record")
    if int((verify.get("summary") or {}).get("blocking_failed", 0)) > 0:
        raise RuntimeError("migrate cleanup requires verification with zero blocking failures")
    if verify.get("status") not in {"passed", "passed_with_warnings"}:
        raise RuntimeError("migrate cleanup requires a successful verification record")

    plan_path = journal_dir / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
    _ensure_migration_plan_unblocked(plan, operation="migrate cleanup")
    cleanup_candidates = plan.get("cleanup_candidates")
    if not isinstance(cleanup_candidates, list):
        cleanup_candidates = []

    candidate_count = len(cleanup_candidates)
    removed_count = 0
    archived_count = 0
    skipped_missing_count = 0
    blocked_reason = None
    archived_items: list[dict[str, str]] = []
    skipped_missing_items: list[dict[str, str]] = []

    if not confirm:
        cleanup_status = "preview"
        step_name = "cleanup_preview"
        step_status = "ok"
        message = "cleanup preview generated"
    elif candidate_count == 0:
        cleanup_status = "completed_noop"
        step_name = "cleanup"
        step_status = "ok"
        message = "cleanup completed without removing legacy data"
    else:
        try:
            archived_items, skipped_missing_items = _cleanup_archive_plan(cfg, migration_id, cleanup_candidates)
            _archive_cleanup_candidates(archived_items)
        except (OSError, RuntimeError) as exc:
            cleanup_status = "blocked"
            step_name = "cleanup"
            step_status = "blocked"
            blocked_reason = str(exc)
            message = blocked_reason
        else:
            archived_count = len(archived_items)
            skipped_missing_count = len(skipped_missing_items)
            cleanup_status = "completed_archived"
            step_name = "cleanup"
            step_status = "ok"
            message = "cleanup archived legacy data without deleting it"

    details = {
        "cleanup_status": cleanup_status,
        "candidate_count": candidate_count,
        "removed_count": removed_count,
        "archived_count": archived_count,
        "skipped_missing_count": skipped_missing_count,
        "confirm": confirm,
    }
    if archived_items:
        details["archived_items"] = archived_items
    if skipped_missing_items:
        details["skipped_missing_items"] = skipped_missing_items
    if blocked_reason:
        details["blocked_reason"] = blocked_reason

    append_migration_journal_step(
        cfg,
        migration_id,
        step_name=step_name,
        status=step_status,
        message=message,
        details=details,
    )
    refresh_migration_summary(cfg, migration_id)

    result = {
        "migration_id": migration_id,
        "status": cleanup_status,
        "candidate_count": candidate_count,
        "removed_count": removed_count,
        "archived_count": archived_count,
        "skipped_missing_count": skipped_missing_count,
        "confirm_required": candidate_count > 0 and cleanup_status not in {"completed_archived"},
    }
    if blocked_reason:
        result["blocked_reason"] = blocked_reason
    return result


def run_migration_finalize(cfg: Config, migration_id: str | None = None, *, confirm: bool = False) -> dict[str, Any]:
    """Finalize a migrated runtime via strict verify -> cleanup -> verify orchestration."""
    if not confirm:
        raise RuntimeError("migrate finalize requires --confirm before changing runtime data")
    if describe_migration_lock(cfg)["status"] != "absent":
        raise RuntimeError("migrate finalize blocked because migration.lock already exists")
    if not migration_id:
        migration_id = datetime.now(timezone.utc).strftime("mig-finalize-%Y%m%d-%H%M%S")

    plan = run_migration_plan(cfg, migration_id=migration_id)
    _ensure_migration_plan_unblocked(plan, operation="migrate finalize")
    _ensure_finalize_targets_ready(plan)

    workspace_result: dict[str, Any] | None = None
    workspace_store = plan.get("stores", {}).get("workspace", {})
    if int(workspace_store.get("legacy_index_count", 0)) > 0:
        workspace_result = run_migration_store(cfg, store="workspace", migration_id=migration_id, confirm=True)
    workspace_output_result = _migrate_legacy_workspace_outputs(cfg)

    journal_dir = resolve_migration_journal(cfg, migration_id)
    if journal_dir is None:
        raise FileNotFoundError(f"migration journal not found: {migration_id}")

    plan_payload = _read_plan_payload(journal_dir)
    plan_cleanup_candidates = _legacy_cleanup_candidates_from_plan(plan)
    plan_cleanup_candidates = _merge_cleanup_candidates(
        plan_cleanup_candidates,
        workspace_output_result.get("cleanup_candidates"),
    )
    merged_cleanup_candidates = _merge_cleanup_candidates(
        plan_payload.get("cleanup_candidates"), plan_cleanup_candidates
    )
    plan_payload["cleanup_candidates"] = merged_cleanup_candidates
    if workspace_output_result.get("status") != "not_needed":
        plan_payload["workspace_system_outputs"] = {
            "status": workspace_output_result.get("status"),
            "copied_count": workspace_output_result.get("copied_count", 0),
            "skipped_count": workspace_output_result.get("skipped_count", 0),
            "conflict_count": workspace_output_result.get("conflict_count", 0),
            "cleanup_candidate_count": workspace_output_result.get("cleanup_candidate_count", 0),
            "roots": workspace_output_result.get("roots", []),
            "updated_at": _now_iso(),
        }
    _write_plan_payload(journal_dir, plan_payload)

    verify_before_cleanup = run_migration_verification(
        cfg,
        migration_id,
        non_blocking_checks={"workspace_index_layout"},
    )
    if verify_before_cleanup.get("status") not in {"passed", "passed_with_warnings"}:
        failed_checks = [
            check["name"]
            for check in verify_before_cleanup.get("checks", [])
            if check.get("status") != "passed" and check.get("blocking", True)
        ]
        raise RuntimeError("migrate finalize blocked because verification failed: " + ", ".join(failed_checks[:10]))

    cleanup = run_migration_cleanup(cfg, migration_id, confirm=True)
    if cleanup.get("status") in {"blocked"}:
        raise RuntimeError(str(cleanup.get("blocked_reason") or "migrate cleanup failed during finalize"))

    verify_after_cleanup = run_migration_verification(cfg, migration_id)
    if verify_after_cleanup.get("status") != "passed":
        failed_checks = [
            check["name"] for check in verify_after_cleanup.get("checks", []) if check.get("status") != "passed"
        ]
        raise RuntimeError("migrate finalize left verification failures: " + ", ".join(failed_checks[:10]))

    updated_meta = ensure_instance_metadata(cfg)
    updated_meta["layout_state"] = "normal"
    updated_meta["layout_version"] = FRESH_LAYOUT_VERSION
    updated_meta["last_successful_migration_id"] = migration_id
    updated_meta["updated_at"] = _now_iso()
    write_instance_metadata(cfg, updated_meta)

    append_migration_journal_step(
        cfg,
        migration_id,
        step_name="finalize",
        status="ok",
        message="finalize completed",
        details={
            "workspace_migrated": workspace_result is not None,
            "workspace_outputs_migrated": workspace_output_result.get("status") != "not_needed",
            "workspace_output_conflict_count": workspace_output_result.get("conflict_count", 0),
            "cleanup_candidate_count": cleanup.get("candidate_count", 0),
            "cleanup_status": cleanup.get("status"),
            "verify_before_cleanup": verify_before_cleanup.get("status"),
            "verify_after_cleanup": verify_after_cleanup.get("status"),
        },
    )
    refresh_migration_summary(cfg, migration_id)

    return {
        "migration_id": migration_id,
        "status": "completed",
        "workspace_migration": workspace_result
        or {
            "store": "workspace",
            "status": "not_needed",
            "copied_count": 0,
            "skipped_count": 0,
            "cleanup_candidate_count": 0,
            "verify_status": verify_before_cleanup.get("status"),
        },
        "workspace_output_migration": workspace_output_result,
        "cleanup": cleanup,
        "verify_before_cleanup": verify_before_cleanup,
        "verify_after_cleanup": verify_after_cleanup,
    }


SUPPORTED_MIGRATION_RUN_STORES = {
    "citation_styles",
    "explore",
    "papers",
    "proceedings",
    "spool",
    "toolref",
    "workspace",
}
UPGRADE_STORE_ORDER = ("workspace", "citation_styles", "toolref", "explore", "proceedings", "spool", "papers")


def _stores_needed_for_upgrade(plan: dict[str, Any]) -> list[str]:
    stores = plan.get("stores", {})
    needed: list[str] = []
    for store in UPGRADE_STORE_ORDER:
        store_info = stores.get(store, {})
        if store == "spool":
            roots = store_info.get("roots", [])
            if isinstance(roots, list) and any(
                bool(root.get("legacy_exists")) and int(root.get("legacy_item_count", 0)) > 0
                for root in roots
                if isinstance(root, dict)
            ):
                needed.append(store)
            continue
        if store == "workspace":
            if int(store_info.get("legacy_index_count", 0)) > 0:
                needed.append(store)
            continue
        if int(store_info.get("legacy_item_count", 0)) > 0:
            needed.append(store)
    return needed


def run_migration_upgrade(cfg: Config, migration_id: str | None = None, *, confirm: bool = False) -> dict[str, Any]:
    """Run supported old-layout store moves and finalization in one command."""
    if not confirm:
        raise RuntimeError("migrate upgrade requires --confirm before changing runtime data")
    if describe_migration_lock(cfg)["status"] != "absent":
        raise RuntimeError("migrate upgrade blocked because migration.lock already exists")
    if not migration_id:
        migration_id = datetime.now(timezone.utc).strftime("mig-upgrade-%Y%m%d-%H%M%S")

    initial_plan = run_migration_plan(cfg, migration_id=migration_id)
    blockers = initial_plan.get("blockers") or []
    if blockers:
        codes = ", ".join(str(blocker.get("code") or blocker) for blocker in blockers if isinstance(blocker, dict))
        raise RuntimeError(f"migrate upgrade blocked: {codes or 'unresolved blockers'}")

    store_runs: list[dict[str, Any]] = []
    for store in _stores_needed_for_upgrade(initial_plan):
        store_runs.append(run_migration_store(cfg, store=store, migration_id=migration_id, confirm=True))

    finalize = run_migration_finalize(cfg, migration_id=migration_id, confirm=True)
    append_migration_journal_step(
        cfg,
        migration_id,
        step_name="upgrade",
        status="ok",
        message="one-command migration upgrade completed",
        details={
            "store_run_count": len(store_runs),
            "stores": [item["store"] for item in store_runs],
            "finalize_status": finalize.get("status"),
        },
    )
    refresh_migration_summary(cfg, migration_id)

    return {
        "migration_id": migration_id,
        "status": "completed",
        "source_layout_version": initial_plan.get("source_layout_version"),
        "target_layout_version": FRESH_LAYOUT_VERSION,
        "store_runs": store_runs,
        "finalize": finalize,
    }


def _legacy_store_dir(cfg: Config, store: str) -> Path:
    if store == "papers":
        return (cfg.control_root.parent / "data" / "papers").resolve()
    if store == "citation_styles":
        return (cfg.control_root.parent / "data" / "citation_styles").resolve()
    if store == "toolref":
        return (cfg.control_root.parent / "data" / "toolref").resolve()
    if store == "explore":
        return (cfg.control_root.parent / "data" / "explore").resolve()
    if store == "proceedings":
        return (cfg.control_root.parent / "data" / "proceedings").resolve()
    raise RuntimeError(f"unsupported migration store: {store}")


def _durable_store_dir(cfg: Config, store: str) -> Path:
    return (cfg.control_root.parent / "data" / "libraries" / store).resolve()


def _migration_phase_for_store(store: str) -> str:
    if store == "proceedings":
        return "A8"
    if store == "spool":
        return "A9"
    if store == "papers":
        return "A10"
    if store == "workspace":
        return "A10"
    return "A7"


def _cleanup_candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    return (str(candidate.get("store") or ""), str(candidate.get("legacy_path") or ""))


def _merge_cleanup_candidates(
    existing: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in existing or []:
        if not isinstance(candidate, dict):
            continue
        key = _cleanup_candidate_key(candidate)
        if key == ("", ""):
            continue
        merged[key] = dict(candidate)
    for candidate in new or []:
        if not isinstance(candidate, dict):
            continue
        key = _cleanup_candidate_key(candidate)
        if key == ("", ""):
            continue
        merged[key] = dict(merged.get(key, {})) | dict(candidate)
    return sorted(merged.values(), key=lambda item: (str(item.get("store") or ""), str(item.get("legacy_path") or "")))


def _read_plan_payload(journal_dir: Path) -> dict[str, Any]:
    plan_path = journal_dir / "plan.json"
    if not plan_path.exists():
        return {}
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _write_plan_payload(journal_dir: Path, payload: dict[str, Any]) -> None:
    _write_json(journal_dir / "plan.json", payload)


def _legacy_cleanup_candidates_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    planned = plan.get("planned_cleanup_candidates")
    if not isinstance(planned, list):
        return []

    cleanup_candidates: list[dict[str, Any]] = []
    for candidate in planned:
        if not isinstance(candidate, dict):
            continue
        legacy_path = Path(str(candidate.get("legacy_path") or ""))
        target_path = Path(str(candidate.get("target_path") or ""))
        store = str(candidate.get("store") or "")
        cleanup_scope = str(candidate.get("cleanup_scope") or "")
        if store == "workspace":
            continue
        if not legacy_path.exists():
            continue
        if store != "workspace" and not target_path.exists():
            continue

        payload = {
            "store": store,
            "legacy_path": str(legacy_path),
            "target_path": str(target_path),
            "cleanup_action": "archive",
            "migration_phase": candidate.get("migration_phase"),
            "item_count": candidate.get("item_count"),
        }
        if cleanup_scope:
            payload["cleanup_scope"] = cleanup_scope
        if "queue_root" in candidate:
            payload["queue_root"] = candidate["queue_root"]
        cleanup_candidates.append(payload)
    return cleanup_candidates


def _ensure_finalize_targets_ready(plan: dict[str, Any]) -> None:
    stores = plan.get("stores", {})
    missing_targets: list[str] = []
    for candidate in _legacy_cleanup_candidates_from_plan(plan):
        store = str(candidate.get("store") or "")
        if store == "workspace":
            continue
        if store == "spool":
            queue_root = str(candidate.get("queue_root") or "")
            spool_roots = stores.get("spool", {}).get("roots", [])
            root_info = next((item for item in spool_roots if item.get("name") == queue_root), None)
            if root_info is None:
                missing_targets.append(str(candidate.get("target_path") or ""))
                continue
            legacy_item_count = int(root_info.get("legacy_item_count", 0))
            target_item_count = int(root_info.get("target_item_count", 0))
            if legacy_item_count > 0 and target_item_count == 0:
                missing_targets.append(str(root_info.get("target_path") or candidate.get("target_path") or ""))
            continue

        store_info = stores.get(store, {})
        legacy_item_count = int(store_info.get("legacy_item_count", 0))
        target_item_count = int(store_info.get("item_count", 0))
        target_path = Path(str(candidate.get("target_path") or ""))
        if legacy_item_count > 0 and target_item_count == 0:
            missing_targets.append(str(target_path))
    if missing_targets:
        preview = ", ".join(missing_targets[:5])
        raise RuntimeError(f"migrate finalize blocked: missing durable target data for {preview}")


def _ensure_migration_plan_unblocked(plan: dict[str, Any], *, operation: str) -> None:
    blockers = plan.get("blockers") or []
    if not isinstance(blockers, list):
        blockers = [blockers]
    if not blockers:
        return

    codes: list[str] = []
    for blocker in blockers:
        if isinstance(blocker, dict):
            code = blocker.get("code")
            codes.append(str(code or blocker))
            continue
        codes.append(str(blocker))
    raise RuntimeError(f"{operation} blocked: {', '.join(codes) or 'unresolved blockers'}")


def _store_copy_plan(source: Path, target: Path) -> dict[str, Any]:
    entries = sorted(source.rglob("*"), key=lambda path: path.relative_to(source).as_posix()) if source.is_dir() else []
    to_copy: list[str] = []
    to_copy_symlinks: list[str] = []
    dirs: list[str] = []
    skipped: list[str] = []
    skipped_symlinks: list[str] = []
    conflicts: list[str] = []

    for src in entries:
        rel = src.relative_to(source)
        dest = target / rel
        rel_text = rel.as_posix()
        dest_exists = os.path.lexists(dest)

        if src.is_symlink():
            if not dest_exists:
                to_copy_symlinks.append(rel_text)
                continue
            if not dest.is_symlink() or os.readlink(src) != os.readlink(dest):
                conflicts.append(rel_text)
                continue
            skipped_symlinks.append(rel_text)
            continue

        if src.is_dir():
            if dest_exists and not dest.is_dir():
                conflicts.append(rel_text)
                continue
            dirs.append(rel_text)
            continue

        if not dest_exists:
            to_copy.append(rel_text)
            continue
        if not dest.is_file() or dest.read_bytes() != src.read_bytes():
            conflicts.append(rel_text)
            continue
        skipped.append(rel_text)

    return {
        "source_file_count": len(to_copy) + len(skipped),
        "source_symlink_count": len(to_copy_symlinks) + len(skipped_symlinks),
        "source_item_count": len(to_copy) + len(skipped) + len(to_copy_symlinks) + len(skipped_symlinks),
        "dirs": dirs,
        "to_copy": to_copy,
        "to_copy_symlinks": to_copy_symlinks,
        "skipped": skipped,
        "skipped_symlinks": skipped_symlinks,
        "conflicts": conflicts,
    }


def _copy_store_without_overwrite(source: Path, target: Path, plan: dict[str, Any]) -> None:
    for rel_text in plan["dirs"]:
        (target / rel_text).mkdir(parents=True, exist_ok=True)
    for rel_text in plan["to_copy"]:
        src = source / rel_text
        dest = target / rel_text
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for rel_text in plan["to_copy_symlinks"]:
        src = source / rel_text
        dest = target / rel_text
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(src), dest)


def _run_spool_migration_store(cfg: Config, *, migration_id: str) -> dict[str, Any]:
    spool_items = _spool_store_dirs(cfg)
    copy_plans: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for item in spool_items:
        source = Path(item["source"])
        target = Path(item["target"])
        plan = _store_copy_plan(source, target)
        copy_plans.append({"item": item, "plan": plan})
        conflicts.extend(f"{item['name']}:{rel}" for rel in plan["conflicts"])

    if conflicts:
        conflict_preview = ", ".join(conflicts[:5])
        raise RuntimeError(f"conflicting spool target files: {conflict_preview}")

    plan_payload = run_migration_plan(cfg, migration_id=migration_id)
    _ensure_migration_plan_unblocked(plan_payload, operation="migrate run")
    write_migration_lock(cfg, migration_id=migration_id, mode="run")
    meta = ensure_instance_metadata(cfg)
    previous_state = str(meta.get("layout_state") or LEGACY_LAYOUT_STATE)
    mark_instance_layout_state(cfg, "migrating")

    try:
        copied_count = 0
        skipped_count = 0
        cleanup_candidates: list[dict[str, Any]] = []
        roots: list[dict[str, Any]] = []
        for entry in copy_plans:
            item = entry["item"]
            plan = entry["plan"]
            source = Path(item["source"])
            target = Path(item["target"])

            target.mkdir(parents=True, exist_ok=True)
            _copy_store_without_overwrite(source, target, plan)

            root_copied = len(plan["to_copy"]) + len(plan["to_copy_symlinks"])
            root_skipped = len(plan["skipped"]) + len(plan["skipped_symlinks"])
            copied_count += root_copied
            skipped_count += root_skipped
            roots.append(
                {
                    "name": item["name"],
                    "source_path": str(source),
                    "target_path": str(target),
                    "copied_count": root_copied,
                    "skipped_count": root_skipped,
                    "source_item_count": plan["source_item_count"],
                }
            )

            if source.is_dir():
                cleanup_candidates.append(
                    {
                        "store": "spool",
                        "queue_root": item["name"],
                        "legacy_path": str(source),
                        "target_path": str(target),
                        "cleanup_action": "archive",
                        "migration_phase": "A9",
                        "item_count": plan["source_item_count"],
                    }
                )

        journal_dir = resolve_migration_journal(cfg, migration_id)
        if journal_dir is None:
            raise FileNotFoundError(f"migration journal not found: {migration_id}")

        target_root = (cfg.control_root.parent / "data" / "spool").resolve()
        source_root = (cfg.control_root.parent / "data").resolve()
        plan_path = journal_dir / "plan.json"
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        plan_payload["cleanup_candidates"] = _merge_cleanup_candidates(
            plan_payload.get("cleanup_candidates"), cleanup_candidates
        )
        plan_payload["run"] = {
            "status": "copied",
            "store": "spool",
            "source_path": str(source_root),
            "target_path": str(target_root),
            "copied_count": copied_count,
            "skipped_count": skipped_count,
            "cleanup_candidate_count": len(cleanup_candidates),
            "roots": roots,
            "updated_at": _now_iso(),
        }
        _write_json(plan_path, plan_payload)

        append_migration_journal_step(
            cfg,
            migration_id,
            step_name="run_store",
            status="ok",
            message="spool queues copied to data/spool targets",
            details=plan_payload["run"],
        )

        verify = run_migration_verification(
            cfg,
            migration_id,
            non_blocking_checks=NON_BLOCKING_DERIVED_STATE_CHECKS | {"workspace_index_layout"},
        )
        if verify.get("status") == "failed":
            raise RuntimeError("post-run verification failed")

        updated_meta = ensure_instance_metadata(cfg)
        updated_meta["layout_state"] = previous_state if previous_state != "migrating" else LEGACY_LAYOUT_STATE
        updated_meta["last_successful_migration_id"] = migration_id
        updated_meta["updated_at"] = _now_iso()
        write_instance_metadata(cfg, updated_meta)
        refresh_migration_summary(cfg, migration_id)

        return {
            "migration_id": migration_id,
            "store": "spool",
            "status": "passed",
            "source_path": str(source_root),
            "target_path": str(target_root),
            "copied_count": copied_count,
            "skipped_count": skipped_count,
            "cleanup_candidate_count": len(cleanup_candidates),
            "verify_status": verify["status"],
        }
    except Exception:
        append_migration_journal_step(
            cfg,
            migration_id,
            step_name="run_store",
            status="failed",
            message="spool migration failed",
        )
        mark_instance_layout_state(cfg, "needs_recovery")
        raise
    finally:
        clear_migration_lock(cfg)


def _run_workspace_migration_store(cfg: Config, *, migration_id: str) -> dict[str, Any]:
    from scholaraio.projects.workspace import migrate_workspace_index_layouts

    plan_payload = run_migration_plan(cfg, migration_id=migration_id)
    _ensure_migration_plan_unblocked(plan_payload, operation="migrate run")
    write_migration_lock(cfg, migration_id=migration_id, mode="run")
    meta = ensure_instance_metadata(cfg)
    previous_state = str(meta.get("layout_state") or LEGACY_LAYOUT_STATE)
    mark_instance_layout_state(cfg, "migrating")

    try:
        reports = migrate_workspace_index_layouts(cfg.workspace_dir)
        migrated_count = sum(1 for report in reports if report["status"] in {"migrated", "initialized_empty"})
        skipped_count = sum(1 for report in reports if report["status"] in {"current_only", "already_migrated"})
        cleanup_candidates: list[dict[str, Any]] = []
        for report in reports:
            raw_cleanup_candidates = report.get("cleanup_candidates", [])
            cleanup_paths = (
                cast(list[Path | str], raw_cleanup_candidates) if isinstance(raw_cleanup_candidates, list) else []
            )
            raw_entry_count = report.get("entry_count", 0)
            entry_count = int(raw_entry_count) if isinstance(raw_entry_count, (int, str, float)) else 0
            for legacy_path in cleanup_paths:
                cleanup_candidates.append(
                    {
                        "store": "workspace",
                        "legacy_path": str(legacy_path),
                        "target_path": str(report["current_path"]),
                        "cleanup_action": "archive",
                        "migration_phase": "A10",
                        "item_count": entry_count,
                    }
                )

        journal_dir = resolve_migration_journal(cfg, migration_id)
        if journal_dir is None:
            raise FileNotFoundError(f"migration journal not found: {migration_id}")

        plan_path = journal_dir / "plan.json"
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        plan_payload["cleanup_candidates"] = _merge_cleanup_candidates(
            plan_payload.get("cleanup_candidates"), cleanup_candidates
        )
        plan_payload["run"] = {
            "status": "migrated",
            "store": "workspace",
            "source_path": str(cfg.workspace_dir),
            "target_path": str(cfg.workspace_dir),
            "copied_count": migrated_count,
            "skipped_count": skipped_count,
            "cleanup_candidate_count": len(cleanup_candidates),
            "workspace_reports": reports,
            "updated_at": _now_iso(),
        }
        _write_json(plan_path, plan_payload)

        append_migration_journal_step(
            cfg,
            migration_id,
            step_name="run_store",
            status="ok",
            message="workspace paper indexes migrated to refs/papers.json",
            details=plan_payload["run"],
        )

        verify = run_migration_verification(
            cfg,
            migration_id,
            non_blocking_checks=NON_BLOCKING_DERIVED_STATE_CHECKS | {"workspace_index_layout"},
        )
        if verify.get("status") == "failed":
            raise RuntimeError("post-run verification failed")

        updated_meta = ensure_instance_metadata(cfg)
        updated_meta["layout_state"] = previous_state if previous_state != "migrating" else LEGACY_LAYOUT_STATE
        updated_meta["last_successful_migration_id"] = migration_id
        updated_meta["updated_at"] = _now_iso()
        write_instance_metadata(cfg, updated_meta)
        refresh_migration_summary(cfg, migration_id)

        return {
            "migration_id": migration_id,
            "store": "workspace",
            "status": "passed",
            "source_path": str(cfg.workspace_dir),
            "target_path": str(cfg.workspace_dir),
            "copied_count": migrated_count,
            "skipped_count": skipped_count,
            "cleanup_candidate_count": len(cleanup_candidates),
            "verify_status": verify["status"],
        }
    except Exception:
        append_migration_journal_step(
            cfg,
            migration_id,
            step_name="run_store",
            status="failed",
            message="workspace migration failed",
        )
        mark_instance_layout_state(cfg, "needs_recovery")
        raise
    finally:
        clear_migration_lock(cfg)


def run_migration_store(
    cfg: Config,
    *,
    store: str,
    migration_id: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run one supported store migration with journal and verification."""
    if store not in SUPPORTED_MIGRATION_RUN_STORES:
        supported = ", ".join(sorted(SUPPORTED_MIGRATION_RUN_STORES))
        raise RuntimeError(f"migrate run currently supports only {supported}, got: {store}")
    if not confirm:
        raise RuntimeError("migrate run requires --confirm before changing runtime data")
    if describe_migration_lock(cfg)["status"] != "absent":
        raise RuntimeError("migrate run blocked because migration.lock already exists")
    if not migration_id:
        migration_id = datetime.now(timezone.utc).strftime("mig-run-%Y%m%d-%H%M%S")
    if store == "spool":
        return _run_spool_migration_store(cfg, migration_id=migration_id)
    if store == "workspace":
        return _run_workspace_migration_store(cfg, migration_id=migration_id)

    source = _legacy_store_dir(cfg, store)
    target = _durable_store_dir(cfg, store)
    copy_plan = _store_copy_plan(source, target)
    if copy_plan["conflicts"]:
        conflicts = ", ".join(copy_plan["conflicts"][:5])
        store_label = "citation style" if store == "citation_styles" else store
        raise RuntimeError(f"conflicting {store_label} target files: {conflicts}")

    plan_payload = run_migration_plan(cfg, migration_id=migration_id)
    _ensure_migration_plan_unblocked(plan_payload, operation="migrate run")
    write_migration_lock(cfg, migration_id=migration_id, mode="run")
    meta = ensure_instance_metadata(cfg)
    previous_state = str(meta.get("layout_state") or LEGACY_LAYOUT_STATE)
    mark_instance_layout_state(cfg, "migrating")

    try:
        target.mkdir(parents=True, exist_ok=True)
        _copy_store_without_overwrite(source, target, copy_plan)

        if store == "papers":
            from scholaraio.services.index import build_index

            build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

        cleanup_candidates: list[dict[str, Any]] = []
        if source.is_dir() and copy_plan["source_item_count"] > 0:
            cleanup_candidates.append(
                {
                    "store": store,
                    "legacy_path": str(source),
                    "target_path": str(target),
                    "cleanup_action": "archive",
                    "migration_phase": _migration_phase_for_store(store),
                    "item_count": copy_plan["source_item_count"],
                }
            )

        journal_dir = resolve_migration_journal(cfg, migration_id)
        if journal_dir is None:
            raise FileNotFoundError(f"migration journal not found: {migration_id}")

        plan_path = journal_dir / "plan.json"
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        plan_payload["cleanup_candidates"] = _merge_cleanup_candidates(
            plan_payload.get("cleanup_candidates"), cleanup_candidates
        )
        plan_payload["run"] = {
            "status": "copied",
            "store": store,
            "source_path": str(source),
            "target_path": str(target),
            "copied_count": len(copy_plan["to_copy"]) + len(copy_plan["to_copy_symlinks"]),
            "skipped_count": len(copy_plan["skipped"]) + len(copy_plan["skipped_symlinks"]),
            "cleanup_candidate_count": len(cleanup_candidates),
            "updated_at": _now_iso(),
        }
        _write_json(plan_path, plan_payload)

        append_migration_journal_step(
            cfg,
            migration_id,
            step_name="run_store",
            status="ok",
            message=f"{store} copied to durable library target",
            details=plan_payload["run"],
        )

        verify = run_migration_verification(
            cfg,
            migration_id,
            non_blocking_checks=NON_BLOCKING_DERIVED_STATE_CHECKS | {"workspace_index_layout"},
        )
        if verify.get("status") == "failed":
            raise RuntimeError("post-run verification failed")

        updated_meta = ensure_instance_metadata(cfg)
        updated_meta["layout_state"] = previous_state if previous_state != "migrating" else LEGACY_LAYOUT_STATE
        updated_meta["last_successful_migration_id"] = migration_id
        updated_meta["updated_at"] = _now_iso()
        write_instance_metadata(cfg, updated_meta)
        refresh_migration_summary(cfg, migration_id)

        return {
            "migration_id": migration_id,
            "store": store,
            "status": "passed",
            "source_path": str(source),
            "target_path": str(target),
            "copied_count": len(copy_plan["to_copy"]) + len(copy_plan["to_copy_symlinks"]),
            "skipped_count": len(copy_plan["skipped"]) + len(copy_plan["skipped_symlinks"]),
            "cleanup_candidate_count": len(cleanup_candidates),
            "verify_status": verify["status"],
        }
    except Exception:
        append_migration_journal_step(
            cfg,
            migration_id,
            step_name="run_store",
            status="failed",
            message=f"{store} migration failed",
        )
        mark_instance_layout_state(cfg, "needs_recovery")
        raise
    finally:
        clear_migration_lock(cfg)
