"""Login service: authenticate, track failures, and enforce lockout.

Lockout policy (OWASP A07): :data:`MAX_FAILED_ATTEMPTS` consecutive failures
locks the account for :data:`LOCKOUT_DURATION`. A locked account is rejected
even with the *correct* password — the lock check runs before the password
comparison. The wall clock is injectable (``clock``) so lockout expiry is
deterministic in tests rather than sleep-based.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..models import Role, User
from .passwords import hash_password, validate_password_policy, verify_password
from .store import UserStore, UserStoreError

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AuthenticationError(Exception):
    """Raised for any login failure. Message is safe to display to the user."""


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated identity used for subsequent authorization checks."""

    username: str
    role: Role


class AuthService:
    """Creates users and authenticates login attempts against a :class:`UserStore`."""

    def __init__(self, store: UserStore, *, clock: Clock = _utc_now) -> None:
        self._store = store
        self._clock = clock

    def create_user(self, username: str, password: str, role: Role) -> None:
        username = username.strip()
        if not username:
            raise ValueError("username must not be empty")
        validate_password_policy(password)
        user = User(username=username, password_hash=hash_password(password), role=role)
        self._store.add_user(user)

    def login(self, username: str, password: str) -> Principal:
        user = self._store.get_user(username.strip())
        if user is None:
            # Same message as a bad password: don't reveal whether the account exists.
            raise AuthenticationError("invalid username or password")

        now = self._clock()
        if user.locked_until is not None and now < user.locked_until:
            raise AuthenticationError(f"account locked until {user.locked_until.isoformat()}")

        if not verify_password(password, user.password_hash):
            self._record_failure(user, now)
            raise AuthenticationError("invalid username or password")

        if user.failed_attempts or user.locked_until is not None:
            self._store.update_auth_state(user.username, failed_attempts=0, locked_until=None)

        return Principal(username=user.username, role=user.role)

    def _record_failure(self, user: User, now: datetime) -> None:
        attempts = user.failed_attempts + 1
        locked_until = now + LOCKOUT_DURATION if attempts >= MAX_FAILED_ATTEMPTS else None
        self._store.update_auth_state(
            user.username, failed_attempts=attempts, locked_until=locked_until
        )


__all__ = [
    "MAX_FAILED_ATTEMPTS",
    "LOCKOUT_DURATION",
    "AuthenticationError",
    "AuthService",
    "Principal",
    "UserStoreError",
]
