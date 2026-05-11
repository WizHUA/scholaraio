"""Tests for rsync backup configuration, command planning, and execution."""

from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio.core.config import _build_config
from scholaraio.interfaces.cli import compat as cli


def _build_backup_cfg(tmp_path: Path):
    return _build_config(
        {
            "backup": {
                "source_dir": "data",
                "targets": {
                    "lab": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio",
                        "port": 2222,
                        "identity_file": "secrets/id_ed25519",
                        "mode": "append-verify",
                        "compress": True,
                        "enabled": True,
                        "exclude": ["*.tmp", "metrics.db"],
                    }
                },
            }
        },
        tmp_path,
    )


def test_build_rsync_command_uses_configured_target_and_flags(tmp_path: Path):
    from scholaraio.services.backup import build_rsync_command

    cfg = _build_backup_cfg(tmp_path)

    cmd = build_rsync_command(cfg, "lab", dry_run=True)

    assert cmd[0] == "rsync"
    assert "-a" in cmd
    assert "-z" in cmd
    assert "--append-verify" in cmd
    assert "--dry-run" in cmd
    assert "--exclude" in cmd
    assert cmd[-1] == "alice@backup.example.com:/srv/scholaraio/"
    assert cmd[-2] == f"{(tmp_path / 'data').resolve()}/"
    assert "-e" in cmd
    ssh_cmd = cmd[cmd.index("-e") + 1]
    assert "ssh" in ssh_cmd
    assert "-p 2222" in ssh_cmd
    assert "-o BatchMode=yes" in ssh_cmd
    assert f"-i {(tmp_path / 'secrets' / 'id_ed25519').resolve()}" in ssh_cmd


def test_build_rsync_command_rejects_missing_target(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_rsync_command

    cfg = _build_backup_cfg(tmp_path)

    with pytest.raises(BackupConfigError, match="unknown backup target"):
        build_rsync_command(cfg, "missing")


def test_build_rsync_command_rejects_disabled_target(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_rsync_command

    cfg = _build_config(
        {
            "backup": {
                "targets": {
                    "archive": {
                        "host": "backup.example.com",
                        "path": "/srv/archive",
                        "enabled": False,
                    }
                }
            }
        },
        tmp_path,
    )

    with pytest.raises(BackupConfigError, match="disabled"):
        build_rsync_command(cfg, "archive")


def test_build_rsync_command_switches_to_password_auth_when_password_is_configured(tmp_path: Path):
    from scholaraio.services.backup import build_rsync_command

    cfg = _build_config(
        {
            "backup": {
                "targets": {
                    "lab": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio",
                        "port": 2222,
                        "password": "secret",
                    }
                }
            }
        },
        tmp_path,
    )

    cmd = build_rsync_command(cfg, "lab", dry_run=True)
    ssh_cmd = cmd[cmd.index("-e") + 1]

    assert "-o BatchMode=yes" not in ssh_cmd
    assert "-o PreferredAuthentications=password,keyboard-interactive" in ssh_cmd
    assert "-o PubkeyAuthentication=no" in ssh_cmd


def test_run_backup_invokes_subprocess_with_planned_command(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import run_backup

    cfg = _build_backup_cfg(tmp_path)
    seen: list[list[str]] = []

    def fake_run(cmd, check, text, **kwargs):
        seen.append(cmd)
        assert check is False
        assert text is True
        assert kwargs.get("capture_output") is True
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    result = run_backup(cfg, "lab", dry_run=False)

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert seen


def test_run_backup_reports_missing_rsync_binary_as_config_error(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import BackupConfigError, run_backup

    cfg = _build_backup_cfg(tmp_path)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("rsync not found")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    with pytest.raises(BackupConfigError, match="failed to execute rsync"):
        run_backup(cfg, "lab", dry_run=False)


def test_run_backup_uses_askpass_env_for_password_targets(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import run_backup

    cfg = _build_config(
        {
            "backup": {
                "targets": {
                    "lab": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio",
                        "password": "secret",
                    }
                }
            }
        },
        tmp_path,
    )
    seen: dict[str, object] = {}

    def fake_run(cmd, check, text, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        assert kwargs.get("stdin") is subprocess.DEVNULL
        env = kwargs.get("env") or {}
        assert env["SCHOLARAIO_BACKUP_SSH_PASSWORD"] == "secret"
        assert env["SSH_ASKPASS_REQUIRE"] == "force"
        assert env["DISPLAY"] == "scholaraio-backup"
        assert "SSH_ASKPASS" in env
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    result = run_backup(cfg, "lab", dry_run=False)

    assert result.returncode == 0
    assert result.stdout == "ok"


def test_cmd_backup_list_displays_configured_targets(tmp_path: Path, monkeypatch):
    cfg = _build_backup_cfg(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))

    cli.cmd_backup(Namespace(backup_action="list"), cfg)

    assert any("Backup source directory" in msg for msg in messages)
    assert any("[lab] enabled" in msg for msg in messages)
    assert any("append-verify" in msg for msg in messages)


def test_cmd_backup_run_reports_dry_run_completion(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=True), _build_backup_cfg(tmp_path))

    assert any("About to run backup command" in msg for msg in messages)
    assert any("Dry run complete" in msg for msg in messages)


def test_cmd_backup_run_displays_shell_quoted_preview(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: [
            "rsync",
            "-a",
            "-e",
            "ssh -p 2222 -i /tmp/test key",
            "/src/",
            "alice@host:/dst/",
        ],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=True), _build_backup_cfg(tmp_path))

    assert any("About to run backup command" in msg for msg in messages)
    assert any("'ssh -p 2222 -i /tmp/test key'" in msg for msg in messages)


def test_cmd_backup_run_exits_cleanly_when_backup_runtime_error_occurs(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import BackupConfigError

    messages: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["missing-rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BackupConfigError("failed to execute rsync")),
    )

    with pytest.raises(SystemExit, match="1"):
        cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=False), _build_backup_cfg(tmp_path))

    assert any("About to run backup command" in msg for msg in messages)
    assert any("failed to execute rsync" in msg for msg in errors)


def test_cmd_backup_run_shows_guidance_for_noninteractive_auth_failures(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=255,
            stdout="",
            stderr="alice@host: Permission denied (publickey,password).",
        ),
    )

    with pytest.raises(SystemExit, match="255"):
        cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=False), _build_backup_cfg(tmp_path))

    assert any("Permission denied" in msg for msg in messages)
    assert any("BatchMode=yes" in msg for msg in messages)
    assert any("config.local.yaml" in msg for msg in messages)
    assert any("known_hosts" in msg for msg in messages)
    assert any("Backup failed, exit code: 255" in msg for msg in errors)


def test_cmd_backup_run_shows_guidance_for_host_key_failures(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=255,
            stdout="",
            stderr="Host key verification failed.",
        ),
    )

    with pytest.raises(SystemExit, match="255"):
        cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=False), _build_backup_cfg(tmp_path))

    assert any("Host key verification failed" in msg for msg in messages)
    assert any("known_hosts" in msg for msg in messages)
    assert any("ssh-keyscan" in msg for msg in messages)
    assert any("Backup failed, exit code: 255" in msg for msg in errors)
