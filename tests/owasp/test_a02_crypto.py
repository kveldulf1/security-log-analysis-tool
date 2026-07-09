"""OWASP A02 - Cryptographic Failures.

Passwords are never stored in a recoverable form: raw db bytes never contain
either dummy account's plaintext password, salts are unique per user, and
verification uses a constant-time comparison.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from security_log_analysis_tool.auth.passwords import hash_password, verify_password
from security_log_analysis_tool.auth.service import AuthenticationError, AuthService
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.models import Role

pytestmark = pytest.mark.owasp

_ADMIN_PASSWORD = "Password123!"
_ANALYST_PASSWORD = "P@ssword123?"


def test_hash_is_never_the_plaintext() -> None:
    stored = hash_password(_ADMIN_PASSWORD)
    assert _ADMIN_PASSWORD not in stored
    assert stored.startswith("scrypt$")


def test_two_users_with_identical_passwords_get_different_hashes() -> None:
    a = hash_password(_ADMIN_PASSWORD)
    b = hash_password(_ADMIN_PASSWORD)
    salt_a = a.split("$")[4]
    salt_b = b.split("$")[4]
    assert salt_a != salt_b  # unique salt per hash, even for identical passwords


def test_verify_password_uses_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    import hmac as hmac_module

    calls = {"count": 0}
    real_compare = hmac_module.compare_digest

    def _spy(a: bytes, b: bytes) -> bool:
        calls["count"] += 1
        return real_compare(a, b)

    monkeypatch.setattr("security_log_analysis_tool.auth.passwords.hmac.compare_digest", _spy)
    stored = hash_password(_ADMIN_PASSWORD)
    verify_password(_ADMIN_PASSWORD, stored)
    assert calls["count"] == 1


def test_raw_db_bytes_never_contain_either_demo_password(tmp_path: Path) -> None:
    db_path = tmp_path / "users.db"
    with UserStore(db_path) as store:
        service = AuthService(store)
        service.create_user("amelia.reyes", _ADMIN_PASSWORD, Role.ADMIN)
        service.create_user("oscar.lindqvist", _ANALYST_PASSWORD, Role.ANALYST)

    raw = db_path.read_bytes()
    assert _ADMIN_PASSWORD.encode() not in raw
    assert _ANALYST_PASSWORD.encode() not in raw


def test_raw_db_bytes_survive_a_failed_login_without_leaking_the_attempt(tmp_path: Path) -> None:
    """A failed-login password is compared in memory only -- it must never be persisted."""

    db_path = tmp_path / "users.db"
    with UserStore(db_path) as store:
        service = AuthService(store)
        service.create_user("amelia.reyes", _ADMIN_PASSWORD, Role.ADMIN)
        with pytest.raises(AuthenticationError):
            service.login("amelia.reyes", "some-other-attempted-password")

    raw = db_path.read_bytes()
    assert b"some-other-attempted-password" not in raw
