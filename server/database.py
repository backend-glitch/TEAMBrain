"""SQLite and PostgreSQL schema setup for TeamBrain."""

import sqlite3

from server.storage import (
    is_postgres,
    mark_postgres_schema_ready,
    postgres_schema_lock,
    postgres_schema_ready,
)


ROLE_SEEDS = (
    ("uiux", "UI/UX design", "#d8adf2", 1, "TEAMBRAIN_TOKEN_UIUX", 0),
    ("frontend", "Frontend engineering", "#87d7e8", 1, "TEAMBRAIN_TOKEN_FRONTEND", 0),
    ("backend", "Backend engineering", "#e8bd85", 1, "TEAMBRAIN_TOKEN_BACKEND", 1),
    ("qa", "Quality assurance", "#95d7a5", 0, "TEAMBRAIN_TOKEN_QA", 0),
    ("database", "Database engineering", "#e7ad59", 0, "TEAMBRAIN_TOKEN_DATABASE", 0),
)


def _table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row[0] if row else ""


def _rebuild_role_table(
    connection: sqlite3.Connection, table: str, columns: tuple[str, ...], ddl: str
) -> None:
    """Remove legacy static role checks while preserving every row and column."""
    sql = _table_sql(connection, table)
    if "role IN ('uiux', 'frontend', 'backend')" not in sql:
        return
    old_table = f"{table}_before_dynamic_roles"
    connection.execute(f'ALTER TABLE "{table}" RENAME TO "{old_table}"')
    connection.execute(ddl)
    column_list = ", ".join(f'"{column}"' for column in columns)
    connection.execute(
        f'INSERT INTO "{table}" ({column_list}) '
        f'SELECT {column_list} FROM "{old_table}"'
    )
    connection.execute(f'DROP TABLE "{old_table}"')


