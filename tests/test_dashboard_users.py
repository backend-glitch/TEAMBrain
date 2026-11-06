import sqlite3

import pytest

from server import dashboard_users, messages
from server.database import create_tables


def test_password_hash_uses_scrypt_with_distinct_per_user_salts():
    first = dashboard_users.hash_password("correct horse battery staple")
    second = dashboard_users.hash_password("correct horse battery staple")

    assert first.startswith("scrypt$16384$8$1$")
    assert first != second
    assert dashboard_users.verify_password("correct horse battery staple", first)
    assert not dashboard_users.verify_password("wrong password", first)


def test_dashboard_user_storage_keeps_hash_private_and_links_member_role(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "dashboard-users.sqlite3")
    with sqlite3.connect(messages.DB_PATH) as connection:
        create_tables(connection)

    created = dashboard_users.create_user(
        "Front.End", "correct horse battery staple", "member", "frontend"
    )

    assert created["username"] == "front.end"
    assert created["linked_role"] == "frontend"
    assert dashboard_users.authenticate_user(
        "FRONT.END", "correct horse battery staple"
    ) == {
        "username": "front.end",
        "role_scope": "member",
        "linked_role": "frontend",
    }
    assert dashboard_users.authenticate_user("front.end", "wrong password") is None
    assert "password_hash" not in dashboard_users.list_users()[0]


def test_dashboard_user_password_and_role_inputs_are_validated(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "users-validation.sqlite3")
    with sqlite3.connect(messages.DB_PATH) as connection:
        create_tables(connection)

    with pytest.raises(ValueError, match="12 and 1024"):
        dashboard_users.create_user("valid-user", "short", "owner")
    with pytest.raises(ValueError, match="existing role"):
        dashboard_users.create_user(
            "valid-user", "correct horse battery staple", "member", "missing"
        )
