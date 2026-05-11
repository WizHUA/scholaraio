"""backup.py -- rsync-based ScholarAIO data backup."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scholaraio.core.config import BackupTargetConfig, Config


class BackupConfigError(ValueError):
    """Raised when backup configuration is missing or invalid."""


@dataclass
class BackupRunResult:
    """Structured result returned from a backup invocation."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def _resolve_target(cfg: Config, target_name: str) -> BackupTargetConfig:
    target = cfg.backup.targets.get(target_name)
    if target is None:
        raise BackupConfigError(f"unknown backup target: {target_name}")
    if not target.enabled:
        raise BackupConfigError(f"backup target is disabled: {target_name}")
    if not target.host:
        raise BackupConfigError(f"backup target {target_name!r} is missing host")
    if not target.path:
        raise BackupConfigError(f"backup target {target_name!r} is missing path")
    return target


def _resolve_identity_file(cfg: Config, identity_file: str) -> str:
    if not identity_file:
        return ""
    path = Path(identity_file).expanduser()
    if not path.is_absolute():
        path = (cfg._root / path).resolve()
    return str(path)


def _build_remote_shell(cfg: Config, target: BackupTargetConfig) -> str:
    parts = [cfg.backup.ssh_bin]
    if target.password:
        parts.extend(
            [
                "-o",
                "PreferredAuthentications=password,keyboard-interactive",
                "-o",
                "PubkeyAuthentication=no",
            ]
        )
    else:
        # Backups should fail fast instead of hanging on interactive SSH prompts.
        parts.extend(["-o", "BatchMode=yes"])
    if target.port and target.port != 22:
        parts.extend(["-p", str(target.port)])
    identity_file = _resolve_identity_file(cfg, target.identity_file)
    if identity_file:
        parts.extend(["-i", identity_file])
    return shlex.join(parts)


def _build_password_env(target: BackupTargetConfig) -> tuple[dict[str, str], str] | tuple[None, None]:
    if not target.password:
        return None, None

    fd, askpass_path = tempfile.mkstemp(prefix="scholaraio-backup-askpass-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nprintf '%s\\n' \"$SCHOLARAIO_BACKUP_SSH_PASSWORD\"\n")
        os.chmod(askpass_path, 0o700)
    except Exception:
        try:
            os.unlink(askpass_path)
        except OSError:
            pass
        raise

    env = os.environ.copy()
    env.update(
        {
            "SCHOLARAIO_BACKUP_SSH_PASSWORD": target.password,
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": "scholaraio-backup",
        }
    )
    return env, askpass_path


def _destination_for(target: BackupTargetConfig) -> str:
    remote = f"{target.user}@{target.host}" if target.user else target.host
    return f"{remote}:{target.path.rstrip('/')}/"


def build_rsync_command(cfg: Config, target_name: str, *, dry_run: bool = False) -> list[str]:
    """Build the rsync command line for a configured backup target."""
    target = _resolve_target(cfg, target_name)
    source_dir = cfg.backup_source_dir

    cmd = [cfg.backup.rsync_bin, "-a", "--stats", "--human-readable"]
    if target.compress:
        cmd.append("-z")
    if target.mode == "append":
        cmd.append("--append")
    elif target.mode == "append-verify":
        cmd.append("--append-verify")
    if dry_run:
        cmd.append("--dry-run")
    for pattern in target.exclude:
        cmd.extend(["--exclude", pattern])
    cmd.extend(["-e", _build_remote_shell(cfg, target)])
    cmd.append(f"{source_dir}/")
    cmd.append(_destination_for(target))
    return cmd


def run_backup(cfg: Config, target_name: str, *, dry_run: bool = False) -> BackupRunResult:
    """Run an rsync backup for a configured target."""
    target = _resolve_target(cfg, target_name)
    cmd = build_rsync_command(cfg, target_name, dry_run=dry_run)
    env, askpass_path = _build_password_env(target)
    run_kwargs: dict[str, Any] = {"check": False, "text": True, "capture_output": True}
    if env is not None:
        run_kwargs["env"] = env
        run_kwargs["stdin"] = subprocess.DEVNULL
    try:
        completed = subprocess.run(cmd, **run_kwargs)
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise BackupConfigError(f"failed to execute rsync {cmd[0]!r}: {detail}") from exc
    finally:
        if askpass_path:
            try:
                os.unlink(askpass_path)
            except OSError:
                pass
    return BackupRunResult(
        command=cmd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
