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
            "created_at",
        }
    finally:
        connection.close()
