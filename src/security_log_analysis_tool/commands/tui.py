"""``tui`` subcommand: launch the Textual interface.

Registered through the auto-discovery registry — this file is added without
touching ``cli.py``. Console logging is disabled while the TUI owns the
terminal (a Rich console handler would corrupt the full-screen display); the
rotating file handlers still capture everything the Tool Logs screen reads.
"""

from __future__ import annotations

import argparse

from ..logging_setup import configure_logging
from ..tui.app import SLATApp

_DEFAULT_RULES_PATH = "config/rules.yaml"


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tui", help="Launch the interactive terminal UI")
    parser.add_argument("--rules", default=_DEFAULT_RULES_PATH, help="Path to the rules YAML file")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    log_paths = configure_logging(console=False)
    app = SLATApp(rules_path=args.rules, log_paths=log_paths)
    app.run()
    return 0
