"""Search-registry update helpers used by ingest."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)

registry_migrated: set[Path] = set()


def ensure_registry_schema(conn, db_path: Path) -> None:
    """Run publication_number column migration once per db_path per process."""
    if db_path in registry_migrated:
        return
    try:
        conn.execute("SELECT publication_number FROM papers_registry LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE papers_registry ADD COLUMN publication_number TEXT")
    # Ensure UNIQUE partial index exists (matches index.py schema).
    # Pre-migration data may contain duplicates, so catch IntegrityError
    # and fall back to a non-unique index rather than silently breaking.
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_publication_number "
            "ON papers_registry(publication_number) "
            "WHERE publication_number IS NOT NULL AND publication_number != ''"
        )
    except sqlite3.IntegrityError:
        _log.warning(
            "Duplicate publication_number values found; creating non-unique index. Run 'scholaraio index' to rebuild."
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_registry_publication_number "
            "ON papers_registry(publication_number) "
            "WHERE publication_number IS NOT NULL AND publication_number != ''"
        )
    registry_migrated.add(db_path)


def update_registry(cfg, meta, dir_name: str) -> None:
    """Insert/update papers_registry so UUID lookup works immediately."""
    db_path = cfg.index_db
    if not db_path.exists():
        return
    try:
        with sqlite3.connect(db_path) as conn:
            ensure_registry_schema(conn, db_path)
            pub_num = (getattr(meta, "publication_number", "") or "").upper().strip()
            doi_norm = (meta.doi or "").lower().strip()
            try:
                conn.execute(
                    """INSERT INTO papers_registry
                       (id, dir_name, title, doi, publication_number, year, first_author)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           dir_name=excluded.dir_name,
                           title=excluded.title,
                           doi=excluded.doi,
                           publication_number=excluded.publication_number,
                           year=excluded.year,
                           first_author=excluded.first_author""",
                    (
                        meta.id,
                        dir_name,
                        meta.title or "",
                        doi_norm,
                        pub_num,
                        meta.year,
                        meta.first_author_lastname or "",
                    ),
                )
            except sqlite3.IntegrityError as exc:
                err_msg = str(exc).lower()
                if "publication_number" in err_msg and pub_num:
                    _log.warning(
                        "publication_number %r for %s conflicts; storing without it",
                        pub_num,
                        meta.id,
                    )
                    conn.execute(
                        """INSERT INTO papers_registry
                           (id, dir_name, title, doi, publication_number, year, first_author)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET
                               dir_name=excluded.dir_name,
                               title=excluded.title,
                               doi=excluded.doi,
                               publication_number=excluded.publication_number,
                               year=excluded.year,
                               first_author=excluded.first_author""",
                        (
                            meta.id,
                            dir_name,
                            meta.title or "",
                            doi_norm,
                            "",
                            meta.year,
                            meta.first_author_lastname or "",
                        ),
                    )
                else:
                    _log.warning("IntegrityError in _update_registry for %s: %s", meta.id, exc)
    except Exception as e:
        _log.debug("failed to update papers_registry: %s", e)
