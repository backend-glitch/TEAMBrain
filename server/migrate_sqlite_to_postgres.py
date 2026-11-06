"""Copy a TeamBrain SQLite database into an empty Prisma/PostgreSQL database."""

import argparse
import sqlite3
from pathlib import Path

from server.database import ROLE_SEEDS, create_tables
from server.messages import DB_PATH
from server.storage import connect, postgres_enabled


TABLES = (
    "contracts",
    "roles",
    "messages",
    "team_status",
    "status_history",
    "work_log",
    "members",
    "dashboard_users",
    "dashboard_settings",
)
DATA_TABLES = (
    "contracts",
    "messages",
    "team_status",
    "status_history",
    "work_log",
    "members",
    "dashboard_users",
)


def migrate(source_path: Path, *, replace: bool = False) -> dict[str, int]:
    if not postgres_enabled():
        raise RuntimeError("Set DATABASE_URL to the Prisma Postgres connection string first.")
    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    counts: dict[str, int] = {}
    with sqlite3.connect(source_path) as source:
        source.row_factory = sqlite3.Row
        create_tables(source)
        source.commit()
        rows_by_table = {
            table: source.execute(f'SELECT * FROM "{table}"').fetchall()
            for table in TABLES
        }

    with connect() as target:
        create_tables(target)
        nonempty = []
        for table in DATA_TABLES:
            count = target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if count:
                nonempty.append(table)
        role_names = {
            row[0] for row in target.execute("SELECT name FROM roles").fetchall()
        }
        seed_names = {role[0] for role in ROLE_SEEDS}
        if role_names != seed_names:
            nonempty.append("roles")
        setting_rows = target.execute(
            "SELECT name, value FROM dashboard_settings"
        ).fetchall()
        if setting_rows != [("fallback_owner_enabled", "1")]:
            nonempty.append("dashboard_settings")
        if nonempty and not replace:
            raise RuntimeError(
                "The target database already contains application data in: "
                + ", ".join(nonempty)
                + ". Re-run with --replace only if you intend to overwrite it."
            )

        for table in reversed(TABLES):
            target.execute(f'DELETE FROM "{table}"')
        for table in TABLES:
            rows = rows_by_table[table]
            if not rows:
                counts[table] = 0
                continue
            columns = list(rows[0].keys())
            column_sql = ", ".join(f'"{column}"' for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            target.executemany(
                f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                [tuple(row[column] for column in columns) for row in rows],
            )
            counts[table] = len(rows)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DB_PATH,
        help="SQLite file to copy (defaults to TEAMBRAIN_DB or the local database).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace application rows already present in the Postgres target.",
    )
    args = parser.parse_args()
    counts = migrate(args.source, replace=args.replace)
    print("Copied TeamBrain tables: " + ", ".join(f"{name}={count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
