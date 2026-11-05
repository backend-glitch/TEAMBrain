import sqlite3

from server import messages


def test_get_thread_returns_root_and_replies_in_order(tmp_path, monkeypatch):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)
    proposal = messages.post_message(
        "frontend", "backend", "proposal", "Paginate users", 1
    )
    reply = messages.post_message(
        "backend",
        "frontend",
        "objection",
        "Need cursor semantics",
        1,
        proposal_id=proposal["id"],
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE messages SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?",
            (proposal["id"],),
        )
        connection.execute(
            "UPDATE messages SET created_at = '2026-01-02T00:00:00+00:00' WHERE id = ?",
            (reply["id"],),
        )

    thread = messages.get_thread(proposal["id"])

    assert [message["id"] for message in thread] == [proposal["id"], reply["id"]]
    assert [message["body"] for message in thread] == [
        "Paginate users",
        "Need cursor semantics",
    ]
    assert all(message["proposal_id"] == proposal["id"] for message in thread)


def test_get_thread_returns_empty_list_for_unknown_proposal(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")

    assert messages.get_thread("missing") == []
