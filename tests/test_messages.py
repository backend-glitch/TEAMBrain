import sqlite3

import pytest

from server import messages


def test_post_message_saves_message_to_sqlite(tmp_path, monkeypatch):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)

    result = messages.post_message(
        from_role="backend",
        to_role="frontend",
        type="proposal",
        body="Add a health endpoint.",
        contract_version=1,
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version, "read", created_at
            FROM messages WHERE id = ?
            """,
            (result["id"],),
        ).fetchone()

    assert row is not None
    assert row[:6] == (
        result["id"],
        "backend",
        "frontend",
        "proposal",
        "Add a health endpoint.",
        1,
    )
    assert row[6] == 0
    assert row[7] == result["created_at"]


def test_post_message_rejects_unknown_type(tmp_path, monkeypatch):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)

    with pytest.raises(ValueError, match="Invalid message type"):
        messages.post_message("backend", "frontend", "update", "body", 1)

    assert not database_path.exists()
