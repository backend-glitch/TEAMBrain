import sqlite3

from server import messages


def test_check_inbox_returns_and_marks_only_matching_unread_messages(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)
    first = messages.post_message("backend", "frontend", "request", "First", 1)
    messages.post_message("design", "backend", "proposal", "Other role", 1)

    inbox = messages.check_inbox("frontend")

    assert [message["id"] for message in inbox] == [first["id"]]
    assert inbox[0]["body"] == "First"
    assert messages.check_inbox("frontend") == []
    with sqlite3.connect(database_path) as connection:
        read_states = connection.execute(
            'SELECT to_role, "read" FROM messages ORDER BY body'
        ).fetchall()
    assert read_states == [("frontend", 1), ("backend", 0)]


def test_check_inbox_warns_when_message_uses_older_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    messages.write_contract("Contract version one")
    old_message = messages.post_message(
        "frontend", "backend", "request", "Written against v1", 1
    )
    messages.write_contract("Contract version two")

    inbox = messages.check_inbox("backend")

    assert inbox[0]["id"] == old_message["id"]
    assert inbox[0]["warning"] == (
        "Message uses contract version 1; latest contract version is 2."
    )
