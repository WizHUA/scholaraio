"""Path helper functions for ingest pipeline orchestration."""

from __future__ import annotations

from pathlib import Path

from scholaraio.core.config import Config


def cfg_dir(cfg: Config, attr: str, *legacy_parts: str) -> Path:
    path = getattr(cfg, attr, None)
    if path is not None:
        return Path(path)
    return Path(getattr(cfg, "_root", Path.cwd())).joinpath(*legacy_parts)


def inbox_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "inbox_dir", "data", "spool", "inbox")


def doc_inbox_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "doc_inbox_dir", "data", "spool", "inbox-doc")


def thesis_inbox_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "thesis_inbox_dir", "data", "spool", "inbox-thesis")


def patent_inbox_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "patent_inbox_dir", "data", "spool", "inbox-patent")


def proceedings_inbox_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "proceedings_inbox_dir", "data", "spool", "inbox-proceedings")


def pending_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "pending_dir", "data", "spool", "pending")


def proceedings_dir(cfg: Config) -> Path:
    return cfg_dir(cfg, "proceedings_dir", "data", "libraries", "proceedings")
