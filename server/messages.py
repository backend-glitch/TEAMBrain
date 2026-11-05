"""Message creation for the TeamBrain MCP server."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from server.database import create_tables

DB_PATH = Path(__file__).resolve().parent / "teambrain.sqlite3"
VALID_MESSAGE_TYPES = {"request", "proposal", "objection", "accept"}


def post_message(
    from_role: str,
    to_role: str,
    type: str,
    body: str,
    contract_version: int,
) -> dict[str, str | int]:
    """Validate and save a message, returning its assigned ID and timestamp."""
    if type not in VALID_MESSAGE_TYPES:
        allowed = ", ".join(sorted(VALID_MESSAGE_TYPES))
        raise ValueError(f"Invalid message type {type!r}; expected one of: {allowed}")

    message_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        connection.execute(
            """
            INSERT INTO messages
                (id, from_role, to_role, type, body, contract_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, from_role, to_role, type, body, contract_version, created_at),
        )

    return {"id": message_id, "created_at": created_at}


def check_inbox(to_role: str) -> list[dict[str, str | int]]:
    """Return unread messages for a role and mark them read."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version, created_at
            FROM messages
            WHERE to_role = ? AND "read" = 0
            ORDER BY created_at, id
            """,
            (to_role,),
        ).fetchall()
        connection.executemany(
            'UPDATE messages SET "read" = 1 WHERE id = ?',
            [(row["id"],) for row in rows],
        )

    return [dict(row) for row in rows]


def read_contract() -> dict[str, str | int] | None:
    """Return the contract with the highest version, if one has been stored."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        row = connection.execute(
            """
            SELECT id, version, content, updated_at
            FROM contracts
            ORDER BY version DESC, updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    return dict(row) if row is not None else None
