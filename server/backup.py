"""Create a consistent SQLite backup and retain the latest seven copies."""

import argparse
import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from server.messages import DB_PATH
from server.database import ROLE_SEEDS, create_tables
from server.storage import connect, postgres_enabled


POSTGRES_TABLES = (
    "contracts", "roles", "messages", "team_status", "status_history",
    "work_log", "members", "dashboard_users", "dashboard_settings",
)


def _retain_latest(directory: Path, pattern: str, keep: int) -> None:
    backups = sorted(
        directory.glob(pattern),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink()


def _backup_postgres(directory: Path, keep: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"teambrain-{timestamp}.json.gz"
    suffix = 1
    while destination.exists():
        destination = directory / f"teambrain-{timestamp}-{suffix}.json.gz"
        suffix += 1

    with connect() as initialization_connection:
        create_tables(initialization_connection)
    with connect(readonly=True) as connection:
        connection.row_factory = sqlite3.Row
        payload = {
            "format": 1,
            "tables": {
                table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
                for table in POSTGRES_TABLES
            },
        }
    with gzip.open(destination, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    _retain_latest(directory, "teambrain-*.json.gz", keep)
    return destination


def restore_postgres_backup(backup_path: Path, *, replace: bool = False) -> None:
    """Restore a compressed JSON dump into PostgreSQL after an explicit check."""
    if not postgres_enabled():
        raise RuntimeError("Set DATABASE_URL to the PostgreSQL restore target first.")
    with gzip.open(backup_path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    tables = payload.get("tables") if payload.get("format") == 1 else None
    if not isinstance(tables, dict) or set(tables) != set(POSTGRES_TABLES):
        raise ValueError("Unsupported or incomplete TeamBrain backup.")

    with connect() as connection:
        create_tables(connection)
        populated = []
        for table in POSTGRES_TABLES:
            if table in {"roles", "dashboard_settings"}:
                continue
            if connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                populated.append(table)
        role_names = {
            row[0] for row in connection.execute("SELECT name FROM roles").fetchall()
        }
        if role_names != {role[0] for role in ROLE_SEEDS}:
            populated.append("roles")
        settings = connection.execute(
            "SELECT name, value FROM dashboard_settings"
        ).fetchall()
        if settings != [("fallback_owner_enabled", "1")]:
            populated.append("dashboard_settings")
        if populated and not replace:
            raise RuntimeError(
                "The target already has TeamBrain data. Pass --replace to overwrite it."
            )
        for table in reversed(POSTGRES_TABLES):
            connection.execute(f'DELETE FROM "{table}"')
        for table in POSTGRES_TABLES:
            rows = tables[table]
            if not isinstance(rows, list):
                raise ValueError(f"Invalid backup rows for {table}.")
            for row in rows:
                if not isinstance(row, dict) or not row:
                    raise ValueError(f"Invalid backup row in {table}.")
                columns = list(row)
                column_sql = ", ".join(f'"{column}"' for column in columns)
                placeholders = ", ".join("?" for _ in columns)
                connection.execute(
                    f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                    [row[column] for column in columns],
                )


def backup_database(
    database_path: Path = DB_PATH,
    backup_directory: Path | None = None,
    keep: int = 7,
) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    destination_dir = backup_directory or Path(database_path).parent / "backups"
    destination_dir = Path(destination_dir)
    if postgres_enabled():
        return _backup_postgres(destination_dir, keep)
    database_path = Path(database_path)
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = destination_dir / f"teambrain-{timestamp}.sqlite3"
    suffix = 1
    while destination.exists():
        destination = destination_dir / f"teambrain-{timestamp}-{suffix}.sqlite3"
        suffix += 1

    with sqlite3.connect(database_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)

    _retain_latest(destination_dir, "teambrain-*.sqlite3", keep)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        help="Backup directory (defaults to <database directory>/backups)",
    )
    parser.add_argument("--keep", type=int, default=7)
    parser.add_argument(
        "--restore",
        type=Path,
        help="Restore a .json.gz PostgreSQL backup instead of creating one.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace current PostgreSQL data when restoring a backup.",
    )
    args = parser.parse_args()
    if args.restore:
        restore_postgres_backup(args.restore, replace=args.replace)
        print("TeamBrain backup restored.")
        return
    output = backup_database(DB_PATH, args.directory, args.keep)
    print(output)


if __name__ == "__main__":
    main()
