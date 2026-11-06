import sqlite3

from server import messages


def test_check_inbox_returns_and_marks_only_matching_unread_messages(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)
    first = messages.post_message("backend", "frontend", "request", "First", 1)
    messages.post_message("uiux", "backend", "proposal", "Other role", 1)

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


def test_check_inbox_peek_leaves_messages_unread(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    first = messages.post_message("backend", "frontend", "request", "First", 1)

    peeked = messages.check_inbox("frontend", peek=True)
    peeked_again = messages.check_inbox("frontend", peek=True)

    assert [message["id"] for message in peeked] == [first["id"]]
    assert [message["id"] for message in peeked_again] == [first["id"]]
    with sqlite3.connect(messages.DB_PATH) as connection:
        read_state = connection.execute(
            'SELECT "read" FROM messages WHERE id = ?', (first["id"],)
        ).fetchone()[0]
    assert read_state == 0


def test_mark_read_marks_only_requested_unread_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    first = messages.post_message("backend", "frontend", "request", "First", 1)
    second = messages.post_message("uiux", "frontend", "request", "Second", 1)

    result = messages.mark_read([first["id"], "missing-id"])

    assert result == {"marked_read": [first["id"]]}
    inbox = messages.check_inbox("frontend", peek=True)
    assert [message["id"] for message in inbox] == [second["id"]]
    assert messages.mark_read([first["id"], second["id"]]) == {
        "marked_read": [second["id"]]
    }
    assert messages.check_inbox("frontend", peek=True) == []


def test_mark_read_can_be_scoped_to_recipient_role(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    frontend_message = messages.post_message(
        "backend", "frontend", "request", "For frontend", 1
    )
    backend_message = messages.post_message(
        "frontend", "backend", "request", "For backend", 1
    )

    result = messages.mark_read(
        [frontend_message["id"], backend_message["id"]], to_role="frontend"
    )

    assert result == {"marked_read": [frontend_message["id"]]}
    assert messages.check_inbox("frontend", peek=True) == []
    backend_inbox = messages.check_inbox("backend", peek=True)
    assert [message["id"] for message in backend_inbox] == [backend_message["id"]]
