"""
Stepyard database layer.

Features
--------
* One SQLAlchemy engine per database file path (module-level singleton cache).
* ``schema_version`` table for lightweight schema migrations.
* Migrations are applied in ``_init_db()`` so any new schema change is
  written as a numbered function here, not as a raw SQL migration file.

Adding a migration
------------------
1. Write a function ``_m_NNN(session)`` in this module.
2. Append it to ``_MIGRATIONS``.

The migration is applied exactly once - when the stored ``schema_version``
is below the migration's index.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

logger = logging.getLogger("stepyard.storage.database")

# ── Per-process engine cache (one engine per db file) ──────────────────────────
_ENGINE_CACHE: dict[str, object] = {}


def _get_engine(db_path: str):
    """Return a cached SQLAlchemy engine for *db_path*."""
    if db_path not in _ENGINE_CACHE:
        _ENGINE_CACHE[db_path] = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
    return _ENGINE_CACHE[db_path]


# ── Migrations ─────────────────────────────────────────────────────────────────


def _m_001_initial_schema(session: Session) -> None:
    """Baseline - tables already created by SQLModel.metadata.create_all."""


def _m_002_wal_mode(session: Session) -> None:
    """Enable WAL mode and NORMAL synchronous mode for better concurrency."""
    session.execute(text("PRAGMA journal_mode=WAL"))
    session.execute(text("PRAGMA synchronous=NORMAL"))


#: Ordered list of migration callables.  Append new migrations here.
_MIGRATIONS: list[Callable[[Session], None]] = [
    _m_001_initial_schema,
    _m_002_wal_mode,
]


class Database:
    """Thin wrapper around a SQLite database with session management."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.engine = _get_engine(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables (if new DB) and apply any outstanding migrations."""
        SQLModel.metadata.create_all(self.engine)

        with self.get_session() as session:
            # Ensure schema_version table exists.
            session.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_version "
                    "(version INTEGER NOT NULL PRIMARY KEY)"
                )
            )
            session.commit()

            row = session.execute(text("SELECT MAX(version) FROM schema_version")).fetchone()
            current_version: int = row[0] if row and row[0] is not None else 0

        for idx, migration_fn in enumerate(_MIGRATIONS, start=1):
            if idx <= current_version:
                continue
            logger.debug("Applying DB migration %d: %s", idx, migration_fn.__name__)
            with self.get_session() as session:
                try:
                    migration_fn(session)
                    session.execute(
                        text("INSERT OR REPLACE INTO schema_version (version) VALUES (:v)"),
                        {"v": idx},
                    )
                    session.commit()
                except Exception as exc:
                    logger.error(
                        "Migration %d (%s) failed: %s",
                        idx,
                        migration_fn.__name__,
                        exc,
                    )
                    raise

    @contextmanager
    def get_session(self):
        """Yield a SQLModel session, committing on exit or rolling back on error."""
        session = Session(self.engine)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
