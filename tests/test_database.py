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
        assert {
            "contracts",
            "messages",
            "team_status",
            "status_history",
            "work_log",
            "members",
        }.issubset(tables)

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
            "decision_note",
            "handoff_prompt",
            "created_at",
        }
        member_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(members)")
        }
        assert member_columns == {
            "role",
            "ai_name",
            "person_name",
            "machine_label",
            "client_name",
            "client_version",
            "last_ip",
            "first_seen",
            "last_seen",
            "last_tool",
            "request_count",
            "run_mode",
            "tool_label",
        }
        member_defaults = {
            row[1]: row[4]
            for row in connection.execute("PRAGMA table_info(members)")
        }
        assert member_defaults["run_mode"] == "'manual'"
        assert member_defaults["tool_label"] == "''"
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

        connection.execute(
            "UPDATE messages SET status = 'rejected' WHERE id = 'existing-proposal'"
        )
        assert connection.execute(
            "SELECT status FROM messages WHERE id = 'existing-proposal'"
        ).fetchone()[0] == "rejected"
    finally:
        connection.close()


def test_create_tables_migrates_old_proposal_status_constraint():
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
                proposal_id TEXT,
                status TEXT CHECK (
                    status IS NULL OR status IN ('open', 'accepted', 'escalated')
                ),
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """INSERT INTO messages
               (id, from_role, to_role, type, body, contract_version,
                proposal_id, status, created_at)
               VALUES ('old-proposal', 'frontend', 'backend', 'proposal',
                       'Preserve me', 1, 'old-proposal', 'escalated', '2026-01-01')"""
        )
        connection.execute(
            "CREATE INDEX idx_messages_proposal_id ON messages(proposal_id)"
        )

        create_tables(connection)

        connection.execute(
            "UPDATE messages SET status = 'rejected' WHERE id = 'old-proposal'"
        )
        row = connection.execute(
            "SELECT body, proposal_id, status, decision_note "
            "FROM messages WHERE id = 'old-proposal'"
        ).fetchone()
        assert row == ("Preserve me", "old-proposal", "rejected", None)
    finally:
        connection.close()


def test_create_tables_migrates_member_run_settings_with_manual_defaults():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE members (
                role TEXT PRIMARY KEY,
                ai_name TEXT,
                person_name TEXT,
                machine_label TEXT,
                client_name TEXT,
                client_version TEXT,
                last_ip TEXT,
                first_seen TEXT,
                last_seen TEXT,
                last_tool TEXT,
                request_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "INSERT INTO members (role, ai_name) VALUES ('frontend', 'Nova')"
        )

        create_tables(connection)

        row = connection.execute(
            "SELECT ai_name, run_mode, tool_label FROM members WHERE role = 'frontend'"
        ).fetchone()
        assert row == ("Nova", "manual", "")
    finally:
        connection.close()
