"""``users`` subcommand: manage accounts (add/list/remove/seed-demo).

Every action except ``seed-demo`` authenticates the operator first (via
``SLAT_USERNAME``/``SLAT_PASSWORD`` in the environment/``.env``, falling back
to an interactive prompt) and then enforces ``Permission.MANAGE_USERS`` at the
service layer via :func:`auth.authz.require` — the authorization check lives
here, not just in what the TUI chooses to show.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from ..auth.authz import AuthorizationError, require
from ..auth.passwords import WeakPasswordError
from ..auth.service import AuthenticationError, AuthService, Principal
from ..auth.store import UserStore, UserStoreError
from ..config import apply_env, load_env_file
from ..models import Permission, Role

# The two dummy accounts mandated for the assessment. Plaintext here only
# (never in logs/reports — redaction guards every output path); README/docs
# reference these same values so a reviewer can log in without hunting.
DEMO_ACCOUNTS: tuple[tuple[str, str, Role], ...] = (
    ("amelia.reyes", "Password123!", Role.ADMIN),
    ("oscar.lindqvist", "P@ssword123?", Role.ANALYST),
)


def register(subparsers) -> None:
    parser = subparsers.add_parser("users", help="manage user accounts (admin)")
    actions = parser.add_subparsers(dest="users_command", metavar="<action>")

    add_p = actions.add_parser("add", help="create a new user account")
    add_p.add_argument("username")
    add_p.add_argument("--role", choices=[r.value for r in Role], required=True)
    add_p.add_argument("--password", help="omit to be prompted (recommended)")
    add_p.set_defaults(func=_run_add)

    list_p = actions.add_parser("list", help="list user accounts")
    list_p.set_defaults(func=_run_list)

    remove_p = actions.add_parser("remove", help="delete a user account")
    remove_p.add_argument("username")
    remove_p.set_defaults(func=_run_remove)

    seed_p = actions.add_parser("seed-demo", help="create the two demo accounts (idempotent)")
    seed_p.set_defaults(func=_run_seed_demo)

    parser.set_defaults(func=_run_no_action)


def _run_no_action(_args) -> int:
    print("usage: security-log-analysis-tool users {add,list,remove,seed-demo}", file=sys.stderr)
    return 2


def _load_dotenv() -> None:
    apply_env(load_env_file(Path(".env")))


def _authenticate_operator(service: AuthService) -> Principal:
    """Authenticate the CLI operator from env/.env, prompting for whatever is missing."""

    _load_dotenv()
    try:
        username = os.environ.get("SLAT_USERNAME") or input("username: ")
        password = os.environ.get("SLAT_PASSWORD") or getpass.getpass("password: ")
    except (EOFError, KeyboardInterrupt) as exc:
        # No terminal to prompt on (e.g. CI) and no env credentials configured.
        raise AuthenticationError(
            "no credentials available: set SLAT_USERNAME/SLAT_PASSWORD or run interactively"
        ) from exc
    return service.login(username, password)


def _require_manage_users(service: AuthService) -> Principal | None:
    """Authenticate + authorize an admin operator. Prints an error and returns None on failure."""

    try:
        principal = _authenticate_operator(service)
        require(principal, Permission.MANAGE_USERS)
    except (AuthenticationError, AuthorizationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    return principal


def _run_add(args) -> int:
    with UserStore() as store:
        service = AuthService(store)
        if _require_manage_users(service) is None:
            return 2

        try:
            password = args.password or getpass.getpass(f"password for {args.username}: ")
        except (EOFError, KeyboardInterrupt):
            print(
                "error: no password provided (pass --password or run interactively)",
                file=sys.stderr,
            )
            return 2

        try:
            service.create_user(args.username, password, Role(args.role))
        except (WeakPasswordError, UserStoreError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    print(f"created user {args.username!r} ({args.role})")
    return 0


def _run_list(_args) -> int:
    with UserStore() as store:
        service = AuthService(store)
        if _require_manage_users(service) is None:
            return 2
        users = store.list_users()

    if not users:
        print("no users")
        return 0
    for user in users:
        lock_note = " (locked)" if user.locked_until else ""
        print(f"{user.username}\t{user.role.value}{lock_note}")
    return 0


def _run_remove(args) -> int:
    with UserStore() as store:
        service = AuthService(store)
        if _require_manage_users(service) is None:
            return 2
        removed = store.remove_user(args.username)

    if not removed:
        print(f"error: no such user {args.username!r}", file=sys.stderr)
        return 2
    print(f"removed user {args.username!r}")
    return 0


def _run_seed_demo(_args) -> int:
    with UserStore() as store:
        service = AuthService(store)
        created: list[str] = []
        skipped: list[str] = []
        for username, password, role in DEMO_ACCOUNTS:
            if store.get_user(username) is not None:
                skipped.append(username)
                continue
            service.create_user(username, password, role)
            created.append(username)

    if created:
        print(f"created demo accounts: {', '.join(created)}")
    if skipped:
        print(f"already present, skipped: {', '.join(skipped)}")
    return 0
