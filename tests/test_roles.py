import sqlite3

import pytest

from server import messages
from server.database import create_tables
from server.roles import create_role, list_roles_tool


def test_unknown_roles_are_rejected_for_messages_and_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "roles.sqlite3")

    with pytest.raises(ValueError, match="Invalid role"):
        messages.post_message("ghost", "frontend", "request", "No", 1)
    with pytest.raises(ValueError, match="Invalid role"):
        messages.post_message("backend", "ghost", "request", "No", 1)
    with pytest.raises(ValueError, match="Invalid role"):
        messages.check_inbox("ghost", peek=True)


def test_new_active_role_gets_its_own_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "roles.sqlite3")
    create_role("qa2", "QA team", "#87d7e8")

    sent = messages.post_message("backend", "qa2", "proposal", "Check release", 1)
    inbox = messages.check_inbox("qa2", peek=True)

    assert len(inbox) == 1
    assert inbox[0]["id"] == sent["id"]
    assert inbox[0]["to_role"] == "qa2"


def test_list_roles_is_read_only_metadata_and_includes_seeded_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "roles.sqlite3")
    with sqlite3.connect(messages.DB_PATH) as connection:
        create_tables(connection)
    roles = list_roles_tool()

    assert [role["name"] for role in roles] == [
        "uiux", "frontend", "backend", "qa", "database"
    ]
    assert next(role for role in roles if role["name"] == "backend")["can_write_contract"]
    assert not next(role for role in roles if role["name"] == "qa")["active"]
    with sqlite3.connect(messages.DB_PATH) as connection:
        before = connection.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
    list_roles_tool()
    with sqlite3.connect(messages.DB_PATH) as connection:
        after = connection.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
    assert before == after == 5


def test_dynamic_role_migration_preserves_existing_member_profile(tmp_path):
    connection = sqlite3.connect(tmp_path / "legacy.sqlite3")
    connection.execute(
        """CREATE TABLE members (
            role TEXT PRIMARY KEY CHECK (role IN ('uiux', 'frontend', 'backend')),
            ai_name TEXT, person_name TEXT, machine_label TEXT, client_name TEXT,
            client_version TEXT, last_ip TEXT, first_seen TEXT, last_seen TEXT,
            last_tool TEXT, request_count INTEGER NOT NULL DEFAULT 0,
            run_mode TEXT NOT NULL DEFAULT 'manual', tool_label TEXT NOT NULL DEFAULT ''
        )"""
    )
    connection.execute(
        """INSERT INTO members
           (role, ai_name, person_name, machine_label, client_name, client_version,
            last_ip, first_seen, last_seen, last_tool, request_count, run_mode, tool_label)
           VALUES ('frontend', 'Nova', 'Alex', 'Laptop', 'Cursor', '2.1',
                   '192.0.2.8', 'first', 'last', 'post_message', 7, 'manual', 'Cursor')"""
    )

    create_tables(connection)
    connection.execute(
        "INSERT INTO members (role, ai_name) VALUES ('qa', 'QA helper')"
    )
    row = connection.execute(
        """SELECT ai_name, person_name, machine_label, client_name, client_version,
                  last_ip, first_seen, last_seen, last_tool, request_count,
                  run_mode, tool_label FROM members WHERE role='frontend'"""
    ).fetchone()

    assert row == (
        "Nova", "Alex", "Laptop", "Cursor", "2.1", "192.0.2.8", "first",
        "last", "post_message", 7, "manual", "Cursor",
    )
    connection.close()
