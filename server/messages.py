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
    proposal_id: str | None = None,
) -> dict[str, str | int | None]:
    """Validate and save a message, returning its ID, timestamp, and thread ID."""
    if type not in VALID_MESSAGE_TYPES:
        allowed = ", ".join(sorted(VALID_MESSAGE_TYPES))
        raise ValueError(f"Invalid message type {type!r}; expected one of: {allowed}")

    message_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        if proposal_id is None and type == "proposal":
            proposal_id = message_id
        elif proposal_id is not None:
            root = connection.execute(
                "SELECT 1 FROM messages WHERE id = ? AND type = 'proposal'",
                (proposal_id,),
            ).fetchone()
            if root is None:
                raise ValueError(
                    f"No original proposal found for proposal_id {proposal_id!r}"
                )

        proposal_status = "open" if type == "proposal" and proposal_id == message_id else None
        connection.execute(
            """
            INSERT INTO messages
                (id, from_role, to_role, type, body, contract_version,
                 proposal_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                from_role,
                to_role,
                type,
                body,
                contract_version,
                proposal_id,
                proposal_status,
                created_at,
            ),
        )

        if proposal_id is not None and type == "accept":
            connection.execute(
                "UPDATE messages SET status = 'accepted' WHERE id = ?",
                (proposal_id,),
            )
        elif proposal_id is not None and type == "objection":
            current_status = connection.execute(
                "SELECT status FROM messages WHERE id = ?", (proposal_id,)
            ).fetchone()[0]
            if current_status != "accepted":
                objection_count = connection.execute(
                    "SELECT COUNT(*) FROM messages "
                    "WHERE proposal_id = ? AND type = 'objection'",
                    (proposal_id,),
                ).fetchone()[0]
                if objection_count >= 3:
                    connection.execute(
                        "UPDATE messages SET status = 'escalated' WHERE id = ?",
                        (proposal_id,),
                    )

    return {
        "id": message_id,
        "created_at": created_at,
        "proposal_id": proposal_id,
        "status": proposal_status,
    }


def check_inbox(to_role: str) -> list[dict[str, str | int | None]]:
    """Return unread messages for a role and mark them read."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, created_at
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


def get_thread(proposal_id: str) -> list[dict[str, str | int | None]]:
    """Return the proposal and its replies in chronological order."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, "read", created_at
            FROM messages
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()

    return [dict(row) for row in rows]