def _create_postgres_tables(connection) -> None:
    """Create or additively migrate the schema on a PostgreSQL database."""
    statements = (
        """CREATE TABLE IF NOT EXISTS contracts (
            id TEXT PRIMARY KEY, version INTEGER NOT NULL, content TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS roles (
            name TEXT PRIMARY KEY UNIQUE CHECK (
                length(name) BETWEEN 1 AND 20 AND name !~ '[^a-z0-9]'),
            description TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#718091',
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            token_env_var TEXT NOT NULL UNIQUE,
            can_write_contract INTEGER NOT NULL DEFAULT 0 CHECK (can_write_contract IN (0, 1)))""",
        """CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, from_role TEXT NOT NULL, to_role TEXT NOT NULL,
            type TEXT NOT NULL, body TEXT NOT NULL, contract_version INTEGER NOT NULL,
            "read" INTEGER NOT NULL DEFAULT 0, proposal_id TEXT,
            status TEXT CHECK (status IS NULL OR status IN ('open', 'accepted', 'escalated', 'rejected')),
            decision_note TEXT, handoff_prompt TEXT, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS team_status (
            role TEXT PRIMARY KEY, summary TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('working', 'blocked', 'waiting', 'done')),
            task TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS status_history (
            id TEXT PRIMARY KEY, role TEXT NOT NULL, summary TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('working', 'blocked', 'waiting', 'done')),
            task TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS work_log (
            id TEXT PRIMARY KEY, role TEXT NOT NULL, summary TEXT NOT NULL,
            files TEXT NOT NULL, related_proposal_id TEXT, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS members (
            role TEXT PRIMARY KEY, ai_name TEXT, person_name TEXT, machine_label TEXT,
            client_name TEXT, client_version TEXT, last_ip TEXT, first_seen TEXT,
            last_seen TEXT, last_tool TEXT, request_count INTEGER NOT NULL DEFAULT 0,
            run_mode TEXT NOT NULL DEFAULT 'manual' CHECK (run_mode IN ('manual', 'headless')),
            tool_label TEXT NOT NULL DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS dashboard_users (
            username TEXT PRIMARY KEY UNIQUE, password_hash TEXT NOT NULL,
            role_scope TEXT NOT NULL CHECK (role_scope IN ('owner', 'member')),
            linked_role TEXT, created_at TEXT NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
            CHECK ((role_scope = 'owner' AND linked_role IS NULL) OR
                   (role_scope = 'member' AND linked_role IS NOT NULL)))""",
        """CREATE TABLE IF NOT EXISTS dashboard_settings (
            name TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    )
    for statement in statements:
        connection.execute(statement)

    # Keep additive migrations safe for databases created by older releases.
    connection.execute(
        "ALTER TABLE members ADD COLUMN IF NOT EXISTS run_mode TEXT NOT NULL DEFAULT 'manual'"
    )
    connection.execute(
        "ALTER TABLE members ADD COLUMN IF NOT EXISTS tool_label TEXT NOT NULL DEFAULT ''"
    )
    for column, definition in (
        ("proposal_id", "TEXT"),
        ("status", "TEXT"),
        ("decision_note", "TEXT"),
        ("handoff_prompt", "TEXT"),
    ):
        connection.execute(
            f"ALTER TABLE messages ADD COLUMN IF NOT EXISTS {column} {definition}"
        )
    connection.executemany(
        """INSERT INTO roles
           (name, description, color, active, token_env_var, can_write_contract)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (name) DO NOTHING""",
        ROLE_SEEDS,
    )
    connection.execute(
        "INSERT INTO dashboard_settings (name, value) "
        "VALUES ('fallback_owner_enabled', '1') ON CONFLICT (name) DO NOTHING"
    )
    connection.execute(
        "UPDATE messages SET proposal_id = id WHERE type = 'proposal' AND proposal_id IS NULL"
    )
    connection.execute(
        "UPDATE messages SET status = 'open' "
        "WHERE type = 'proposal' AND proposal_id = id AND status IS NULL"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_status_history_role_created "
        "ON status_history(role, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_log_role_created "
        "ON work_log(role, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_proposal_id ON messages(proposal_id)"
    )


def create_tables(connection: sqlite3.Connection) -> None:
    """Create the application schema for the selected database backend."""
    if is_postgres(connection):
        if postgres_schema_ready():
            return
        with postgres_schema_lock():
            if not postgres_schema_ready():
                _create_postgres_tables(connection)
                connection.commit()
                mark_postgres_schema_ready()
        return
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
        CREATE TABLE IF NOT EXISTS roles (
            name TEXT PRIMARY KEY UNIQUE CHECK (
                length(name) BETWEEN 1 AND 20 AND name NOT GLOB '*[^a-z0-9]*'
            ),
            description TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT '#718091',
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            token_env_var TEXT NOT NULL UNIQUE,
            can_write_contract INTEGER NOT NULL DEFAULT 0 CHECK (can_write_contract IN (0, 1))
        )
        """
    )
    connection.executemany(
        """INSERT OR IGNORE INTO roles
           (name, description, color, active, token_env_var, can_write_contract)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ROLE_SEEDS,
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
            handoff_prompt TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS team_status (
            role TEXT PRIMARY KEY,
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
            role TEXT NOT NULL,
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
            role TEXT NOT NULL,
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
            request_count INTEGER NOT NULL DEFAULT 0,
            run_mode TEXT NOT NULL DEFAULT 'manual' CHECK (run_mode IN ('manual', 'headless')),
            tool_label TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_users (
            username TEXT PRIMARY KEY UNIQUE,
            password_hash TEXT NOT NULL,
            role_scope TEXT NOT NULL CHECK (role_scope IN ('owner', 'member')),
            linked_role TEXT,
            created_at TEXT NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
            CHECK (
                (role_scope = 'owner' AND linked_role IS NULL) OR
                (role_scope = 'member' AND linked_role IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_settings (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO dashboard_settings (name, value) "
        "VALUES ('fallback_owner_enabled', '1')"
    )
    member_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(members)")
    }
    if "run_mode" not in member_columns:
        connection.execute(
            "ALTER TABLE members ADD COLUMN run_mode TEXT NOT NULL DEFAULT 'manual' "
            "CHECK (run_mode IN ('manual', 'headless'))"
        )
    if "tool_label" not in member_columns:
        connection.execute(
            "ALTER TABLE members ADD COLUMN tool_label TEXT NOT NULL DEFAULT ''"
        )
    _rebuild_role_table(
        connection,
        "members",
        (
            "role", "ai_name", "person_name", "machine_label", "client_name",
            "client_version", "last_ip", "first_seen", "last_seen", "last_tool",
            "request_count", "run_mode", "tool_label",
        ),
        """CREATE TABLE members (
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
            request_count INTEGER NOT NULL DEFAULT 0,
            run_mode TEXT NOT NULL DEFAULT 'manual' CHECK (run_mode IN ('manual', 'headless')),
            tool_label TEXT NOT NULL DEFAULT ''
        )""",
    )
    _rebuild_role_table(
        connection, "team_status",
        ("role", "summary", "state", "task", "updated_at"),
        """CREATE TABLE team_status (
            role TEXT PRIMARY KEY, summary TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('working', 'blocked', 'waiting', 'done')),
            task TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
    )
    _rebuild_role_table(
        connection, "status_history",
        ("id", "role", "summary", "state", "task", "created_at"),
        """CREATE TABLE status_history (
            id TEXT PRIMARY KEY, role TEXT NOT NULL, summary TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('working', 'blocked', 'waiting', 'done')),
            task TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
    )
    _rebuild_role_table(
        connection, "work_log",
        ("id", "role", "summary", "files", "related_proposal_id", "created_at"),
        """CREATE TABLE work_log (
            id TEXT PRIMARY KEY, role TEXT NOT NULL, summary TEXT NOT NULL,
            files TEXT NOT NULL, related_proposal_id TEXT, created_at TEXT NOT NULL
        )""",
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
    if "handoff_prompt" not in message_columns:
        connection.execute("ALTER TABLE messages ADD COLUMN handoff_prompt TEXT")

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
                handoff_prompt TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO messages
                (id, from_role, to_role, type, body, contract_version, "read",
                 proposal_id, status, decision_note, handoff_prompt, created_at)
            SELECT id, from_role, to_role, type, body, contract_version, "read",
                   proposal_id, status, decision_note, handoff_prompt, created_at
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
