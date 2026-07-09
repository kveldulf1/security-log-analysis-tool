"""``watch`` subcommand: follow one or more log files and report findings live.

Registered through the auto-discovery registry (``register(subparsers)``), so this
file is added without ever touching ``cli.py``. Unlike ``analyze``, ``watch`` is a
long-running monitor rather than a CI gate: it always exits 0 on a clean ``Ctrl+C``
and streams each new finding as its triggering line arrives.
"""

from __future__ import annotations

import argparse
import threading

from rich.console import Console

from ..config import load_rules
from ..models import Finding
from ..pipeline.watch import WatchSession
from ..redaction import redact

_DEFAULT_RULES_PATH = "config/rules.yaml"
_DEFAULT_POLL_INTERVAL = 0.5

_SEVERITY_STYLE = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
}


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "watch", help="Follow log files and report suspicious activity as it appears"
    )
    parser.add_argument("files", nargs="+", help="Log files to follow")
    parser.add_argument("--rules", default=_DEFAULT_RULES_PATH, help="Path to the rules YAML file")
    parser.add_argument(
        "--format",
        dest="fmt",
        default="auto",
        choices=("auto", "apache", "syslog"),
        help="Log format (auto-detected per file by default)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL,
        help="Seconds between polls for new lines (default: 0.5)",
    )
    parser.set_defaults(func=run)


def _print_findings(console: Console, findings: list[Finding]) -> None:
    for finding in sorted(findings, key=lambda f: -int(f.severity)):
        style = _SEVERITY_STYLE.get(finding.severity.name, "")
        label = f"[{style}]{finding.severity.name}[/{style}]" if style else finding.severity.name
        console.print(f"{label} {redact(finding.title)} [{finding.rule_id}]")


def run(args: argparse.Namespace) -> int:
    config = load_rules(args.rules)
    console = Console()

    session = WatchSession(
        args.files,
        config,
        fmt=args.fmt,
        poll_interval=args.interval,
        on_findings=lambda findings: _print_findings(console, findings),
    )

    console.print(
        f"Watching {len(args.files)} file(s) for suspicious activity — press Ctrl+C to stop."
    )
    stop = threading.Event()
    try:
        session.run(stop)
    except KeyboardInterrupt:
        stop.set()

    console.print(
        f"\nStopped. {session.finding_count} finding(s) across {session.event_count} event(s); "
        f"{session.failure_count} line(s) failed to parse."
    )
    return 0
