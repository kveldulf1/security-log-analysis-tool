"""OWASP A07 - Identification and Authentication Failures.

Lockout after repeated failures, unlock after the window, weak-password
rejection, and constant-time comparison (also covered from the crypto angle
in test_a02_crypto.py).
"""

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
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.models import Role

pytestmark = pytest.mark.owasp


class _FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@pytest.fixture
def store(tmp_path: Path):
    with UserStore(tmp_path / "users.db") as s:
        yield s


def test_five_consecutive_failures_lock_the_account(store: UserStore) -> None:
    clock = _FakeClock()
    service = AuthService(store, clock=clock)
    service.create_user("alice", "Password123!", Role.ANALYST)

    for attempt in range(1, MAX_FAILED_ATTEMPTS + 1):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")
        user = store.get_user("alice")
        assert user.failed_attempts == attempt

    assert store.get_user("alice").locked_until == clock() + LOCKOUT_DURATION


def test_account_unlocks_after_the_lockout_window(store: UserStore) -> None:
    clock = _FakeClock()
    service = AuthService(store, clock=clock)
    service.create_user("alice", "Password123!", Role.ANALYST)

    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")

    clock.advance(LOCKOUT_DURATION + timedelta(seconds=1))
    principal = service.login("alice", "Password123!")
    assert principal.username == "alice"
    assert store.get_user("alice").failed_attempts == 0
    assert store.get_user("alice").locked_until is None


def test_fewer_than_max_failures_does_not_lock(store: UserStore) -> None:
    clock = _FakeClock()
    service = AuthService(store, clock=clock)
    service.create_user("alice", "Password123!", Role.ANALYST)

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError):
            service.login("alice", "wrong-password")

    assert store.get_user("alice").locked_until is None
    principal = service.login("alice", "Password123!")  # still allowed
    assert principal.username == "alice"


@pytest.mark.parametrize(
    "weak_password",
    ["short1A!", "alllowercaseonly", "12345678901234"],
)
def test_users_add_rejects_weak_password_at_creation(store: UserStore, weak_password: str) -> None:
    service = AuthService(store)
    with pytest.raises(WeakPasswordError):
        service.create_user("alice", weak_password, Role.ANALYST)
    assert store.get_user("alice") is None


def test_password_comparison_never_short_circuits_on_length_via_timing_oracle() -> None:
    """Not a timing measurement (flaky in CI) -- verifies compare_digest is used, not `==`."""

    import inspect

    from security_log_analysis_tool.auth import passwords

    source = inspect.getsource(passwords.verify_password)
    assert "compare_digest" in source
    assert " == expected" not in source and "expected ==" not in source
