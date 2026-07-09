"""Tests for the SQLite user store: CRUD, WAL mode, and parameterization safety."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_log_analysis_tool.auth.passwords import hash_password
from security_log_analysis_tool.auth.store import UserStore, UserStoreError, default_db_path
from security_log_analysis_tool.models import Role, User


@pytest.fixture
def store(tmp_path: Path):
    with UserStore(tmp_path / "users.db") as s:
        yield s


def _user(username: str = "alice", role: Role = Role.ANALYST) -> User:
    return User(username=username, password_hash=hash_password("Password123!"), role=role)


def test_add_and_get_user(store: UserStore) -> None:
    store.add_user(_user("alice", Role.ANALYST))
    got = store.get_user("alice")
    assert got is not None
    assert got.username == "alice"
    assert got.role is Role.ANALYST
    assert got.failed_attempts == 0
    assert got.locked_until is None


def test_get_missing_user_returns_none(store: UserStore) -> None:
    assert store.get_user("nobody") is None


def test_add_duplicate_user_raises(store: UserStore) -> None:
    store.add_user(_user("alice"))
    with pytest.raises(UserStoreError):
        store.add_user(_user("alice"))


def test_list_users_sorted(store: UserStore) -> None:
    store.add_user(_user("bob", Role.ADMIN))
    store.add_user(_user("alice", Role.ANALYST))
    users = store.list_users()
    assert [u.username for u in users] == ["alice", "bob"]


def test_remove_user(store: UserStore) -> None:
    store.add_user(_user("alice"))
    assert store.remove_user("alice") is True
    assert store.get_user("alice") is None


def test_remove_missing_user_returns_false(store: UserStore) -> None:
    assert store.remove_user("nobody") is False


def test_update_auth_state_roundtrip(store: UserStore) -> None:
    store.add_user(_user("alice"))
    locked_until = datetime(2026, 1, 1, tzinfo=UTC)
    store.update_auth_state("alice", failed_attempts=3, locked_until=locked_until)
    got = store.get_user("alice")
    assert got is not None
    assert got.failed_attempts == 3
    assert got.locked_until == locked_until


def test_sql_injection_shaped_username_is_inert(store: UserStore) -> None:
    """A malicious username must be treated as pure data, never as SQL (A03)."""

    payload = "alice'; DROP TABLE users; --"
    store.add_user(_user(payload))
    assert store.get_user(payload) is not None
    assert store.get_user("alice") is None  # table not dropped; other rows unaffected
    assert len(store.list_users()) == 1


def test_wal_journal_mode_enabled(tmp_path: Path) -> None:
    with UserStore(tmp_path / "users.db") as s:
        mode = s._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_default_db_path_honours_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom.db"
    monkeypatch.setenv("SLAT_USERS_DB", str(override))
    assert default_db_path() == override


def test_raw_db_bytes_never_contain_plaintext_password(tmp_path: Path) -> None:
    db_path = tmp_path / "users.db"
    with UserStore(db_path) as s:
        s.add_user(_user("alice"))
        s.add_user(_user("bob"))
    raw = db_path.read_bytes()
    assert b"Password123!" not in raw
