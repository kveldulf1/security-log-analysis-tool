"""Rich console reporting: findings table, correlation callouts, run summary."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from ..models import Finding, Severity
from ..redaction import redact

_SEVERITY_STYLE = {
    Severity.LOW: "dim",
    Severity.MEDIUM: "yellow",
    Severity.HIGH: "bold dark_orange",
    Severity.CRITICAL: "bold red",
}


def render_report(
    console: Console,
    findings: Sequence[Finding],
    *,
    event_count: int,
    failure_count: int,
) -> None:
    """Print the full findings report: correlated callouts, findings table, summary."""

    ordered = sorted(findings, key=lambda f: (-int(f.severity), f.first_seen))
    correlated = [f for f in ordered if f.correlated_rule_ids]

    if correlated:
        console.print("[bold red]Correlated multi-vector attacks[/bold red]")
        for finding in correlated:
            title = redact(finding.title)
            console.print(f"  • {title} — rules: {', '.join(finding.correlated_rule_ids)}")
        console.print()

    console.print(_build_table(ordered))
    console.print(
        f"\n{len(ordered)} finding(s) across {event_count} event(s); "
        f"{failure_count} line(s) failed to parse."
    )


def _build_table(findings: Sequence[Finding]) -> Table:
    table = Table(title="Findings")
    table.add_column("Severity")
    table.add_column("Rule")
    table.add_column("Title")
    table.add_column("IP")
    table.add_column("Count", justify="right")
    table.add_column("First seen")
    table.add_column("Last seen")

    for finding in findings:
        style = _SEVERITY_STYLE.get(finding.severity, "")
        severity_text = (
            f"[{style}]{finding.severity.name}[/{style}]" if style else finding.severity.name
        )
        table.add_row(
            severity_text,
            finding.rule_id,
            redact(finding.title),
            finding.ip or "-",
            str(finding.count),
            finding.first_seen.isoformat(),
            finding.last_seen.isoformat(),
        )
    return table
