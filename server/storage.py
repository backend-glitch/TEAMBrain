"""Small DB-API compatibility layer for local SQLite and hosted PostgreSQL."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any


_POSTGRES_SCHEMA_LOCK = threading.Lock()
_POSTGRES_SCHEMA_READY = False


def postgres_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


class _HybridRow(dict):
    """Mapping row that also preserves sqlite3.Row's numeric indexing."""

    def __init__(self, names: list[str], values: tuple[Any, ...]):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _hybrid_row_factory(cursor):
    names = [column.name for column in (cursor.description or ())]
    return lambda values: _HybridRow(names, values)


def _postgres_sql(sql: str) -> str:
    """Translate the small SQLite SQL subset used by the application."""
    sql = re.sub(r"\bBEGIN\s+IMMEDIATE\b", "BEGIN", sql, flags=re.IGNORECASE)
    ignore_insert = bool(
        re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.IGNORECASE)
    )
    sql = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        sql,
        flags=re.IGNORECASE,
    )
    if ignore_insert and not re.search(r"\bON\s+CONFLICT\b", sql, re.IGNORECASE):
        sql = re.sub(r";\s*$", "", sql.rstrip()) + " ON CONFLICT DO NOTHING"
    sql = re.sub(r"(?<!:):([A-Za-z_][A-Za-z_0-9]*)", r"%(\1)s", sql)
    sql = sql.replace("?", "%s")
    sql = re.sub(
        r"\bORDER\s+BY\s+rowid\b",
        "ORDER BY CASE name WHEN 'uiux' THEN 0 WHEN 'frontend' THEN 1 "
        "WHEN 'backend' THEN 2 WHEN 'qa' THEN 3 WHEN 'database' THEN 4 "
        "ELSE 5 END, name",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


class _PostgresConnection:
    """Adapter for the sqlite-style calls shared by the server modules."""

    def __init__(self, connection):
        self._connection = connection

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        from psycopg.rows import tuple_row

        self._connection.row_factory = _hybrid_row_factory if value is not None else tuple_row

    def execute(self, sql: str, parameters=()):
        return self._connection.execute(_postgres_sql(sql), parameters)

    def executemany(self, sql: str, parameters):
        cursor = self._connection.cursor()
        cursor.executemany(_postgres_sql(sql), parameters)
        return cursor

    def executescript(self, script: str):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def connect(database_path: str | Path | None = None, *, readonly: bool = False):
    """Open the configured database, preferring DATABASE_URL when provided."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        import psycopg
        from psycopg.rows import tuple_row

        # Prisma's pooled URL uses PgBouncer transaction pooling; avoid
        # server-side prepared statements that may not survive pool handoff.
        kwargs = {"row_factory": tuple_row, "prepare_threshold": None}
        return _PostgresConnection(psycopg.connect(url, **kwargs))

    if database_path is None:
        from server.messages import DB_PATH

        database_path = DB_PATH
    path = Path(database_path)
    if readonly:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def is_postgres(connection) -> bool:
    return isinstance(connection, _PostgresConnection)


def is_integrity_error(error: BaseException) -> bool:
    if isinstance(error, sqlite3.IntegrityError):
        return True
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(error, psycopg.IntegrityError)


def begin_write(connection) -> None:
    """Start a serialized write transaction, matching SQLite's old behavior."""
    if is_postgres(connection):
        connection.execute("SELECT pg_advisory_xact_lock(716298413)")
    else:
        connection.execute("BEGIN IMMEDIATE")


def mark_postgres_schema_ready() -> None:
    global _POSTGRES_SCHEMA_READY
    _POSTGRES_SCHEMA_READY = True


def postgres_schema_ready() -> bool:
    return _POSTGRES_SCHEMA_READY


def postgres_schema_lock():
    return _POSTGRES_SCHEMA_LOCK
