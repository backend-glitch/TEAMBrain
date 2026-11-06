"""AI member identity and authenticated-request tracking."""

import sqlite3
from datetime import datetime, timezone
from typing import Any

from server.database import create_tables
from server.roles import list_roles, validate_role
from server.storage import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile_value(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be plain text")
    value = value.strip()
    if len(value) > 40:
        raise ValueError(f"{name} must be at most 40 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} must be plain text")
    return value


def _run_settings(run_mode: str, tool_label: str) -> tuple[str, str]:
    if not isinstance(run_mode, str) or run_mode not in {"manual", "headless"}:
        raise ValueError("run_mode must be 'manual' or 'headless'")
    if not isinstance(tool_label, str):
        raise ValueError("tool_label must be plain text")
    tool_label = tool_label.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in tool_label):
        raise ValueError("tool_label must be plain text")
    return run_mode, tool_label


def set_profile(role: str, ai_name: str, person_name: str, machine_label: str) -> dict[str, str]:
    """Set the profile belonging to role, without touching activity telemetry."""
    values = {
        "ai_name": _profile_value("ai_name", ai_name),
        "person_name": _profile_value("person_name", person_name),
        "machine_label": _profile_value("machine_label", machine_label),
    }
    with connect() as connection:
        create_tables(connection)
        validate_role(connection, role, active_only=False)
        connection.execute(
            """
            INSERT INTO members (role, ai_name, person_name, machine_label)
            VALUES (:role, :ai_name, :person_name, :machine_label)
            ON CONFLICT(role) DO UPDATE SET
                ai_name = excluded.ai_name,
                person_name = excluded.person_name,
                machine_label = excluded.machine_label
            """,
            {"role": role, **values},
        )
    return {"role": role, **values}


def set_run_settings(role: str, run_mode: str, tool_label: str) -> dict[str, str]:
    """Set dashboard run-mode metadata; headless execution remains unimplemented."""
    run_mode, tool_label = _run_settings(run_mode, tool_label)
    with connect() as connection:
        create_tables(connection)
        validate_role(connection, role, active_only=False)
        connection.execute(
            """
            INSERT INTO members (role, run_mode, tool_label)
            VALUES (?, ?, ?)
            ON CONFLICT(role) DO UPDATE SET
                run_mode = excluded.run_mode,
                tool_label = excluded.tool_label
            """,
            (role, run_mode, tool_label),
        )
    return {"role": role, "run_mode": run_mode, "tool_label": tool_label}


def set_dashboard_member(
    role: str,
    ai_name: str,
    person_name: str,
    machine_label: str,
    run_mode: str,
    tool_label: str,
) -> dict[str, str]:
    """Atomically update a dashboard profile and its run-mode settings."""
    values = {
        "ai_name": _profile_value("ai_name", ai_name),
        "person_name": _profile_value("person_name", person_name),
        "machine_label": _profile_value("machine_label", machine_label),
    }
    run_mode, tool_label = _run_settings(run_mode, tool_label)
    with connect() as connection:
        create_tables(connection)
        validate_role(connection, role, active_only=False)
        connection.execute(
            """
            INSERT INTO members (
                role, ai_name, person_name, machine_label, run_mode, tool_label
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(role) DO UPDATE SET
                ai_name = excluded.ai_name,
                person_name = excluded.person_name,
                machine_label = excluded.machine_label,
                run_mode = excluded.run_mode,
                tool_label = excluded.tool_label
            """,
            (role, values["ai_name"], values["person_name"], values["machine_label"], run_mode, tool_label),
        )
    return {"role": role, **values, "run_mode": run_mode, "tool_label": tool_label}


