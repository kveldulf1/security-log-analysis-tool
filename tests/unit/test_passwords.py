"""Tests for scrypt hashing and the password policy, positive and negative."""

from __future__ import annotations

import pytest

from security_log_analysis_tool.auth.passwords import (
    WeakPasswordError,
    hash_password,
    validate_password_policy,
    verify_password,
)


def test_hash_and_verify_roundtrip() -> None:
    stored = hash_password("Password123!")
    assert verify_password("Password123!", stored) is True


def test_verify_rejects_wrong_password() -> None:
    stored = hash_password("Password123!")
    assert verify_password("wrong-password", stored) is False


def test_hash_is_not_plaintext() -> None:
    stored = hash_password("Password123!")
    assert "Password123!" not in stored


def test_two_hashes_of_same_password_use_different_salts() -> None:
    a = hash_password("Password123!")
    b = hash_password("Password123!")
    assert a != b  # unique salt each time
    assert verify_password("Password123!", a)
    assert verify_password("Password123!", b)


def test_verify_rejects_malformed_stored_hash() -> None:
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "scrypt$bad$format") is False
    assert verify_password("anything", "bcrypt$32768$8$1$aa$bb") is False


@pytest.mark.parametrize(
    "password",
    ["Password123!", "P@ssword123?", "Str0ng-Pass_word"],
)
def test_policy_accepts_strong_passwords(password: str) -> None:
    validate_password_policy(password)  # must not raise


@pytest.mark.parametrize(
    "password",
    [
        "short1A!",  # too short (8 chars)
        "alllowercaseonly",  # 1 class: lowercase only
        "ALLUPPERCASEONLY",  # 1 class: uppercase only
        "123456789012345",  # 1 class: digits only
        "lowercaseANDupper",  # 2 classes: lower + upper only
    ],
)
def test_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_password_policy(password)
