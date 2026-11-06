"""Dynamic role validation and owner-managed role metadata."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from server.database import create_tables


ROLE_NAME = re.compile(r"^[a-z0-9]{1,20}$")
ROLE_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_role(
    connection: sqlite3.Connection, role: str, *, active_only: bool = True
) -> None:
    """Raise ValueError unless role exists and, by default, is active."""
    if not isinstance(role, str):
        raise ValueError("Invalid role")
    query = "SELECT active FROM roles WHERE name = ?"
    row = connection.execute(query, (role,)).fetchone()
    if row is None or (active_only and not row[0]):
        raise ValueError(f"Invalid role {role!r}")


def list_roles(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """List role metadata in creation order; never includes token values."""
    connection.row_factory = sqlite3.Row
    return [
        {**dict(row), "active": bool(row["active"]), "can_write_contract": bool(row["can_write_contract"])}
        for row in connection.execute("SELECT * FROM roles ORDER BY rowid")
    ]


def list_roles_tool() -> list[dict[str, Any]]:
    """Read-only MCP view of configured roles."""
    from server.messages import DB_PATH

    uri = f"{Path(DB_PATH).resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return list_roles(connection)


def create_role(
    name: str, description: str, color: str, *, active: bool = True
) -> dict[str, Any]:
    """Create a role and return the token environment variable name only."""
    from server.messages import DB_PATH

    if not isinstance(name, str) or not ROLE_NAME.fullmatch(name):
        raise ValueError("Role name must contain 1–20 lowercase letters or digits.")
    if not isinstance(description, str) or len(description) > 200:
        raise ValueError("Description must be plain text up to 200 characters.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in description):
        raise ValueError("Description must be plain text.")
    if not isinstance(color, str) or not ROLE_COLOR.fullmatch(color):
        raise ValueError("Choose a valid color.")
    if not isinstance(active, bool):
        raise ValueError("active must be a boolean.")
    token_env_var = f"TEAMBRAIN_TOKEN_{name.upper()}"
    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        try:
            connection.execute(
                """INSERT INTO roles
                   (name, description, color, active, token_env_var, can_write_contract)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (name, description.strip(), color.lower(), int(active), token_env_var),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Role {name!r} already exists.") from error
    return {
        "name": name,
        "description": description.strip(),
        "color": color.lower(),
        "active": active,
        "token_env_var": token_env_var,
        "can_write_contract": False,
        "token_setup": "Set this environment variable yourself after manually generating a token, then restart TeamBrain HTTP. The server does not create or store tokens.",
    }


def set_role_active(name: str, active: bool) -> dict[str, Any]:
    """Enable or disable a role for HTTP authentication."""
    from server.messages import DB_PATH

    if not isinstance(active, bool):
        raise ValueError("active must be a boolean.")
    with sqlite3.connect(DB_PATH) as connection:
        create_tables(connection)
        cursor = connection.execute(
            "UPDATE roles SET active = ? WHERE name = ?", (int(active), name)
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Unknown role {name!r}.")
    return {"name": name, "active": active}
