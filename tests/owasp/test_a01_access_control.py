"""OWASP A01 - Broken Access Control.

The full authorization matrix, proven at BOTH layers: the service layer
(``auth.authz.require`` — the layer that actually enforces) and the CLI
(``users`` subcommands — an analyst invoking an admin operation must be
denied end-to-end, not just have a hidden menu item).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from security_log_analysis_tool import cli
from security_log_analysis_tool.auth.authz import AuthorizationError, require
from security_log_analysis_tool.auth.passwords import hash_password
from security_log_analysis_tool.auth.service import AuthenticationError, AuthService, Principal
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.models import Permission, Role, User

pytestmark = pytest.mark.owasp

_ADMIN_ONLY = (
    Permission.MANAGE_USERS,
    Permission.MANAGE_RULES,
    Permission.VIEW_ALL_TOOL_LOGS,
    Permission.STOP_ANY_JOB,
)


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
        store.add_user(
            User(
                username="oscar.lindqvist",
                password_hash=hash_password("P@ssword123?"),
                role=Role.ANALYST,
            )
        )
    return db_path


def _login_as(monkeypatch: pytest.MonkeyPatch, username: str, password: str) -> None:
    monkeypatch.setenv("SLAT_USERNAME", username)
    monkeypatch.setenv("SLAT_PASSWORD", password)


# --- service layer: the actual enforcement point ---


@pytest.mark.parametrize("permission", _ADMIN_ONLY)
def test_service_layer_denies_admin_only_permissions_to_analyst(permission: Permission) -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError):
        require(analyst, permission)


@pytest.mark.parametrize("permission", list(Permission))
def test_service_layer_grants_every_permission_to_admin(permission: Permission) -> None:
    admin = Principal(username="amelia.reyes", role=Role.ADMIN)
    require(admin, permission)  # must not raise


# --- CLI layer: enforcement holds through the real entrypoint, not just the service call ---


def test_cli_users_add_denied_for_analyst(
    users_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _login_as(monkeypatch, "oscar.lindqvist", "P@ssword123?")
    code = cli.main(
        ["users", "add", "charlie", "--role", "analyst", "--password", "Str0ng-Pass_word"]
    )
    assert code == 2
    assert "lacks permission" in capsys.readouterr().err
    with UserStore(users_db) as store:
        assert store.get_user("charlie") is None


def test_cli_users_add_allowed_for_admin(users_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _login_as(monkeypatch, "amelia.reyes", "Password123!")
    code = cli.main(
        ["users", "add", "charlie", "--role", "analyst", "--password", "Str0ng-Pass_word"]
    )
    assert code == 0
    with UserStore(users_db) as store:
        assert store.get_user("charlie") is not None


def test_cli_users_remove_denied_for_analyst(
    users_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login_as(monkeypatch, "oscar.lindqvist", "P@ssword123?")
    code = cli.main(["users", "remove", "amelia.reyes"])
    assert code == 2
    with UserStore(users_db) as store:
        assert store.get_user("amelia.reyes") is not None  # untouched


def test_cli_users_remove_allowed_for_admin(
    users_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login_as(monkeypatch, "amelia.reyes", "Password123!")
    code = cli.main(["users", "remove", "oscar.lindqvist"])
    assert code == 0
    with UserStore(users_db) as store:
        assert store.get_user("oscar.lindqvist") is None


def test_cli_users_list_denied_for_analyst(users_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _login_as(monkeypatch, "oscar.lindqvist", "P@ssword123?")
    assert cli.main(["users", "list"]) == 2


def test_cli_users_list_allowed_for_admin(
    users_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _login_as(monkeypatch, "amelia.reyes", "Password123!")
    assert cli.main(["users", "list"]) == 0
    out = capsys.readouterr().out
    assert "amelia.reyes" in out
    assert "oscar.lindqvist" in out


def test_analyst_cannot_stop_another_users_job_but_can_stop_own() -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError):
        require(analyst, Permission.STOP_ANY_JOB)
    require(analyst, Permission.STOP_OWN_JOB)


def test_locked_account_rejected_even_with_correct_password(
    users_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with UserStore(users_db) as store:
        service = AuthService(store)
        for _ in range(5):
            with pytest.raises(AuthenticationError):
                service.login("oscar.lindqvist", "wrong-password")
        with pytest.raises(AuthenticationError, match="locked"):
            service.login("oscar.lindqvist", "P@ssword123?")