def upsert_authenticated_request(
    role: str,
    *,
    last_ip: str | None,
    last_tool: str | None = None,
    client_name: str | None = None,
    client_version: str | None = None,
    count_request: bool = True,
) -> None:
    """Record activity metadata only; request bodies and tokens are never stored."""
    now = _now()
    with connect() as connection:
        create_tables(connection)
        try:
            validate_role(connection, role)
        except ValueError:
            return
        if not count_request:
            connection.execute(
                """
                UPDATE members SET
                    client_name = COALESCE(?, client_name),
                    client_version = COALESCE(?, client_version),
                    last_tool = COALESCE(?, last_tool)
                WHERE role = ?
                """,
                (client_name, client_version, last_tool, role),
            )
            return
        connection.execute(
            """
            INSERT INTO members (
                role, client_name, client_version, last_ip, first_seen,
                last_seen, last_tool, request_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(role) DO UPDATE SET
                client_name = COALESCE(excluded.client_name, members.client_name),
                client_version = COALESCE(excluded.client_version, members.client_version),
                last_ip = COALESCE(excluded.last_ip, members.last_ip),
                first_seen = COALESCE(members.first_seen, excluded.first_seen),
                last_seen = excluded.last_seen,
                last_tool = COALESCE(excluded.last_tool, members.last_tool),
                request_count = members.request_count + 1
            """,
            (role, client_name, client_version, last_ip, now, now, last_tool),
        )


def dashboard_members(
    connection: sqlite3.Connection,
    *,
    role_rows: list[dict[str, Any]] | None = None,
    messages: list[sqlite3.Row] | None = None,
) -> list[dict[str, Any]]:
    """Return a dashboard view for every role, including unseen roles."""
    connection.row_factory = sqlite3.Row
    rows = {
        row["role"]: dict(row)
        for row in connection.execute("SELECT * FROM members")
    }
    role_rows = role_rows if role_rows is not None else list_roles(connection)
    if messages is None:
        messages = connection.execute(
            '''SELECT id, from_role, to_role, type, body, contract_version,
                      proposal_id, status, "read", handoff_prompt, created_at
               FROM messages ORDER BY created_at, id'''
        ).fetchall()
    sent_counts: dict[str, int] = {}
    unread_counts: dict[str, int] = {}
    open_proposals = {
        row["id"]
        for row in messages
        if row["type"] == "proposal" and row["status"] == "open"
    }
    unread_messages: dict[str, list[dict[str, Any]]] = {}
    waiting_roles = set()
    for row in messages:
        sent_counts[row["from_role"]] = sent_counts.get(row["from_role"], 0) + 1
        if not row["read"]:
            unread_counts[row["to_role"]] = unread_counts.get(row["to_role"], 0) + 1
            if row["proposal_id"] in open_proposals:
                waiting_roles.add(row["to_role"])
            unread_messages.setdefault(row["to_role"], []).append(
                {
                    key: row[key]
                    for key in (
                        "id", "from_role", "to_role", "type", "body",
                        "contract_version", "proposal_id", "handoff_prompt", "created_at",
                    )
                }
            )
    for rows_for_role in unread_messages.values():
        rows_for_role.sort(
            key=lambda row: (row["created_at"], row["id"]), reverse=True
        )
    result = []
    for role_metadata in role_rows:
        role = role_metadata["name"]
        member = rows.get(role, {})
        result.append(
            {
                "role": role,
                "description": role_metadata["description"],
                "color": role_metadata["color"],
                "active": role_metadata["active"],
                "token_env_var": role_metadata["token_env_var"],
                "can_write_contract": role_metadata["can_write_contract"],
                "ai_name": member.get("ai_name") or f"{role} AI",
                "person_name": member.get("person_name") or "",
                "machine_label": member.get("machine_label") or "",
                "client_name": member.get("client_name") or "",
                "client_version": member.get("client_version") or "",
                "last_ip": member.get("last_ip") or "",
                "first_seen": member.get("first_seen"),
                "last_seen": member.get("last_seen"),
                "last_tool": member.get("last_tool") or "",
                "request_count": member.get("request_count", 0),
                "messages_sent": sent_counts.get(role, 0),
                "unread_count": unread_counts.get(role, 0),
                "waiting_on_open_proposal": role in waiting_roles,
                "run_mode": member.get("run_mode") or "manual",
                "tool_label": member.get("tool_label") or "",
                "unread_messages": unread_messages.get(role, []),
            }
        )
    return result
