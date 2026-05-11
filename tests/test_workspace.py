"""Contract tests for workspace management.

Verifies: create initializes the current ``refs/papers.json`` layout,
read_paper_ids returns correct UUIDs, and explicit migration rewrites legacy
root ``papers.json`` into the current layout.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from scholaraio.projects.workspace import (
    add,
    create,
    list_workspaces,
    migrate_paper_index_layout,
    migrate_workspace_index_layouts,
    read_manifest,
    read_paper_ids,
    remove,
    rename,
    validate_workspace_name,
)


class TestWorkspaceCreate:
    """Workspace creation contract."""

    def test_create_initializes_directory(self, tmp_path):
        ws_dir = tmp_path / "workspace" / "test-ws"
        create(ws_dir)
        assert ws_dir.is_dir()
        assert (ws_dir / "refs" / "papers.json").exists()

    def test_create_idempotent(self, tmp_path):
        ws_dir = tmp_path / "workspace" / "test-ws"
        create(ws_dir)
        create(ws_dir)
        data = json.loads((ws_dir / "refs" / "papers.json").read_text())
        assert data == []


class TestReadPaperIds:
    """read_paper_ids contract: returns set of UUIDs from refs/papers.json."""

    def test_empty_workspace(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        assert read_paper_ids(ws_dir) == set()

    def test_reads_ids_from_current_refs_papers_json(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "refs" / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        ids = read_paper_ids(ws_dir)
        assert ids == {"aaaa-1111", "bbbb-2222"}

    def test_nonexistent_workspace_returns_empty(self, tmp_path):
        ids = read_paper_ids(tmp_path / "nonexistent")
        assert ids == set()

    def test_reads_ids_from_refs_papers_json(self, tmp_path):
        ws_dir = tmp_path / "ws"
        (ws_dir / "refs").mkdir(parents=True)
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "refs" / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        ids = read_paper_ids(ws_dir)
        assert ids == {"aaaa-1111", "bbbb-2222"}

    def test_legacy_root_papers_json_is_ignored_until_migrated(self, tmp_path):
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir(parents=True)
        (ws_dir / "papers.json").write_text(
            json.dumps([{"id": "paper-legacy", "dir_name": "Legacy-Paper", "added_at": "2024-01-01"}]),
            encoding="utf-8",
        )

        ids = read_paper_ids(ws_dir)
        assert ids == set()


class TestWorkspaceIndexMigration:
    def test_migrate_paper_index_layout_rewrites_root_index_into_refs(self, tmp_path):
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir(parents=True)
        entries = [
            {"id": "paper-1", "dir_name": "Paper-One", "added_at": "2024-01-01"},
            {"id": "paper-2", "dir_name": "Paper-Two", "added_at": "2024-01-01"},
        ]
        (ws_dir / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        result = migrate_paper_index_layout(ws_dir)

        assert result["status"] == "migrated"
        assert result["entry_count"] == 2
        assert json.loads((ws_dir / "refs" / "papers.json").read_text(encoding="utf-8")) == entries
        assert result["cleanup_candidates"] == [str(ws_dir / "papers.json")]

    def test_migrate_paper_index_layout_rejects_conflicting_current_and_legacy_indexes(self, tmp_path):
        ws_dir = tmp_path / "ws"
        (ws_dir / "refs").mkdir(parents=True)
        (ws_dir / "papers.json").write_text(
            json.dumps([{"id": "paper-legacy", "dir_name": "Legacy", "added_at": "2024-01-01"}]),
            encoding="utf-8",
        )
        (ws_dir / "refs" / "papers.json").write_text(
            json.dumps([{"id": "paper-current", "dir_name": "Current", "added_at": "2024-01-01"}]),
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="mismatch"):
            migrate_paper_index_layout(ws_dir)

    def test_migrate_workspace_index_layouts_skips_system_dir(self, tmp_path):
        ws_root = tmp_path / "workspace"
        legacy_ws = ws_root / "legacy"
        system_dir = ws_root / "_system"
        legacy_ws.mkdir(parents=True)
        system_dir.mkdir(parents=True)
        (legacy_ws / "papers.json").write_text("[]\n", encoding="utf-8")

        reports = migrate_workspace_index_layouts(ws_root)

        assert [report["workspace"] for report in reports] == ["legacy"]


class TestReadManifest:
    def test_missing_manifest_returns_none(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)

        assert read_manifest(ws_dir) is None

    def test_reads_and_normalizes_schema_v1_manifest(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text(
            """
