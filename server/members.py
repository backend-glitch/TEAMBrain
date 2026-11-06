"""AI member identity and authenticated-request tracking."""

import sqlite3
from datetime import datetime, timezone
from typing import Any

from server.database import create_tables
from server import messages


TEAM_ROLES = ("uiux", "frontend", "backend")


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


def set_profile(role: str, ai_name: str, person_name: str, machine_label: str) -> dict[str, str]:
    """Set the profile belonging to role, without touching activity telemetry."""
    if role not in TEAM_ROLES:
        raise ValueError(f"Invalid role {role!r}; expected one of: {', '.join(TEAM_ROLES)}")
    values = {
        "ai_name": _profile_value("ai_name", ai_name),
        "person_name": _profile_value("person_name", person_name),
        "machine_label": _profile_value("machine_label", machine_label),
    }
    with sqlite3.connect(messages.DB_PATH) as connection:
        create_tables(connection)
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
    if role not in TEAM_ROLES:
        return
    now = _now()
    with sqlite3.connect(messages.DB_PATH) as connection:
        create_tables(connection)
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


def dashboard_members(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return a dashboard view for every role, including unseen roles."""
    connection.row_factory = sqlite3.Row
    try:
        rows = {
            row["role"]: dict(row)
            for row in connection.execute("SELECT * FROM members")
        }
    except sqlite3.OperationalError:
        rows = {}
    sent_counts = {
        row["from_role"]: row["message_count"]
        for row in connection.execute(
            "SELECT from_role, COUNT(*) AS message_count FROM messages GROUP BY from_role"
        )
    }
    result = []
    for role in TEAM_ROLES:
        member = rows.get(role, {})
        result.append(
            {
                "role": role,
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
            }
        )
    return result
