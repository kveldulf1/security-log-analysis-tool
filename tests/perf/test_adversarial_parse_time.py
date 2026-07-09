"""Performance: adversarial input parses in bounded time (ReDoS guard).

Turns the "anchored regexes, no nested quantifiers, oversized lines pre-truncated"
mitigation into an asserted number rather than a claim: a 1 MB line, and
pathological near-miss inputs aimed at the traversal/SQLi patterns, must each be
handled in well under a per-item time bound — no catastrophic backtracking, no
whole-line materialisation blow-up.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fixtures import ADVERSARIAL_LINES  # type: ignore[import-not-found]

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.detection import build_rule
from security_log_analysis_tool.models import LogEvent, LogSource
from security_log_analysis_tool.parsers import get_parser
from security_log_analysis_tool.redaction import redact

pytestmark = pytest.mark.perf

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _ROOT / "config" / "rules.yaml"

_PER_LINE_BUDGET_SECONDS = 0.25
# A "not hanging" ceiling for redacting an oversized blob — the fix makes redaction
# strictly linear, so a 1 MB input lands well under this generous CI-safe bound.
_REDACT_BUDGET_SECONDS = 1.0
_PATHOLOGICAL_LEN = 200_000


def _timed(func) -> float:
    start = time.monotonic()
    func()
    return time.monotonic() - start


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@pytest.mark.timeout(30)
def test_adversarial_lines_parse_within_budget():
    apache = get_parser("apache")
    syslog = get_parser("syslog")
    for i, line in enumerate(ADVERSARIAL_LINES):
        parser = syslog if line.lstrip().startswith(_MONTHS) else apache
        elapsed = _timed(lambda p=parser, ln=line, n=i: p.parse_line("adv.log", n + 1, ln))
        assert elapsed < _PER_LINE_BUDGET_SECONDS, f"line {i} parsed in {elapsed:.3f}s"


@pytest.mark.timeout(30)
def test_one_megabyte_line_redacts_within_budget():
    # A long run of scheme-valid characters with no "://" was O(n^2) in the URL
    # userinfo rule (a ReDoS); the length-bounded scheme makes redaction linear.
    big = "x=1&token=abc " + "A" * (1024 * 1024)
    elapsed = _timed(lambda: redact(big))
    assert elapsed < _REDACT_BUDGET_SECONDS, f"redaction of 1 MB line took {elapsed:.3f}s"


def _event_with_path(path: str) -> LogEvent:
    return LogEvent(
        source=LogSource.WEB,
        file="adv.log",
        line_no=1,
        timestamp=datetime(2025, 7, 3, 10, 0, 0, tzinfo=UTC),
        raw="raw",
        ip="203.0.113.9",
        method="GET",
        path=path,
        status=404,
    )


# (rule_id, unit-string): the pathological path is built inside the test from the
# short unit so the 200k-char blob never leaks into the pytest node id (which Windows
# would reject as an over-long env var).
_PATHOLOGICAL_CASES = {
    "traversal-dotdot": ("path-traversal", "/", "../"),
    "traversal-pct2e": ("path-traversal", "/", "%2e"),
    "sqli-or": ("sqli-probe", "/?q=", "or "),
    "sqli-quotes": ("sqli-probe", "/?q=", "'"),
}


@pytest.mark.timeout(30)
@pytest.mark.parametrize("case", list(_PATHOLOGICAL_CASES))
def test_web_attack_regexes_bounded_on_pathological_input(case: str):
    rule_id, prefix, unit = _PATHOLOGICAL_CASES[case]
    path = prefix + unit * (_PATHOLOGICAL_LEN // len(unit))
    config = next(r for r in load_rules(_RULES_PATH).rules if r.id == rule_id)
    rule = build_rule(config)
    event = _event_with_path(path)
    elapsed = _timed(lambda: rule.evaluate([event]))
    assert elapsed < _PER_LINE_BUDGET_SECONDS, (
        f"{rule_id} took {elapsed:.3f}s on pathological input — possible ReDoS"
    )