schema_version: 1
name: " turbulence-review "
description: " Drafting workspace "
tags:
  - review
  - " turbulence "
  - ""
  - review
mounts:
  explore:
    - survey-2026
    - " survey-2026 "
    - ""
  toolref:
    - openfoam-2312
  custom_bucket:
    - keep-me
outputs:
  default_dir: " outputs/reports "
custom_field:
  enabled: true
""".strip()
            + "\n",
            encoding="utf-8",
        )

        manifest = read_manifest(ws_dir)

        assert manifest == {
            "schema_version": 1,
            "name": "turbulence-review",
            "description": "Drafting workspace",
            "tags": ["review", "turbulence"],
            "mounts": {
                "explore": ["survey-2026"],
                "toolref": ["openfoam-2312"],
                "custom_bucket": ["keep-me"],
            },
            "outputs": {"default_dir": "outputs/reports"},
            "custom_field": {"enabled": True},
        }

    def test_preserves_unsupported_newer_schema_as_opaque_metadata(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text(
            """
schema_version: 2
name: "  Keep Raw  "
tags:
  - " A "
unknown:
  nested: true
""".strip()
            + "\n",
            encoding="utf-8",
        )

        manifest = read_manifest(ws_dir)

        assert manifest == {
            "schema_version": 2,
            "name": "  Keep Raw  ",
            "tags": [" A "],
            "unknown": {"nested": True},
        }

    def test_rejects_manifest_without_schema_version(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text("name: test\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="缺少 schema_version"):
            read_manifest(ws_dir)

    def test_rejects_boolean_schema_version(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text("schema_version: true\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="schema_version 必须是整数"):
            read_manifest(ws_dir)

    def test_rejects_non_mapping_manifest(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text("- bad\n- manifest\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="期望 mapping"):
            read_manifest(ws_dir)

    def test_rejects_physical_path_like_mount_entries(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text(
            """
schema_version: 1
mounts:
  explore:
    - ../survey
""".strip()
            + "\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match=r"mounts\.explore"):
            read_manifest(ws_dir)

    def test_rejects_outputs_dir_that_escapes_workspace(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        (ws_dir / "workspace.yaml").write_text(
            """
schema_version: 1
outputs:
  default_dir: ../reports
