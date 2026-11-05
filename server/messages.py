"""Message creation for the TeamBrain MCP server."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from server.database import create_tables

DB_PATH = Path(__file__).resolve().parent / "teambrain.sqlite3"
VALID_MESSAGE_TYPES = {"request", "proposal", "objection", "accept"}


def _messages_with_contract_warnings(
    rows: list[sqlite3.Row], latest_version: int
) -> list[dict[str, str | int | None]]:
    """Add a warning to messages written against an older contract version."""
    messages_with_warnings = []
    for row in rows:
        message = dict(row)
        if message["contract_version"] < latest_version:
            message["warning"] = (
                f"Message uses contract version {message['contract_version']}; "
                f"latest contract version is {latest_version}."
            )
        messages_with_warnings.append(message)
    return messages_with_warnings


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
        latest_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM contracts"
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, created_at
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

    return _messages_with_contract_warnings(rows, latest_version)


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


def write_contract(content: str) -> dict[str, str | int]:
    """Store contract content as a new version, starting at version 1."""
    contract_id = str(uuid4())
    updated_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        connection.execute("BEGIN IMMEDIATE")
        latest_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM contracts"
        ).fetchone()[0]
        version = latest_version + 1
        connection.execute(
            """
            INSERT INTO contracts (id, version, content, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (contract_id, version, content, updated_at),
        )

    return {
        "id": contract_id,
        "version": version,
        "content": content,
        "updated_at": updated_at,
    }


def get_thread(proposal_id: str) -> list[dict[str, str | int | None]]:
    """Return the proposal and its replies in chronological order."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        latest_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM contracts"
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, "read", created_at
            FROM messages
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()

    return _messages_with_contract_warnings(rows, latest_version)


def list_escalated() -> list[dict[str, str | int | list[dict[str, str]]]]:
    """List unresolved escalated proposals with concise role-based positions."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        proposals = connection.execute(
            """
            SELECT id, from_role, contract_version
            FROM messages
            WHERE type = 'proposal' AND status = 'escalated'
            ORDER BY created_at, id
            """
        ).fetchall()

        escalated = []
        for proposal in proposals:
            thread = connection.execute(
                """
                SELECT from_role, type, body
                FROM messages
                WHERE proposal_id = ?
                ORDER BY created_at, id
                """,
                (proposal["id"],),
            ).fetchall()
            role_positions: dict[str, list[str]] = {}
            for message in thread:
                role_positions.setdefault(message["from_role"], []).append(
                    f"{message['type']}: {message['body']}"
                )

            positions = []
            for role, statements in role_positions.items():
                summary = " | ".join(statements)
                if len(summary) > 240:
                    summary = summary[:237].rstrip() + "..."
                positions.append({"role": role, "summary": summary})

            escalated.append(
                {
                    "proposal_id": proposal["id"],
                    "contract_version": proposal["contract_version"],
                    "positions": positions,
                }
            )

    return escalated


def human_decision(
    proposal_id: str,
    decision: Literal["accept", "reject"],
    note: str | None = None,
) -> dict[str, str | None]:
    """Resolve an escalated proposal with a human accept or reject decision."""
    if decision not in {"accept", "reject"}:
        raise ValueError("decision must be 'accept' or 'reject'")

    status = "accepted" if decision == "accept" else "rejected"
    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        connection.execute("BEGIN IMMEDIATE")
        proposal = connection.execute(
            "SELECT status FROM messages WHERE id = ? AND type = 'proposal'",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            return {
                "proposal_id": proposal_id,
                "error": f"Unknown proposal_id '{proposal_id}'.",
            }
        if proposal[0] != "escalated":
            return {
                "proposal_id": proposal_id,
                "error": (
                    f"Proposal is '{proposal[0]}', only 'escalated' proposals "
                    "can receive a human decision."
                ),
            }
        connection.execute(
            "UPDATE messages SET status = ?, decision_note = ? WHERE id = ?",
            (status, note, proposal_id),
        )

    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "status": status,
        "note": note,
    }
