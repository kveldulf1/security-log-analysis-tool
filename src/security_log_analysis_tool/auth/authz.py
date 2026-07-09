"""Authorization: role -> permission mapping, enforced at the service layer.

The TUI and CLI only *hide* actions a role can't perform; every privileged
operation must additionally call :func:`require` so enforcement holds even if
a UI surface forgets to hide something (A01 — broken access control).
"""

from __future__ import annotations

from ..models import Permission, Role
from .service import Principal

_ANALYST_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.RUN_ANALYSIS,
        Permission.STOP_OWN_JOB,
        Permission.VIEW_FINDINGS,
        Permission.VIEW_OWN_TOOL_LOGS,
        Permission.EXPORT_FINDINGS,
    }
)

_ADMIN_PERMISSIONS: frozenset[Permission] = _ANALYST_PERMISSIONS | frozenset(
    {
        Permission.MANAGE_USERS,
        Permission.MANAGE_RULES,
        Permission.VIEW_ALL_TOOL_LOGS,
        Permission.STOP_ANY_JOB,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ANALYST: _ANALYST_PERMISSIONS,
    Role.ADMIN: _ADMIN_PERMISSIONS,
}


class AuthorizationError(Exception):
    """Raised when a principal lacks a required permission."""


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def require(principal: Principal, permission: Permission) -> None:
    """Raise :class:`AuthorizationError` unless ``principal`` holds ``permission``."""

    if not has_permission(principal.role, permission):
        raise AuthorizationError(
            f"{principal.username!r} ({principal.role.value}) lacks permission {permission.value!r}"
        )
