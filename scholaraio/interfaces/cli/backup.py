"""Backup CLI command handler."""

from __future__ import annotations

import argparse
import logging
import shlex
import sys


def _ui(msg: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        from scholaraio.core.log import ui as log_ui

        log_ui(msg)
        return
    cli_mod.ui(msg)


def _log_error(msg: str, *args) -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        logging.getLogger(__name__).error(msg, *args)
        return
    cli_mod._log.error(msg, *args)


def cmd_backup(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.backup import BackupConfigError, build_rsync_command, run_backup

    ui = _ui
    action = getattr(args, "backup_action", None)
    if action == "list":
        ui(f"Backup source directory: {cfg.backup_source_dir}")
        if not cfg.backup.targets:
            ui("No backup targets configured.")
            return
        ui()
        for name, target in sorted(cfg.backup.targets.items()):
            status = "enabled" if target.enabled else "disabled"
            remote = f"{target.user}@{target.host}" if target.user else target.host
            ui(f"[{name}] {status}")
            ui(f"  Remote: {remote}:{target.path}")
            ui(f"  Mode: {target.mode}  |  compress: {'on' if target.compress else 'off'}")
            if target.exclude:
                ui(f"  Exclude: {', '.join(target.exclude)}")
        return

    if action == "run":
        try:
            cmd = build_rsync_command(cfg, args.target, dry_run=args.dry_run)
            ui("About to run backup command: ")
            ui("  " + shlex.join(cmd))
            result = run_backup(cfg, args.target, dry_run=args.dry_run)
        except BackupConfigError as exc:
            _log_error("%s", exc)
            sys.exit(1)

        if result.stdout.strip():
            ui()
            ui(result.stdout.rstrip())
        if result.stderr.strip():
            ui()
            ui(result.stderr.rstrip())
        if result.returncode != 0:
            _print_backup_failure_guidance(cfg, args.target, result.stderr)
            _log_error("Backup failed, exit code: %s", result.returncode)
            sys.exit(result.returncode)
        if args.dry_run:
            ui()
            ui("Dry run complete: no files were transferred.")
        else:
            ui()
            ui("Backup completed.")
        return

    _log_error("Unknown backup subcommand: %s", action)
    sys.exit(1)


def _print_backup_failure_guidance(cfg, target_name: str, stderr: str) -> None:
    ui = _ui
    stderr = (stderr or "").strip()
    if not stderr:
        return

    target = cfg.backup.targets.get(target_name)
    host = target.host if target and target.host else "<host>"
    user = target.user if target and target.user else "<user>"
    port = target.port if target and target.port else 22
    identity_file = target.identity_file if target and target.identity_file else "~/.ssh/id_ed25519"
    remote = f"{user}@{host}" if user != "<user>" else host
    lower = stderr.lower()

    auth_error = "permission denied" in lower or "publickey" in lower
    host_key_error = "host key verification failed" in lower or "host key is unknown" in lower
    if not auth_error and not host_key_error:
        return

    ui()
    ui(
        "Hint: `scholaraio backup run` forces non-interactive SSH (`BatchMode=yes`), and will not wait for passwords or host-key confirmation in the CLI."
    )
    ui("Complete one-time setup with these steps: ")
    ui("  1. Fill in SSH settings for this target in `config.local.yaml`: ")
    ui("     backup:")
    ui("       targets:")
    ui(f"         {target_name}:")
    ui(f"           host: {host}")
    ui(f"           user: {user}")
    ui(f"           port: {port}")
    ui(f"           identity_file: {identity_file}  # recommended: key-based login")
    ui("           password: <ssh-password>  # fallback: keep only in config.local.yaml")
    if host_key_error:
        ui(f"  2. Write `known_hosts` first: `ssh-keyscan -p {port} {host} >> ~/.ssh/known_hosts`")
    else:
        ui(
            "  2. `backup run` does not support entering SSH passwords interactively; prepare keys or store the password in `config.local.yaml` first."
        )
        ui(
            f"     If this is the first connection and the host is not trusted yet, run: `ssh-keyscan -p {port} {host} >> ~/.ssh/known_hosts`"
        )
    ui(f"  3. If using keys, verify first: `ssh -i {identity_file} -p {port} {remote} true`")
    ui("     If using a password, save `config.local.yaml` and retry backup dry-run.")
    ui(f"  4. After verification passes, retry: `scholaraio backup run {target_name} --dry-run`")
