"""Dashboard account storage and salted password hashing."""

import hashlib
import hmac
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from server.database import create_tables
from server.storage import connect, is_integrity_error


_USERNAME = re.compile(r"^[a-zA-Z0-9_.-]{1,40}$")
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a fresh per-password random salt."""
    _validate_password(password)
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=64,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    if not isinstance(password, str) or len(password) > 1024:
        return False
    try:
        algorithm, n_value, r_value, p_value, salt_hex, digest_hex = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        if (n_value, r_value, p_value) != (str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P)):
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, MemoryError):
        return False


def _validate_password(password: object) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must contain between 12 and 1024 characters.")
    if "\x00" in password:
        raise ValueError("Password contains an invalid character.")
    return password


def _connection() -> sqlite3.Connection:
    connection = connect()
    create_tables(connection)
    return connection


@contextmanager
def _db_connection():
    connection = _connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    username = username.strip().lower() if isinstance(username, str) else ""
    with _db_connection() as connection:
        row = connection.execute(
            "SELECT username, password_hash, role_scope, linked_role, disabled "
            "FROM dashboard_users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None or row[4] or not verify_password(password, row[1]):
        return None
    return {"username": row[0], "role_scope": row[2], "linked_role": row[3]}


def user_for_session(username: str) -> dict[str, str] | None:
    with _db_connection() as connection:
        row = connection.execute(
            "SELECT username, role_scope, linked_role, disabled "
            "FROM dashboard_users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
    if row is None or row[3]:
        return None
    return {"username": row[0], "role_scope": row[1], "linked_role": row[2]}


def create_user(
    username: object, password: object, role_scope: object, linked_role: object = None
) -> dict[str, str | bool | None]:
    if not isinstance(username, str) or not _USERNAME.fullmatch(username.strip()):
        raise ValueError("Username must be 1 to 40 letters, digits, dots, dashes, or underscores.")
    username = username.strip().lower()
    password = _validate_password(password)
    if not isinstance(role_scope, str) or role_scope not in {"owner", "member"}:
        raise ValueError("role_scope must be 'owner' or 'member'.")
    if role_scope == "owner":
        if linked_role not in (None, ""):
            raise ValueError("Owner accounts cannot have a linked role.")
        linked_role = None
    else:
        if not isinstance(linked_role, str) or not linked_role:
            raise ValueError("Member accounts require a linked role.")
        with _db_connection() as connection:
            role = connection.execute(
                "SELECT name FROM roles WHERE name = ?", (linked_role,)
            ).fetchone()
        if role is None:
            raise ValueError("linked_role must name an existing role.")

    encoded_hash = hash_password(password)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with _db_connection() as connection:
            connection.execute(
                "INSERT INTO dashboard_users "
                "(username, password_hash, role_scope, linked_role, created_at, disabled) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (username, encoded_hash, role_scope, linked_role, created_at),
            )
    except Exception as error:
        if not is_integrity_error(error):
            raise
        raise ValueError("Username already exists.") from error
    return {
        "username": username,
        "role_scope": role_scope,
        "linked_role": linked_role,
        "created_at": created_at,
        "disabled": False,
    }


def list_users() -> list[dict[str, str | bool | None]]:
    with _db_connection() as connection:
        rows = connection.execute(
            "SELECT username, role_scope, linked_role, created_at, disabled "
            "FROM dashboard_users ORDER BY username"
        ).fetchall()
    return [
        {
            "username": row[0],
            "role_scope": row[1],
            "linked_role": row[2],
            "created_at": row[3],
            "disabled": bool(row[4]),
        }
        for row in rows
    ]


def reset_password(username: str, password: object) -> None:
    username = username.strip().lower()
    encoded_hash = hash_password(_validate_password(password))
    with _db_connection() as connection:
        cursor = connection.execute(
            "UPDATE dashboard_users SET password_hash = ? WHERE username = ?",
            (encoded_hash, username),
        )
        if cursor.rowcount != 1:
            raise ValueError("Dashboard user not found.")


def set_user_disabled(username: str, disabled: bool) -> None:
    username = username.strip().lower()
    with _db_connection() as connection:
        row = connection.execute(
            "SELECT role_scope, disabled FROM dashboard_users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            raise ValueError("Dashboard user not found.")
        if disabled and row[0] == "owner" and not row[1]:
            active_owners = connection.execute(
                "SELECT COUNT(*) FROM dashboard_users "
                "WHERE role_scope = 'owner' AND disabled = 0 AND username <> ?",
                (username,),
            ).fetchone()[0]
            if active_owners == 0:
                raise ValueError("At least one enabled owner account must remain.")
        connection.execute(
            "UPDATE dashboard_users SET disabled = ? WHERE username = ?",
            (int(disabled), username),
        )


def fallback_owner_enabled() -> bool:
    with _db_connection() as connection:
        value = connection.execute(
            "SELECT value FROM dashboard_settings WHERE name = 'fallback_owner_enabled'"
        ).fetchone()[0]
    return value == "1"


def set_fallback_owner_enabled(enabled: bool) -> None:
    with _db_connection() as connection:
        if not enabled:
            owner_count = connection.execute(
                "SELECT COUNT(*) FROM dashboard_users "
                "WHERE role_scope = 'owner' AND disabled = 0"
            ).fetchone()[0]
            if owner_count == 0:
                raise ValueError("Create an enabled owner account before disabling fallback login.")
        connection.execute(
            "UPDATE dashboard_settings SET value = ? "
            "WHERE name = 'fallback_owner_enabled'",
            ("1" if enabled else "0",),
        )
