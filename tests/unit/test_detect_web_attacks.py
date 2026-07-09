"""Unit tests for path-traversal and SQLi-probe detectors (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import apache_line, make_rule_config

from security_log_analysis_tool.detection.web_attacks import PathTraversalRule, SqliProbeRule
from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers import get_parser

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)

_TRAVERSAL_PATTERNS = [r"\.\./", r"\.\.\\", "%2e%2e", "%252e"]
_SQLI_PATTERNS = [
    r"(?i)\bunion\s+select\b",
    r"(?i)\bdrop\s+table\b",
    r"(?i)\bor\s+1\s*=\s*1\b",
    r"(?i);\s*--",
    r"(?i)'\s+or\s+'1'\s*=\s*'1",
]


def _event(ip: str, path: str, i: int = 0) -> object:
    apache = get_parser("apache")
    when = _REF + timedelta(seconds=i * 5)
    return apache.parse_line("f", i + 1, apache_line(ip=ip, path=path, status=404, when=when))


def test_path_traversal_flags_raw_dotdot() -> None:
    rule = PathTraversalRule(
        make_rule_config(
            id="path-traversal",
            type="path-traversal",
            source=LogSource.WEB,
            patterns=_TRAVERSAL_PATTERNS,
        )
    )
    events = [_event("203.0.113.5", "/download?file=../../etc/passwd")]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "203.0.113.5"


def test_path_traversal_flags_double_encoded() -> None:
    rule = PathTraversalRule(
        make_rule_config(
            id="path-traversal",
            type="path-traversal",
            source=LogSource.WEB,
            patterns=_TRAVERSAL_PATTERNS,
        )
    )
    events = [_event("203.0.113.5", "/static/%252e%252e%252fetc/passwd")]

    assert len(rule.evaluate(events)) == 1


def test_path_traversal_ignores_benign_path() -> None:
    rule = PathTraversalRule(
        make_rule_config(
            id="path-traversal",
            type="path-traversal",
            source=LogSource.WEB,
            patterns=_TRAVERSAL_PATTERNS,
        )
    )
    events = [_event("192.0.2.1", "/products/42")]

    assert rule.evaluate(events) == []


def test_sqli_probe_flags_union_select() -> None:
    rule = SqliProbeRule(
        make_rule_config(
            id="sqli-probe", type="sqli-probe", source=LogSource.WEB, patterns=_SQLI_PATTERNS
        )
    )
    events = [
        _event("198.51.100.23", "/search?q=union%20select%20username,password%20from%20users")
    ]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "198.51.100.23"


def test_sqli_probe_flags_or_1_equals_1() -> None:
    rule = SqliProbeRule(
        make_rule_config(
            id="sqli-probe", type="sqli-probe", source=LogSource.WEB, patterns=_SQLI_PATTERNS
        )
    )
    # Real access logs percent-encode spaces/quotes — an unencoded path would
    # break the Apache request-line split, so probes are always URL-encoded here.
    events = [_event("198.51.100.23", "/item?id=1%27%20OR%20%271%27=%271")]

    assert len(rule.evaluate(events)) == 1


def test_sqli_probe_does_not_flag_obrien_lookalike() -> None:
    """O'Brien is a legitimate search term, not a SQLi payload — must not be flagged."""

    rule = SqliProbeRule(
        make_rule_config(
            id="sqli-probe", type="sqli-probe", source=LogSource.WEB, patterns=_SQLI_PATTERNS
        )
    )
    events = [_event("192.0.2.55", "/search?q=O%27Brien")]

    assert rule.evaluate(events) == []


def test_web_attacks_aggregate_multiple_hits_per_ip() -> None:
    rule = SqliProbeRule(
        make_rule_config(
            id="sqli-probe", type="sqli-probe", source=LogSource.WEB, patterns=_SQLI_PATTERNS
        )
    )
    events = [
        _event("198.51.100.23", "/search?q=union%20select%20x", 0),
        _event("198.51.100.23", "/item?id=1%27%20OR%20%271%27=%271", 1),
    ]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].count == 2
