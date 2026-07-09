"""Step implementations for auth.feature.

Uses an in-memory ``UserStore`` (SQLite ``:memory:``) so each scenario gets an
isolated, filesystem-free user database that needs no teardown.
"""

from __future__ import annotations

import contextlib

from behave import given, then, when

from security_log_analysis_tool.auth.authz import AuthorizationError, require
from security_log_analysis_tool.auth.passwords import WeakPasswordError
from security_log_analysis_tool.auth.service import AuthenticationError, AuthService, Principal
from security_log_analysis_tool.auth.store import UserStore
from security_log_analysis_tool.models import Permission, Role

_DEMO_PASSWORDS = {"amelia.reyes": "Password123!", "oscar.lindqvist": "P@ssword123?"}


def _session_for(context, username: str) -> None:
    user = context.auth_store.get_user(username)
    assert user is not None, f"no such user {username!r} — is the Background missing?"
    context.principal = Principal(username=user.username, role=user.role)


@given("a fresh user store")
def step_fresh_store(context) -> None:
    context.auth_store = UserStore(":memory:")
    context.auth_service = AuthService(context.auth_store)


@given('an admin user "{username}" with password "{password}"')
def step_admin_user(context, username: str, password: str) -> None:
    if context.auth_store.get_user(username) is None:
        context.auth_service.create_user(username, password, Role.ADMIN)


@given('an analyst user "{username}" with password "{password}"')
def step_analyst_user(context, username: str, password: str) -> None:
    if context.auth_store.get_user(username) is None:
        context.auth_service.create_user(username, password, Role.ANALYST)


@given('an analyst session for "{username}"')
def step_analyst_session(context, username: str) -> None:
    _session_for(context, username)


@given('an admin session for "{username}"')
def step_admin_session(context, username: str) -> None:
    _session_for(context, username)


@when("they attempt to manage users")
def step_attempt_manage_users(context) -> None:
    try:
        require(context.principal, Permission.MANAGE_USERS)
        context.auth_error = None
    except AuthorizationError as exc:
        context.auth_error = exc


@then("the attempt is denied with an authorization error")
def step_denied(context) -> None:
    assert context.auth_error is not None


@then("the attempt succeeds")
def step_succeeds(context) -> None:
    assert context.auth_error is None


@given('{count:d} consecutive failed login attempts for "{username}"')
def step_failed_attempts(context, count: int, username: str) -> None:
    for _ in range(count):
        with contextlib.suppress(AuthenticationError):
            context.auth_service.login(username, "definitely-wrong-password")


@when('"{username}" logs in with the correct password')
def step_login_correct_password(context, username: str) -> None:
    try:
        context.login_result = context.auth_service.login(username, _DEMO_PASSWORDS[username])
        context.login_error = None
    except AuthenticationError as exc:
        context.login_result = None
        context.login_error = exc


@then("the login is rejected as locked")
def step_rejected_as_locked(context) -> None:
    assert context.login_error is not None
    assert "locked" in str(context.login_error)


@when('an admin creates a user "{username}" with password "{password}"')
def step_admin_creates_user(context, username: str, password: str) -> None:
    try:
        context.auth_service.create_user(username, password, Role.ANALYST)
        context.create_error = None
    except WeakPasswordError as exc:
        context.create_error = exc


@then("the creation is rejected as a weak password")
def step_creation_rejected_weak(context) -> None:
    assert isinstance(context.create_error, WeakPasswordError)


@when('someone logs in as "{username}" with password "{password}"')
def step_someone_logs_in(context, username: str, password: str) -> None:
    try:
        context.login_result = context.auth_service.login(username, password)
        context.login_error = None
    except AuthenticationError as exc:
        context.login_result = None
        context.login_error = exc


@then("the login is rejected")
def step_login_rejected(context) -> None:
    assert context.login_error is not None


@then("no new user row is created")
def step_no_new_user_row(context) -> None:
    usernames = {u.username for u in context.auth_store.list_users()}
    assert usernames <= set(_DEMO_PASSWORDS)  # only the Background-seeded accounts exist
