"""CLI-level robustness tests for the ``users`` command that aren't OWASP-specific.

A non-interactive environment (no SLAT_USERNAME/PASSWORD and no terminal to
prompt on, e.g. CI) must fail with a clean exit 2, never an unhandled
EOFError traceback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from security_log_analysis_tool import cli
from security_log_analysis_tool.auth.passwords import hash_password
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.models import Role, User


@pytest.fixture
def users_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "users.db"
    monkeypatch.setenv("SLAT_USERS_DB", str(db_path))
    with UserStore(db_path) as store:
        store.add_user(
            User(
                username="amelia.reyes",
                password_hash=hash_password("Password123!"),
                role=Role.ADMIN,
            )
        )
    return db_path


@pytest.fixture
def empty_users_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "users.db"
    monkeypatch.setenv("SLAT_USERS_DB", str(db_path))
    return db_path


def _raise_eof(*_args: object, **_kwargs: object):
    raise EOFError


def test_no_credentials_and_no_terminal_exits_cleanly(
    users_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SLAT_USERNAME", raising=False)
    monkeypatch.delenv("SLAT_PASSWORD", raising=False)
    monkeypatch.setattr("builtins.input", _raise_eof)
    monkeypatch.setattr("getpass.getpass", _raise_eof)

    code = cli.main(["users", "list"])

    assert code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "no credentials available" in err


def test_add_with_no_password_and_no_terminal_exits_cleanly(
    users_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SLAT_USERNAME", "amelia.reyes")
    monkeypatch.setenv("SLAT_PASSWORD", "Password123!")
    monkeypatch.setattr("getpass.getpass", _raise_eof)

    code = cli.main(["users", "add", "charlie", "--role", "analyst"])

    assert code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "no password provided" in err
    with UserStore(users_db) as store:
        assert store.get_user("charlie") is None


def test_seed_demo_is_idempotent(empty_users_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    first = cli.main(["users", "seed-demo"])
    out_first = capsys.readouterr().out
    second = cli.main(["users", "seed-demo"])
    out_second = capsys.readouterr().out

    assert first == 0
    assert second == 0
    assert "created demo accounts" in out_first
    assert "already present, skipped" in out_second
    with UserStore(empty_users_db) as store:
        assert store.get_user("amelia.reyes") is not None
        assert store.get_user("oscar.lindqvist") is not None