""".strip()
            + "\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match=r"outputs\.default_dir"):
            read_manifest(ws_dir)


class TestAddResolved:
    """add(resolved=...) contract: batch-add pre-resolved papers."""

    def test_adds_and_deduplicates(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        resolved = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test"},
        ]
        added = add(ws_dir, [], tmp_path / "unused.db", resolved=resolved)
        assert len(added) == 2
        assert read_paper_ids(ws_dir) == {"aaaa-1111", "bbbb-2222"}

        # Second call with overlap — only new paper added
        resolved2 = [
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test"},
            {"id": "cccc-3333", "dir_name": "Li-2025-New"},
        ]
        added2 = add(ws_dir, [], tmp_path / "unused.db", resolved=resolved2)
        assert len(added2) == 1
        assert added2[0]["id"] == "cccc-3333"
        assert read_paper_ids(ws_dir) == {"aaaa-1111", "bbbb-2222", "cccc-3333"}

    def test_add_preserves_future_refs_layout_when_legacy_missing(self, tmp_path):
        ws_dir = tmp_path / "ws"
        (ws_dir / "refs").mkdir(parents=True)
        (ws_dir / "refs" / "papers.json").write_text("[]\n", encoding="utf-8")

        resolved = [{"id": "aaaa-1111", "dir_name": "Smith-2023-Test"}]
        added = add(ws_dir, [], tmp_path / "unused.db", resolved=resolved)

        assert len(added) == 1
        assert not (ws_dir / "papers.json").exists()
        entries = json.loads((ws_dir / "refs" / "papers.json").read_text(encoding="utf-8"))
        assert [entry["id"] for entry in entries] == ["aaaa-1111"]


class TestRemove:
    def test_remove_falls_back_to_workspace_dir_name_when_lookup_misses(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "refs" / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        monkeypatch.setattr("scholaraio.services.index.lookup_paper", lambda db_path, ref: None)

        removed = remove(ws_dir, ["Smith-2023-Test"], tmp_path / "index.db")

        assert [e["dir_name"] for e in removed] == ["Smith-2023-Test"]
        assert read_paper_ids(ws_dir) == {"bbbb-2222"}

    def test_remove_lookup_miss_does_not_delete_uuid_collision_entry(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "real-uuid-1", "dir_name": "SharedRef", "added_at": "2024-01-01"},
            {"id": "SharedRef", "dir_name": "Other-Paper", "added_at": "2024-01-01"},
        ]
        (ws_dir / "refs" / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        monkeypatch.setattr("scholaraio.services.index.lookup_paper", lambda db_path, ref: None)

        removed = remove(ws_dir, ["SharedRef"], tmp_path / "index.db")

        assert [e["dir_name"] for e in removed] == ["Other-Paper"]
        assert read_paper_ids(ws_dir) == {"real-uuid-1"}

    def test_remove_falls_back_when_lookup_raises_sqlite_error(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "refs" / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        def fail_lookup(db_path, ref):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("scholaraio.services.index.lookup_paper", fail_lookup)

        removed = remove(ws_dir, ["Smith-2023-Test"], tmp_path / "index.db")

        assert [e["dir_name"] for e in removed] == ["Smith-2023-Test"]
        assert read_paper_ids(ws_dir) == {"bbbb-2222"}


class TestListWorkspaces:
    """list_workspaces contract: discovers workspace directories."""

    def test_lists_created_workspaces(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "alpha")
        create(ws_root / "beta")

        names = list_workspaces(ws_root)
        assert set(names) == {"alpha", "beta"}

    def test_ignores_dirs_without_refs_papers_json(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "real")
        (ws_root / "fake").mkdir(parents=True)

        names = list_workspaces(ws_root)
        assert names == ["real"]

    def test_recognizes_refs_papers_json(self, tmp_path):
        ws_root = tmp_path / "workspace"
        current_dir = ws_root / "current"
        (current_dir / "refs").mkdir(parents=True)
        (current_dir / "refs" / "papers.json").write_text("[]\n", encoding="utf-8")

        names = list_workspaces(ws_root)
        assert names == ["current"]


class TestRenameWorkspace:
    """rename contract: moves workspace and validates source/target."""

    def test_rename_success(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")

        new_dir = rename(ws_root, "old", "new")

        assert new_dir == ws_root / "new"
        assert (ws_root / "new" / "refs" / "papers.json").exists()
        assert not (ws_root / "old").exists()

    def test_rename_missing_source_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir(parents=True, exist_ok=True)

        with pytest.raises(FileNotFoundError, match="工作区不存在"):
            rename(ws_root, "missing", "new")

    def test_rename_target_exists_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")
        create(ws_root / "new")

        with pytest.raises(FileExistsError, match="目标工作区已存在"):
            rename(ws_root, "old", "new")

    def test_rename_source_is_not_directory_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir(parents=True, exist_ok=True)
        (ws_root / "old").write_text("not a directory", encoding="utf-8")

        with pytest.raises(ValueError, match="不是有效工作区目录"):
            rename(ws_root, "old", "new")

    def test_rename_source_without_refs_papers_json_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        (ws_root / "old").mkdir(parents=True, exist_ok=True)

        with pytest.raises(ValueError, match=r"缺少工作区论文索引"):
            rename(ws_root, "old", "new")

    def test_rename_future_refs_workspace_success(self, tmp_path):
        ws_root = tmp_path / "workspace"
        old_dir = ws_root / "old"
        (old_dir / "refs").mkdir(parents=True)
        (old_dir / "refs" / "papers.json").write_text("[]\n", encoding="utf-8")

        new_dir = rename(ws_root, "old", "new")

        assert new_dir == ws_root / "new"
        assert (ws_root / "new" / "refs" / "papers.json").exists()
        assert not (ws_root / "old").exists()

    def test_rename_rejects_invalid_old_name(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")

        with pytest.raises(ValueError, match="非法工作区名称"):
            rename(ws_root, "../old", "new")

    def test_rename_rejects_invalid_new_name(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")

        with pytest.raises(ValueError, match="非法工作区名称"):
            rename(ws_root, "old", "../new")


class TestValidateWorkspaceName:
    def test_accepts_regular_name(self):
        assert validate_workspace_name("my-ws_2026")

    def test_rejects_empty_or_path_like_name(self):
        assert not validate_workspace_name("")
        assert not validate_workspace_name("   ")
        assert not validate_workspace_name(".")
        assert not validate_workspace_name("../foo")
        assert not validate_workspace_name("foo/bar")
        assert not validate_workspace_name("foo\\bar")
        assert not validate_workspace_name("C:foo")
        assert not validate_workspace_name(" ws ")
