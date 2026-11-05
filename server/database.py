"""SQLite schema setup for TeamBrain."""

import sqlite3


def create_tables(connection: sqlite3.Connection) -> None:
    """Create the contracts and messages tables if they do not exist."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS contracts (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            from_role TEXT NOT NULL,
            to_role TEXT NOT NULL,
            type TEXT NOT NULL,
            body TEXT NOT NULL,
            contract_version INTEGER NOT NULL,
            "read" INTEGER NOT NULL DEFAULT 0,
            proposal_id TEXT,
            status TEXT CHECK (
                status IS NULL OR status IN ('open', 'accepted', 'escalated', 'rejected')
            ),
            decision_note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    message_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(messages)")
    }
    if "proposal_id" not in message_columns:
        connection.execute("ALTER TABLE messages ADD COLUMN proposal_id TEXT")
    if "status" not in message_columns:
        connection.execute(
            "ALTER TABLE messages ADD COLUMN status TEXT "
            "CHECK (status IS NULL OR status IN ('open', 'accepted', 'escalated', 'rejected'))"
        )
    if "decision_note" not in message_columns:
        connection.execute("ALTER TABLE messages ADD COLUMN decision_note TEXT")

    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages'"
    ).fetchone()[0]
    if "'rejected'" not in table_sql:
        connection.execute("ALTER TABLE messages RENAME TO messages_before_rejection")
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
                    status IS NULL OR status IN ('open', 'accepted', 'escalated', 'rejected')
                ),
                decision_note TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO messages
                (id, from_role, to_role, type, body, contract_version, "read",
                 proposal_id, status, decision_note, created_at)
            SELECT id, from_role, to_role, type, body, contract_version, "read",
                   proposal_id, status, decision_note, created_at
            FROM messages_before_rejection
            """
        )
        connection.execute("DROP TABLE messages_before_rejection")

    # Existing standalone proposals become roots of their own threads.
    connection.execute(
        "UPDATE messages SET proposal_id = id WHERE type = 'proposal' AND proposal_id IS NULL"
    )
    connection.execute(
        "UPDATE messages SET status = 'open' "
        "WHERE type = 'proposal' AND proposal_id = id AND status IS NULL"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_proposal_id ON messages(proposal_id)"
    )
    connection.commit()
