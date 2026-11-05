import sqlite3

from server.database import create_tables


def test_create_tables_creates_contracts_and_messages():
    connection = sqlite3.connect(":memory:")
    try:
        create_tables(connection)

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"contracts", "messages"}.issubset(tables)

        contract_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(contracts)")
        }
        message_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(messages)")
        }
        assert contract_columns == {"id", "version", "content", "updated_at"}
        assert message_columns == {
            "id",
            "from_role",
            "to_role",
            "type",
            "body",
            "contract_version",
            "read",
            "proposal_id",
            "status",
            "created_at",
        }
    finally:
        connection.close()


def test_create_tables_migrates_existing_messages_table():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                from_role TEXT NOT NULL,
                to_role TEXT NOT NULL,
                type TEXT NOT NULL,
                body TEXT NOT NULL,
                contract_version INTEGER NOT NULL,
                "read" INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """INSERT INTO messages
               (id, from_role, to_role, type, body, contract_version, created_at)
               VALUES ('existing-proposal', 'frontend', 'backend', 'proposal', 'Keep this', 1, '2026-01-01')"""
        )

        create_tables(connection)

        columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
        proposal_id = connection.execute(
            "SELECT proposal_id FROM messages WHERE id = 'existing-proposal'"
        ).fetchone()[0]
        status = connection.execute(
            "SELECT status FROM messages WHERE id = 'existing-proposal'"
        ).fetchone()[0]
        assert {"proposal_id", "status"}.issubset(columns)
        assert proposal_id == "existing-proposal"
        assert status == "open"
    finally:
        connection.close()
