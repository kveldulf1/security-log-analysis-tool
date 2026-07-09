"""SQLite-backed user store: 100% parameterized queries, WAL journal mode.

A JSON file would race under the job queue's worker threads; SQLite with WAL
gives safe concurrent readers while a single writer commits. Every query is
parameterized — this *is* the SQL-injection demonstration (see the OWASP A03
tests) as much as it is the storage layer.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Role, User

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);
"""


class UserStoreError(Exception):
    """Raised for user-store integrity problems (e.g. duplicate username)."""


def default_db_path() -> Path:
    """The default users.db location: ``%LOCALAPPDATA%`` on Windows, XDG on posix.

    ``SLAT_USERS_DB`` overrides this — the seam tests use to avoid touching a
    real user profile directory.
    """

    override = os.environ.get("SLAT_USERS_DB")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "security-log-analysis-tool" / "users.db"


class UserStore:
    """Owns one SQLite connection. Not shared across processes."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.execute(_SCHEMA)

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> UserStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def add_user(self, user: User) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO users "
                    "(username, password_hash, role, failed_attempts, locked_until) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        user.username,
                        user.password_hash,
                        user.role.value,
                        user.failed_attempts,
                        user.locked_until.isoformat() if user.locked_until else None,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise UserStoreError(f"user {user.username!r} already exists") from exc

    def get_user(self, username: str) -> User | None:
        row = self._conn.execute(
            "SELECT username, password_hash, role, failed_attempts, locked_until "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def list_users(self) -> tuple[User, ...]:
        rows = self._conn.execute(
            "SELECT username, password_hash, role, failed_attempts, locked_until "
            "FROM users ORDER BY username"
        ).fetchall()
        return tuple(_row_to_user(row) for row in rows)

    def remove_user(self, username: str) -> bool:
        with self._conn:
            cursor = self._conn.execute("DELETE FROM users WHERE username = ?", (username,))
        return cursor.rowcount > 0

    def update_auth_state(
        self, username: str, *, failed_attempts: int, locked_until: datetime | None
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?",
                (failed_attempts, locked_until.isoformat() if locked_until else None, username),
            )


def _row_to_user(row: tuple[Any, ...]) -> User:
    username, password_hash, role, failed_attempts, locked_until = row
    return User(
        username=username,
        password_hash=password_hash,
        role=Role(role),
        failed_attempts=failed_attempts,
        locked_until=datetime.fromisoformat(locked_until) if locked_until else None,
    )
