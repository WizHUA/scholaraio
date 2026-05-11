"""Shared CLI path helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from scholaraio.core.log import ui as _default_ui


def _ui(message: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        _default_ui(message)
        return
    cli_mod.ui(message)


def _resolve_ws_paper_ids(args: argparse.Namespace, cfg) -> set[str] | None:
    ws_name = getattr(args, "ws", None)
    if not ws_name:
        return None
    from scholaraio.projects import workspace

    if not workspace.validate_workspace_name(ws_name):
        raise ValueError(f"Invalid workspace name: {ws_name}")

    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        workspace_root = _workspace_root
    else:
        workspace_root = cli_mod._workspace_root
    ws_dir = workspace_root(cfg) / ws_name
    pids = workspace.read_paper_ids(ws_dir)
    if not pids:
        _ui(f"Workspace {ws_name} is empty or does not exist")
    return pids


def _workspace_root(cfg) -> Path:
    workspace_dir = getattr(cfg, "workspace_dir", None)
    if workspace_dir is not None:
        return Path(workspace_dir)
    return Path(getattr(cfg, "_root", Path.cwd())) / "workspace"


def _default_docx_output_path(cfg) -> Path:
    docx_output_path = getattr(cfg, "workspace_docx_output_path", None)
    if docx_output_path is not None:
        return Path(docx_output_path)
    return _workspace_root(cfg) / "output.docx"


def _workspace_figures_dir(cfg) -> Path:
    figures_dir = getattr(cfg, "workspace_figures_dir", None)
    if figures_dir is not None:
        return Path(figures_dir)
    return _workspace_root(cfg) / "figures"


def _default_inbox_dir(cfg) -> Path:
    inbox_dir = getattr(cfg, "inbox_dir", None)
    if inbox_dir is not None:
        return Path(inbox_dir)
    return Path(getattr(cfg, "_root", Path.cwd())) / "data" / "inbox"
