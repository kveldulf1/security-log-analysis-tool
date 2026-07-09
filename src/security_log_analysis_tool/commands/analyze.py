"""``analyze`` subcommand: run the full parse/detect/correlate pipeline over one
or more log files, print a Rich console report, and optionally export findings.

Exit-code contract (documented, CI-friendly): 0 = no HIGH-or-above finding, 1 = at
least one HIGH/CRITICAL finding, 2 = configuration/usage error (bad rules file,
unreadable log file, unknown format, bad flag value) — the generic ``ConfigError``
-> exit 2 handling already lives in ``cli.py``.
"""

from __future__ import annotations

import argparse

from rich.console import Console

from ..config import ConfigError, load_rules
from ..export.csv_export import write_csv
from ..export.json_export import write_json
from ..export.sarif_export import write_sarif
from ..models import Severity
from ..pipeline.engine import AnalysisEngine
from ..report.console import render_report

_DEFAULT_RULES_PATH = "config/rules.yaml"

_EXPORTERS = {
    "json": write_json,
    "csv": write_csv,
    "sarif": write_sarif,
}


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "analyze", help="Analyze one or more log files for suspicious activity"
    )
    parser.add_argument("files", nargs="+", help="Log files to analyze")
    parser.add_argument("--rules", default=_DEFAULT_RULES_PATH, help="Path to the rules YAML file")
    parser.add_argument(
        "--format",
        dest="fmt",
        default="auto",
        choices=("auto", "apache", "syslog"),
        help="Log format (auto-detected per file by default)",
    )
    parser.add_argument(
        "--export", dest="export_format", choices=tuple(_EXPORTERS), help="Export format"
    )
    parser.add_argument("--output", help="Export output file path (required with --export)")
    parser.add_argument(
        "--no-alerts", action="store_true", help="Do not dispatch alerts for this run"
    )
    parser.add_argument(
        "--min-severity",
        default="low",
        help="Minimum severity to display/export (low|medium|high|critical)",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    config = load_rules(args.rules)
    engine = AnalysisEngine(config)
    result = engine.analyze(args.files, fmt=args.fmt)

    try:
        min_severity = Severity.from_name(args.min_severity)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    visible = [f for f in result.findings if f.severity >= min_severity]

    console = Console()
    render_report(
        console, visible, event_count=len(result.events), failure_count=len(result.failures)
    )

    if args.export_format:
        if not args.output:
            raise ConfigError("--output is required when --export is given")
        _EXPORTERS[args.export_format](visible, args.output)
        console.print(f"\nExported {len(visible)} finding(s) to {args.output}")

    has_high_or_above = any(f.severity >= Severity.HIGH for f in result.findings)
    return 1 if has_high_or_above else 0
