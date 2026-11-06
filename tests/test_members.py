import sqlite3

import pytest

from server import app as app_module
from server import messages
from server.http_auth import current_role
from server.members import dashboard_members


def test_set_profile_only_changes_the_authenticated_callers_role(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "members.sqlite3")
    token = current_role.set("frontend")
    try:
        result = app_module.set_profile_tool(
            ai_name="Nova", person_name="Alex", machine_label="Work laptop"
        )
    finally:
        current_role.reset(token)

    assert result == {"role": "frontend", "updated": True}
    with sqlite3.connect(messages.DB_PATH) as connection:
        rows = connection.execute("SELECT role, ai_name FROM members").fetchall()
    assert rows == [("frontend", "Nova")]


def test_set_profile_requires_authenticated_role_and_limits_plain_text(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "members.sqlite3")
    with pytest.raises(PermissionError, match="authenticated role token"):
        app_module.set_profile_tool("Name", "Person", "Machine")

    token = current_role.set("backend")
    try:
        with pytest.raises(ValueError, match="at most 40"):
            app_module.set_profile_tool("x" * 41, "Person", "Machine")
        saved = app_module.set_profile_tool(
            "<b>Atlas</b>", "Person", "Machine"
        )
    finally:
        current_role.reset(token)

    assert saved == {"role": "backend", "updated": True}
    with sqlite3.connect(messages.DB_PATH) as connection:
        stored_name = connection.execute(
            "SELECT ai_name FROM members WHERE role = 'backend'"
        ).fetchone()[0]
    assert stored_name == "<b>Atlas</b>"


def test_dashboard_members_includes_all_roles_and_default_names(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "members.sqlite3")
    from server.database import create_tables

    with sqlite3.connect(messages.DB_PATH) as connection:
        create_tables(connection)
        members = dashboard_members(connection)

    assert [member["role"] for member in members] == ["uiux", "frontend", "backend", "qa", "database"]
    assert [member["ai_name"] for member in members] == [
        "uiux AI", "frontend AI", "backend AI", "qa AI", "database AI"
    ]
    assert all(member["last_seen"] is None for member in members)
