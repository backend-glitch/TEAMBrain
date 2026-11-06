"""Message creation for the TeamBrain MCP server."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from server.database import create_tables
from server.roles import list_roles, validate_role

DB_PATH = Path(__file__).resolve().parent / "teambrain.sqlite3"
VALID_MESSAGE_TYPES = {"request", "proposal", "objection", "accept"}
VALID_STATUS_STATES = {"working", "blocked", "waiting", "done"}


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


def set_status(
    role: str, summary: str, state: str, task: str
) -> dict[str, str]:
    """Save a role's latest status and append a status history entry."""
    if state not in VALID_STATUS_STATES:
        raise ValueError(
            f"Invalid state {state!r}; expected one of: "
            f"{', '.join(sorted(VALID_STATUS_STATES))}"
        )

    updated_at = datetime.now(timezone.utc).isoformat()
    status = {
        "role": role,
        "summary": summary,
        "state": state,
        "task": task,
        "updated_at": updated_at,
    }
    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        validate_role(connection, role)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO team_status (role, summary, state, task, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(role) DO UPDATE SET
                summary = excluded.summary,
                state = excluded.state,
                task = excluded.task,
                updated_at = excluded.updated_at
            """,
            (role, summary, state, task, updated_at),
        )
        connection.execute(
            """
            INSERT INTO status_history (id, role, summary, state, task, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), role, summary, state, task, updated_at),
        )
    return status


def log_work(
    role: str,
    summary: str,
    files: list[str],
    related_proposal_id: str | None = None,
) -> dict[str, str | list[str] | None]:
    """Record finished work for a role."""
    if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
        raise ValueError("files must be a list of strings")

    entry = {
        "id": str(uuid4()),
        "role": role,
        "summary": summary,
        "files": files,
        "related_proposal_id": related_proposal_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        validate_role(connection, role)
        connection.execute(
            """
            INSERT INTO work_log
                (id, role, summary, files, related_proposal_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                role,
                summary,
                json.dumps(files, ensure_ascii=False),
                related_proposal_id,
                entry["created_at"],
            ),
        )
    return entry


def get_team_status() -> dict[str, list[dict[str, object]]]:
    """Return all role statuses, recent status history, and recent work logs."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        role_rows = list_roles(connection)
        latest_rows = {
            row["role"]: dict(row)
            for row in connection.execute("SELECT * FROM team_status").fetchall()
        }
        team = []
        for role_metadata in role_rows:
            role = role_metadata["name"]
            history = connection.execute(
                """
                SELECT summary, state, task, created_at
                FROM status_history WHERE role = ?
                ORDER BY created_at DESC, id DESC LIMIT 10
                """,
                (role,),
            ).fetchall()
            work_rows = connection.execute(
                """
                SELECT id, role, summary, files, related_proposal_id, created_at
                FROM work_log WHERE role = ?
                ORDER BY created_at DESC, id DESC LIMIT 10
                """,
                (role,),
            ).fetchall()
            team.append(
                {
                    "role": role,
                    "description": role_metadata["description"],
                    "color": role_metadata["color"],
                    "active": role_metadata["active"],
                    "current_status": latest_rows.get(role),
                    "status_history": [dict(row) for row in history],
                    "work_log": [
                        {**dict(row), "files": json.loads(row["files"])}
                        for row in work_rows
                    ],
                }
            )
    return {"roles": team}


def post_message(
    from_role: str,
    to_role: str,
    type: str,
    body: str,
    contract_version: int,
    proposal_id: str | None = None,
    handoff_prompt: str | None = None,
    *,
    allow_owner: bool = False,
) -> dict[str, str | int | None]:
    """Validate and save a message, returning its ID, timestamp, and thread ID."""
    if type not in VALID_MESSAGE_TYPES:
        allowed = ", ".join(sorted(VALID_MESSAGE_TYPES))
        raise ValueError(f"Invalid message type {type!r}; expected one of: {allowed}")
    if handoff_prompt is not None:
        if not isinstance(handoff_prompt, str):
            raise ValueError("handoff_prompt must be plain text")
        if len(handoff_prompt) > 2000:
            raise ValueError("handoff_prompt must be at most 2000 characters")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in handoff_prompt):
            raise ValueError("handoff_prompt must be plain text")

    message_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        if not (allow_owner and from_role == "owner"):
            validate_role(connection, from_role)
        validate_role(connection, to_role)
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
                 proposal_id, status, handoff_prompt, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                handoff_prompt,
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


def check_inbox(
    to_role: str, peek: bool = False
) -> list[dict[str, str | int | None]]:
    """Return unread messages; peek leaves them unread."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        create_tables(connection)
        validate_role(connection, to_role)
        latest_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM contracts"
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, handoff_prompt, created_at
            FROM messages
            WHERE to_role = ? AND "read" = 0
            ORDER BY created_at, id
            """,
            (to_role,),
        ).fetchall()
        if not peek:
            connection.executemany(
                'UPDATE messages SET "read" = 1 WHERE id = ?',
                [(row["id"],) for row in rows],
            )

    return _messages_with_contract_warnings(rows, latest_version)


def mark_read(
    message_ids: list[str], to_role: str | None = None
) -> dict[str, list[str]]:
    """Mark supplied unread messages as read, optionally scoped to a recipient role."""
    if not message_ids:
        return {"marked_read": []}

    placeholders = ", ".join("?" for _ in message_ids)
    role_filter = " AND to_role = ?" if to_role is not None else ""
    parameters: list[str] = list(message_ids)
    if to_role is not None:
        parameters.append(to_role)
    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        unread_ids = [
            row[0]
            for row in connection.execute(
                f'SELECT id FROM messages WHERE id IN ({placeholders}) AND "read" = 0'
                f"{role_filter} ORDER BY id",
                parameters,
            ).fetchall()
        ]
        if unread_ids:
            unread_placeholders = ", ".join("?" for _ in unread_ids)
            update_role_filter = " AND to_role = ?" if to_role is not None else ""
            update_parameters: list[str] = list(unread_ids)
            if to_role is not None:
                update_parameters.append(to_role)
            connection.execute(
                f'UPDATE messages SET "read" = 1 WHERE id IN ({unread_placeholders})'
                f"{update_role_filter}",
                update_parameters,
            )

    return {"marked_read": unread_ids}


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
                   proposal_id, status, decision_note, handoff_prompt, "read", created_at
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
