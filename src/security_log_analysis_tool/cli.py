"""Command-line entry point: a thin auto-discovering subcommand dispatcher.

``cli.py`` deliberately knows nothing about individual commands. It scans the
``commands`` package at startup and lets each module register its own subparser via
a ``register(subparsers)`` hook. Later sessions add ``commands/<name>.py`` files and
never touch this file — that decoupling is what makes the parallel waves safe.

Configuration and format errors surface as a clean ``exit 2`` with an actionable
message, never a traceback.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Sequence

from . import __version__, commands
from .config import ConfigError
from .parsers import UnknownFormatError

# Errors that mean "the user's input/config was wrong" -> exit code 2.
_USAGE_ERRORS = (ConfigError, UnknownFormatError)


def discover_commands() -> list[object]:
    """Import every ``commands`` submodule that exposes a ``register`` hook."""

    modules: list[object] = []
    for info in pkgutil.iter_modules(commands.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{commands.__name__}.{info.name}")
        if hasattr(module, "register"):
            modules.append(module)
    return modules


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="security-log-analysis-tool",
        description="Parse, detect, and correlate suspicious activity across logs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for module in discover_commands():
        module.register(subparsers)  # type: ignore[attr-defined]
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        # No subcommand: behave as a friendly no-op (and keep --version working).
        print("security-log-analysis-tool is ready. Try --help for commands.")
        return 0

    try:
        result = func(args)
    except _USAGE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # A command may return None to mean "success"; normalize to an exit code.
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
