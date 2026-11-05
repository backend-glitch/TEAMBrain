"""SQLite schema setup for TeamBrain."""

import sqlite3


def create_tables(connection: sqlite3.Connection) -> None:
    """Create the contracts and messages tables if they do not exist."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS contracts (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            from_role TEXT NOT NULL,
            to_role TEXT NOT NULL,
            type TEXT NOT NULL,
            body TEXT NOT NULL,
            contract_version INTEGER NOT NULL,
            "read" INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.commit()
