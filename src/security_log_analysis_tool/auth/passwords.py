"""Password hashing: stdlib ``scrypt``, no third-party crypto dependency.

Parameters follow OWASP's interactive-login guidance for scrypt (N=2**15, r=8,
p=1, 32-byte salt). Hashes are stored self-describing —
``scrypt$n$r$p$<salt-hex>$<digest-hex>`` — so the cost parameters can change
later without a migration script, and comparison always runs through
``hmac.compare_digest`` for constant-time verification.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ALGO = "scrypt"
_N = 2**15
_R = 8
_P = 1
_DKLEN = 32
_SALT_LEN = 32

# OpenSSL's default scrypt memory ceiling is 32 MiB, which N=2**15, r=8 sits
# right at the edge of (128*N*r bytes exactly) and can tip over depending on
# build/overhead. Give it deliberate headroom so hashing never fails on a
# memory-limit false negative.
_MAXMEM = 128 * 1024 * 1024

MIN_LENGTH = 12
_MIN_CHAR_CLASSES = 3


class WeakPasswordError(ValueError):
    """Raised when a candidate password fails the minimum policy (A07)."""


def validate_password_policy(password: str) -> None:
    """Raise :class:`WeakPasswordError` unless ``password`` meets the policy.

    Policy: at least :data:`MIN_LENGTH` characters, mixing at least
    :data:`_MIN_CHAR_CLASSES` of {lowercase, uppercase, digit, symbol}.
    """

    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_LENGTH} characters")

    classes = sum(
        (
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        )
    )
    if classes < _MIN_CHAR_CLASSES:
        raise WeakPasswordError(
            "password must mix at least 3 of: lowercase, uppercase, digit, symbol"
        )


def hash_password(password: str) -> str:
    """Hash ``password`` with a fresh random salt."""

    salt = os.urandom(_SALT_LEN)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM
    )
    return f"{_ALGO}${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Return whether ``password`` matches ``stored_hash``. Never raises."""

    parts = stored_hash.split("$")
    if len(parts) != 6 or parts[0] != _ALGO:
        return False
    _, n_s, r_s, p_s, salt_hex, digest_hex = parts
    try:
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected), maxmem=_MAXMEM
    )
    return hmac.compare_digest(candidate, expected)
