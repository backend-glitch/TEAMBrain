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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS team_status (
            role TEXT PRIMARY KEY CHECK (role IN ('uiux', 'frontend', 'backend')),
            summary TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('working', 'blocked', 'waiting', 'done')),
            task TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS status_history (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL CHECK (role IN ('uiux', 'frontend', 'backend')),
            summary TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('working', 'blocked', 'waiting', 'done')),
            task TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS work_log (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL CHECK (role IN ('uiux', 'frontend', 'backend')),
            summary TEXT NOT NULL,
            files TEXT NOT NULL,
            related_proposal_id TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            role TEXT PRIMARY KEY CHECK (role IN ('uiux', 'frontend', 'backend')),
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
        "CREATE INDEX IF NOT EXISTS idx_status_history_role_created "
        "ON status_history(role, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_log_role_created "
        "ON work_log(role, created_at DESC)"
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
