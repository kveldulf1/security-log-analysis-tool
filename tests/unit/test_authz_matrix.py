"""Full authorization matrix: every Permission x {admin, analyst}, positive AND negative.

This is the A01 access-control proof: enforcement is asserted at the service
layer (``auth.authz.require``), not merely "the TUI hides the button".
"""

from __future__ import annotations

import pytest

from security_log_analysis_tool.auth.authz import (
    ROLE_PERMISSIONS,
    AuthorizationError,
    has_permission,
    require,
)
from security_log_analysis_tool.auth.service import Principal
from security_log_analysis_tool.models import Permission, Role

_ANALYST_PERMISSIONS = frozenset(
    {
        Permission.RUN_ANALYSIS,
        Permission.STOP_OWN_JOB,
        Permission.VIEW_FINDINGS,
        Permission.VIEW_OWN_TOOL_LOGS,
        Permission.EXPORT_FINDINGS,
    }
)
_ADMIN_ONLY_PERMISSIONS = frozenset(
    {
        Permission.MANAGE_USERS,
        Permission.MANAGE_RULES,
        Permission.VIEW_ALL_TOOL_LOGS,
        Permission.STOP_ANY_JOB,
    }
)


def test_role_permission_map_matches_the_smallest_realistic_soc_set() -> None:
    assert ROLE_PERMISSIONS[Role.ANALYST] == _ANALYST_PERMISSIONS
    assert ROLE_PERMISSIONS[Role.ADMIN] == _ANALYST_PERMISSIONS | _ADMIN_ONLY_PERMISSIONS
    # Every permission the enum defines is assigned to at least one role.
    assigned = ROLE_PERMISSIONS[Role.ADMIN] | ROLE_PERMISSIONS[Role.ANALYST]
    assert assigned == frozenset(Permission)


@pytest.mark.parametrize("permission", list(Permission))
def test_admin_holds_every_permission(permission: Permission) -> None:
    admin = Principal(username="amelia.reyes", role=Role.ADMIN)
    assert has_permission(admin.role, permission) is True
    require(admin, permission)  # must not raise


@pytest.mark.parametrize("permission", sorted(_ANALYST_PERMISSIONS, key=lambda p: p.value))
def test_analyst_holds_analyst_permissions(permission: Permission) -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    assert has_permission(analyst.role, permission) is True
    require(analyst, permission)  # must not raise


@pytest.mark.parametrize("permission", sorted(_ADMIN_ONLY_PERMISSIONS, key=lambda p: p.value))
def test_analyst_denied_admin_only_permissions(permission: Permission) -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    assert has_permission(analyst.role, permission) is False
    with pytest.raises(AuthorizationError):
        require(analyst, permission)


def test_analyst_cannot_manage_users_add_remove_shaped_check() -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError):
        require(analyst, Permission.MANAGE_USERS)


def test_analyst_cannot_stop_another_users_job() -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError):
        require(analyst, Permission.STOP_ANY_JOB)
    # ...but can stop their own.
    require(analyst, Permission.STOP_OWN_JOB)


def test_analyst_cannot_view_all_tool_logs_but_can_view_own() -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError):
        require(analyst, Permission.VIEW_ALL_TOOL_LOGS)
    require(analyst, Permission.VIEW_OWN_TOOL_LOGS)


def test_analyst_cannot_manage_rules() -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError):
        require(analyst, Permission.MANAGE_RULES)


def test_authorization_error_message_is_actionable_and_not_leaky() -> None:
    analyst = Principal(username="oscar.lindqvist", role=Role.ANALYST)
    with pytest.raises(AuthorizationError) as exc:
        require(analyst, Permission.MANAGE_USERS)
    message = str(exc.value)
    assert "oscar.lindqvist" in message
    assert "manage_users" in message
    assert "Password123!" not in message
    assert "P@ssword123?" not in message
