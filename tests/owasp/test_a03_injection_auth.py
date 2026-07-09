"""OWASP A03 - Injection, scoped to the auth surface.

A classic SQL-injection auth-bypass payload must fail cleanly through every
parameterized query path: login, user creation, lookup, and removal. Nothing
here builds SQL by string interpolation, so these tests exercise the store's
real behaviour, not a mock.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from security_log_analysis_tool.auth.passwords import hash_password
from security_log_analysis_tool.auth.service import AuthenticationError, AuthService
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.models import Role, User

pytestmark = pytest.mark.owasp

_CLASSIC_BYPASS = "admin' OR '1'='1' --"
_DROP_TABLE = "alice'; DROP TABLE users; --"


@pytest.fixture
def store(tmp_path: Path):
    with UserStore(tmp_path / "users.db") as s:
        yield s


def test_classic_bypass_payload_fails_login_and_creates_no_row(store: UserStore) -> None:
    service = AuthService(store)
    service.create_user("admin", "Password123!", Role.ADMIN)

    with pytest.raises(AuthenticationError):
        service.login(_CLASSIC_BYPASS, "anything")

    assert store.get_user(_CLASSIC_BYPASS) is None
    assert len(store.list_users()) == 1  # only the legitimate admin


def test_drop_table_shaped_username_does_not_touch_the_schema(store: UserStore) -> None:
    service = AuthService(store)
    service.create_user("admin", "Password123!", Role.ADMIN)

    # Creating a user with a DROP-TABLE-shaped username must be inert as SQL:
    # it either succeeds as an ordinary (if odd) username, or fails on policy --
    # either way the users table and the pre-existing admin row must survive.
    with contextlib.suppress(Exception):
        service.create_user(_DROP_TABLE, "Password123!", Role.ANALYST)

    assert store.get_user("admin") is not None
    admin_login = service.login("admin", "Password123!")
    assert admin_login.username == "admin"


def test_password_field_with_sql_metacharacters_is_treated_as_opaque_data(
    store: UserStore,
) -> None:
    service = AuthService(store)
    tricky_password = "P@ss'; DROP TABLE users; --1"
    service.create_user("bob", tricky_password, Role.ANALYST)

    principal = service.login("bob", tricky_password)
    assert principal.username == "bob"
    assert store.get_user("admin_should_not_exist") is None
    assert len(store.list_users()) == 1


def test_remove_user_with_injection_shaped_name_only_deletes_the_exact_row(
    store: UserStore,
) -> None:
    store.add_user(
        User(username="alice", password_hash=hash_password("Password123!"), role=Role.ANALYST)
    )
    store.add_user(
        User(username="bob", password_hash=hash_password("Password123!"), role=Role.ANALYST)
    )

    removed = store.remove_user("alice' OR '1'='1")
    assert removed is False  # no row matches that exact (nonexistent) username
    assert store.get_user("alice") is not None
    assert store.get_user("bob") is not None
