"""Unit tests for the SSH invalid-user enumeration detector (good + bad)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fixtures import make_rule_config, syslog_line

from security_log_analysis_tool.detection.ssh_enum import SshInvalidUserEnumRule
from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser

_REF = datetime(2025, 7, 3, 12, 0, 0, tzinfo=UTC)


def _invalid_user_event(ip: str, user: str, i: int) -> object:
    syslog = SyslogAuthParser(reference=_REF)
    when = _REF + timedelta(seconds=i * 5)
    message = f"Failed password for invalid user {user} from {ip} port {51000 + i} ssh2"
    return syslog.parse_line("f", i + 1, syslog_line(when=when, message=message))


def test_ssh_enum_flags_distinct_invalid_users_at_threshold() -> None:
    rule = SshInvalidUserEnumRule(
        make_rule_config(
            id="ssh-invalid-user-enum",
            type="ssh-invalid-user-enum",
            source=LogSource.AUTH,
            threshold=4,
        )
    )
    users = ["admin", "test", "oracle", "postgres"]
    events = [_invalid_user_event("203.0.113.5", user, i) for i, user in enumerate(users)]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].ip == "203.0.113.5"
    assert set(findings[0].users) == set(users)


def test_ssh_enum_does_not_flag_below_threshold() -> None:
    rule = SshInvalidUserEnumRule(
        make_rule_config(
            id="ssh-invalid-user-enum",
            type="ssh-invalid-user-enum",
            source=LogSource.AUTH,
            threshold=4,
        )
    )
    events = [
        _invalid_user_event("203.0.113.5", user, i) for i, user in enumerate(["admin", "test"])
    ]

    assert rule.evaluate(events) == []


def test_ssh_enum_ignores_valid_user_failures() -> None:
    rule = SshInvalidUserEnumRule(
        make_rule_config(
            id="ssh-invalid-user-enum",
            type="ssh-invalid-user-enum",
            source=LogSource.AUTH,
            threshold=2,
        )
    )
    syslog = SyslogAuthParser(reference=_REF)
    events = [
        syslog.parse_line(
            "f",
            i + 1,
            syslog_line(
                when=_REF + timedelta(seconds=i * 5),
                message=f"Failed password for root from 203.0.113.5 port {51000 + i} ssh2",
            ),
        )
        for i in range(4)
    ]

    assert rule.evaluate(events) == []
