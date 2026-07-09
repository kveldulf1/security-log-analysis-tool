"""Cross-source correlation: escalate when one IP triggers several distinct
detection rules across distinct log sources within a time window.

This is deliberately separate from ``detection/`` — a correlation rule consumes
the *findings* other rules already produced, not raw events, so it lives one
layer up in the pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta

from ..config import RuleConfig
from ..detection.base import new_finding_id
from ..models import Finding, LogSource

_DEFAULT_MIN_DISTINCT_RULES = 2
_DEFAULT_REQUIRE_DISTINCT_SOURCES = True


def correlate(
    findings: Sequence[Finding],
    correlation_rules: Sequence[RuleConfig],
    rule_sources: dict[str, LogSource | None],
) -> list[Finding]:
    """Run every ``multi-vector-correlation`` rule config over ``findings``.

    ``rule_sources`` maps a detector rule id to the log source it was configured
    for, so correlation can require findings to span distinct sources.
    """

    correlated: list[Finding] = []
    for rule_config in correlation_rules:
        correlated.extend(_correlate_one(findings, rule_config, rule_sources))
    return correlated


def _correlate_one(
    findings: Sequence[Finding],
    rule_config: RuleConfig,
    rule_sources: dict[str, LogSource | None],
) -> list[Finding]:
    min_distinct_rules = int(
        rule_config.params.get("min_distinct_rules", _DEFAULT_MIN_DISTINCT_RULES)
    )
    require_distinct_sources = bool(
        rule_config.params.get("require_distinct_sources", _DEFAULT_REQUIRE_DISTINCT_SOURCES)
    )

    by_ip: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        if finding.ip is not None:
            by_ip[finding.ip].append(finding)

    results: list[Finding] = []
    for ip, ip_findings in by_ip.items():
        ordered = sorted(ip_findings, key=lambda f: f.first_seen)
        group = _find_correlated_group(
            ordered,
            rule_config.window_seconds,
            min_distinct_rules,
            require_distinct_sources,
            rule_sources,
        )
        if group is not None:
            results.append(_build_finding(rule_config, ip, group))
    return results


def _find_correlated_group(
    ip_findings: Sequence[Finding],
    window_seconds: int,
    min_distinct_rules: int,
    require_distinct_sources: bool,
    rule_sources: dict[str, LogSource | None],
) -> list[Finding] | None:
    """Return the earliest set of one IP's findings that satisfies the
    correlation thresholds within ``window_seconds``, or ``None`` if none do."""

    for i, anchor in enumerate(ip_findings):
        window_end = anchor.first_seen + timedelta(seconds=window_seconds)
        group = [f for f in ip_findings[i:] if f.first_seen <= window_end]
        distinct_rules = {f.rule_id for f in group}
        distinct_sources = {rule_sources.get(rid) for rid in distinct_rules}
        distinct_sources.discard(None)
        if len(distinct_rules) >= min_distinct_rules and (
            not require_distinct_sources or len(distinct_sources) >= 2
        ):
            return group
    return None


def _build_finding(rule_config: RuleConfig, ip: str, group: Sequence[Finding]) -> Finding:
    rule_ids = tuple(sorted({f.rule_id for f in group}))
    evidence = tuple(e for f in group for e in f.evidence)
    users = tuple(sorted({u for f in group for u in f.users}))
    return Finding(
        finding_id=new_finding_id(),
        rule_id=rule_config.id,
        severity=rule_config.severity,
        title=f"Multi-vector attack correlated on {ip}",
        description=(
            f"{ip} triggered {len(rule_ids)} distinct rules ({', '.join(rule_ids)}) "
            "across multiple log sources within one window — likely a single "
            "coordinated attack."
        ),
        ip=ip,
        users=users,
        first_seen=min(f.first_seen for f in group),
        last_seen=max(f.last_seen for f in group),
        count=sum(f.count for f in group),
        evidence=evidence,
        correlated_rule_ids=rule_ids,
    )
