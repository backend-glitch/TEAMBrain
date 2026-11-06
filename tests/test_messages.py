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
            SELECT id, from_role, to_role, type, body, contract_version, "read", proposal_id, created_at
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
    assert row[7] == result["proposal_id"] == result["id"]
    assert row[8] == result["created_at"]


def test_post_message_rejects_unknown_type(tmp_path, monkeypatch):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)

    with pytest.raises(ValueError, match="Invalid message type"):
        messages.post_message("backend", "frontend", "update", "body", 1)

    assert not database_path.exists()


def test_post_message_accepts_proposal_id_for_reply(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal = messages.post_message("frontend", "backend", "proposal", "Use pagination", 1)

    reply = messages.post_message(
        "backend", "frontend", "accept", "Agreed", 1, proposal_id=proposal["id"]
    )

    assert reply["proposal_id"] == proposal["id"]


def test_post_message_rejects_unknown_proposal_id(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")

    with pytest.raises(ValueError, match="No original proposal found"):
        messages.post_message(
            "backend", "frontend", "accept", "Agreed", 1, proposal_id="missing"
        )


def test_post_message_stores_contract_version(tmp_path, monkeypatch):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)

    result = messages.post_message(
        "frontend", "backend", "request", "Use contract v7", 7
    )

    with sqlite3.connect(database_path) as connection:
        contract_version = connection.execute(
            "SELECT contract_version FROM messages WHERE id = ?", (result["id"],)
        ).fetchone()[0]

    assert contract_version == 7


def test_post_message_stores_optional_handoff_prompt(tmp_path, monkeypatch):
    database_path = tmp_path / "messages.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)

    with_prompt = messages.post_message(
        "backend", "frontend", "request", "Implement this", 1,
        handoff_prompt="Use this exact handoff.",
    )
    without_prompt = messages.post_message(
        "backend", "frontend", "request", "Existing callers still work", 1
    )

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT id, handoff_prompt FROM messages ORDER BY created_at, id"
        ).fetchall()
    assert (with_prompt["id"], "Use this exact handoff.") in rows
    assert (without_prompt["id"], None) in rows


@pytest.mark.parametrize(
    "prompt, message",
    [
        ("x" * 2001, "at most 2000"),
        ("bad\x00text", "plain text"),
    ],
)
def test_post_message_rejects_invalid_handoff_prompt(
    tmp_path, monkeypatch, prompt, message
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    with pytest.raises(ValueError, match=message):
        messages.post_message(
            "backend", "frontend", "request", "Body", 1,
            handoff_prompt=prompt,
        )
