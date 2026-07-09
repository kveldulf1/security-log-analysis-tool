"""Table-driven tests for the redaction choke point."""

from __future__ import annotations

import pytest

from security_log_analysis_tool.redaction import REDACTED, REDACTED_EMAIL, redact

# Synthetic, obviously-fake credential literals used only as test fixtures.
_FAKE_GH_PAT = "ghp_EXAMPLEexampleEXAMPLEexample0000"
_FAKE_ANTHROPIC = "sk-ant-EXAMPLEexampleEXAMPLE00"
_FAKE_OPENAI_PROJ = "sk-proj-EXAMPLEexampleEXAMPLEexample00"
_FAKE_OPENAI_SVC = "sk-svcacct-EXAMPLEexampleEXAMPLE00"
_FAKE_AWS = "AKIAEXAMPLE0000EXAMP"


@pytest.mark.parametrize(
    ("raw", "must_contain", "must_not_contain"),
    [
        # key=value credentials
        ("login failed password=Password123!", REDACTED, "Password123!"),
        ("analyst password: 'P@ssword123?'", REDACTED, "P@ssword123?"),
        ("db token=super-secret-value", REDACTED, "super-secret-value"),
        ("api_key = 0123456789abcdef", REDACTED, "0123456789abcdef"),
        ("client_secret=hunter2hunter2", REDACTED, "hunter2hunter2"),
        # Authorization header, with and without Bearer
        ("Authorization: Bearer abcdef.ghijkl.mnopqr", REDACTED, "abcdef.ghijkl"),
        ("authorization=raw-opaque-token", REDACTED, "raw-opaque-token"),
        # URL inline credentials
        (
            "cloning https://alice:hunter2@example.com/repo.git",
            "https://" + REDACTED + "@example.com",
            "hunter2",
        ),
        # Password containing '@' must be fully scrubbed (not stop at first '@')
        (
            "conn postgres://user:p@ssw0rd-secret@db.example.com/app",
            "postgres://" + REDACTED + "@db.example.com",
            "ssw0rd-secret",
        ),
        # Colon-less token in userinfo position
        (
            "fetch https://gho_tokenvalue123@github.com/x",
            "https://" + REDACTED + "@github.com",
            "gho_tokenvalue123",
        ),
        # Provider token shapes
        (f"leaked {_FAKE_GH_PAT} here", REDACTED, _FAKE_GH_PAT),
        (f"key {_FAKE_ANTHROPIC} here", REDACTED, _FAKE_ANTHROPIC),
        (f"openai {_FAKE_OPENAI_PROJ} here", REDACTED, _FAKE_OPENAI_PROJ),
        (f"openai {_FAKE_OPENAI_SVC} here", REDACTED, _FAKE_OPENAI_SVC),
        (f"aws {_FAKE_AWS} here", REDACTED, _FAKE_AWS),
        # Email PII
        ("contact john.doe@example.com now", REDACTED_EMAIL, "john.doe@example.com"),
    ],
)
def test_redacts_secrets(raw: str, must_contain: str, must_not_contain: str) -> None:
    out = redact(raw)
    assert must_contain in out
    assert must_not_contain not in out


def test_redacts_private_key_block() -> None:
    raw = (
        "config -----BEGIN RSA PRIVATE KEY-----\n"
        "AAAAB3NzaC1yc2EAAAADAQABAAAB\nfake-key-body\n"
        "-----END RSA PRIVATE KEY----- tail"
    )
    out = redact(raw)
    assert "PRIVATE KEY" not in out
    assert "fake-key-body" not in out
    assert out.startswith("config ") and out.endswith(" tail")


@pytest.mark.parametrize(
    "benign",
    [
        # A bare apostrophe surname must survive untouched — it is not a secret.
        "GET /search?q=O'Brien HTTP/1.1",
        '10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "POST /login HTTP/1.1" 200 1234',
        "Failed password for invalid user admin from 203.0.113.5 port 54321 ssh2",
        "user amelia.reyes logged in",
    ],
)
def test_leaves_benign_text_unchanged(benign: str) -> None:
    assert redact(benign) == benign


def test_redaction_is_idempotent() -> None:
    raw = "password=Password123! from john@example.com token=abcdefabcdef"
    once = redact(raw)
    assert redact(once) == once


def test_redact_coerces_non_str() -> None:
    assert redact(1234) == "1234"
    assert redact(None) == "None"
