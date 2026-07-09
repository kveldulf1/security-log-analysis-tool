"""Authentication, authorization, and the SQLite user store."""

from __future__ import annotations

from .authz import AuthorizationError, has_permission, permissions_for, require
from .passwords import WeakPasswordError, hash_password, validate_password_policy, verify_password
from .service import AuthenticationError, AuthService, Principal
from .store import UserStore, UserStoreError, default_db_path

__all__ = [
    "AuthenticationError",
    "AuthService",
    "AuthorizationError",
    "Principal",
    "UserStore",
    "UserStoreError",
    "WeakPasswordError",
    "default_db_path",
    "has_permission",
    "hash_password",
    "permissions_for",
    "require",
    "validate_password_policy",
    "verify_password",
]
