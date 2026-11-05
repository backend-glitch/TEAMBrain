import sqlite3

from server import messages
from server.database import create_tables


def test_read_contract_returns_highest_version(tmp_path, monkeypatch):
    database_path = tmp_path / "contracts.sqlite3"
    monkeypatch.setattr(messages, "DB_PATH", database_path)
    with sqlite3.connect(database_path) as connection:
        create_tables(connection)
        connection.executemany(
            "INSERT INTO contracts (id, version, content, updated_at) VALUES (?, ?, ?, ?)",
            [
                ("v1", 1, "Old contract", "2026-01-01T00:00:00+00:00"),
                ("v2", 2, "Latest contract", "2026-02-01T00:00:00+00:00"),
            ],
        )

    assert messages.read_contract() == {
        "id": "v2",
        "version": 2,
        "content": "Latest contract",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }


def test_read_contract_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "contracts.sqlite3")

    assert messages.read_contract() is None
