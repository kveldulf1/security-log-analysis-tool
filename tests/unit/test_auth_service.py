"""Tests for AuthService: login, lockout, and unlock-after-window (A07)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from security_log_analysis_tool.auth.passwords import WeakPasswordError
from security_log_analysis_tool.auth.service import (
    LOCKOUT_DURATION,
    MAX_FAILED_ATTEMPTS,
    AuthenticationError,
    AuthService,
)
from security_log_analysis_tool.auth.store import UserStore, UserStoreError
from security_log_analysis_tool.models import Role


class _FakeClock:
    """An injectable, manually-advanced clock so lockout expiry needs no sleep."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@pytest.fixture
def store(tmp_path: Path):
    with UserStore(tmp_path / "users.db") as s:
        yield s


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def service(store: UserStore, clock: _FakeClock) -> AuthService:
    return AuthService(store, clock=clock)


def test_create_user_and_login(service: AuthService) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    principal = service.login("alice", "Password123!")
    assert principal.username == "alice"
    assert principal.role is Role.ANALYST


def test_create_user_rejects_weak_password(service: AuthService) -> None:
    with pytest.raises(WeakPasswordError):
        service.create_user("alice", "weak", Role.ANALYST)


def test_create_user_rejects_duplicate(service: AuthService) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    with pytest.raises(UserStoreError):
        service.create_user("alice", "Password123!", Role.ANALYST)


def test_login_unknown_user_rejected(service: AuthService) -> None:
    with pytest.raises(AuthenticationError):
        service.login("ghost", "Password123!")


def test_login_unknown_user_still_performs_password_verification(
    service: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards a username-enumeration timing side-channel: rejecting an unknown
    user must still pay the same scrypt cost as a wrong-password rejection,
    not return early — otherwise response latency alone reveals which
    usernames exist even though the error message doesn't."""

    import security_log_analysis_tool.auth.service as service_module

    calls: list[str] = []
    original_verify = service_module.verify_password

    def spy_verify(password: str, stored_hash: str) -> bool:
        calls.append(stored_hash)
        return original_verify(password, stored_hash)

    monkeypatch.setattr(service_module, "verify_password", spy_verify)

    with pytest.raises(AuthenticationError):
        service.login("ghost", "whatever")

    assert calls == [service_module._DUMMY_PASSWORD_HASH]


def test_login_wrong_password_rejected(service: AuthService) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    with pytest.raises(AuthenticationError):
        service.login("alice", "wrong-password")


def test_login_resets_failed_attempts_on_success(service: AuthService, store: UserStore) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    with pytest.raises(AuthenticationError):
        service.login("alice", "wrong-password")
    assert store.get_user("alice").failed_attempts == 1

    service.login("alice", "Password123!")
    assert store.get_user("alice").failed_attempts == 0


def test_lockout_after_max_failed_attempts(
    service: AuthService, store: UserStore, clock: _FakeClock
) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")

    user = store.get_user("alice")
    assert user.failed_attempts == MAX_FAILED_ATTEMPTS
    assert user.locked_until == clock() + LOCKOUT_DURATION


def test_locked_account_rejects_even_correct_password(
    service: AuthService, clock: _FakeClock
) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")

    with pytest.raises(AuthenticationError, match="locked"):
        service.login("alice", "Password123!")


def test_lockout_expires_after_window(service: AuthService, clock: _FakeClock) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")

    clock.advance(LOCKOUT_DURATION + timedelta(seconds=1))
    principal = service.login("alice", "Password123!")
    assert principal.username == "alice"


def test_lockout_still_active_just_before_window_ends(
    service: AuthService, clock: _FakeClock
) -> None:
    service.create_user("alice", "Password123!", Role.ANALYST)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")

    clock.advance(LOCKOUT_DURATION - timedelta(seconds=1))
    with pytest.raises(AuthenticationError, match="locked"):
        service.login("alice", "Password123!")


def test_sqli_shaped_login_fails_and_creates_no_row(service: AuthService, store: UserStore) -> None:
    """A01/A03: a classic auth-bypass payload must not authenticate or create a row."""

    with pytest.raises(AuthenticationError):
        service.login("admin' OR '1'='1' --", "anything")
    assert store.list_users() == ()
