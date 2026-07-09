"""Unit tests for the sudo sensitive-command detector (good + bad)."""

from __future__ import annotations

from fixtures import make_rule_config, syslog_line

from security_log_analysis_tool.detection.sudo_rules import SudoSensitiveCommandRule
from security_log_analysis_tool.models import LogSource
from security_log_analysis_tool.parsers.syslog_auth import SyslogAuthParser

_SENSITIVE_PATTERNS = [r"/etc/shadow", r"/etc/sudoers", r"/etc/passwd", r"\.ssh/", "id_rsa"]


def _sudo_event(message: str, i: int = 1) -> object:
    syslog = SyslogAuthParser()
    return syslog.parse_line("f", i, syslog_line(program="sudo", message=message))


def test_sudo_flags_sensitive_command() -> None:
    rule = SudoSensitiveCommandRule(
        make_rule_config(
            id="sudo-sensitive-command",
            type="sudo-sensitive-command",
            source=LogSource.AUTH,
            sensitive_patterns=_SENSITIVE_PATTERNS,
        )
    )
    event = _sudo_event(
        "alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/usr/bin/cat /etc/shadow"
    )

    findings = rule.evaluate([event])

    assert len(findings) == 1
    assert findings[0].users == ("alice",)


def test_sudo_does_not_flag_benign_command() -> None:
    """systemctl restart nginx is an ordinary sudo command, not sensitive."""

    rule = SudoSensitiveCommandRule(
        make_rule_config(
            id="sudo-sensitive-command",
            type="sudo-sensitive-command",
            source=LogSource.AUTH,
            sensitive_patterns=_SENSITIVE_PATTERNS,
        )
    )
    event = _sudo_event(
        "bob : TTY=pts/1 ; PWD=/home/bob ; USER=root ; COMMAND=/usr/bin/systemctl restart nginx"
    )

    assert rule.evaluate([event]) == []


def test_sudo_ignores_non_sudo_program() -> None:
    rule = SudoSensitiveCommandRule(
        make_rule_config(
            id="sudo-sensitive-command",
            type="sudo-sensitive-command",
            source=LogSource.AUTH,
            sensitive_patterns=_SENSITIVE_PATTERNS,
        )
    )
    syslog = SyslogAuthParser()
    event = syslog.parse_line(
        "f",
        1,
        syslog_line(
            program="sshd", message="Accepted password for alice from 10.0.0.1 port 40000 ssh2"
        ),
    )

    assert rule.evaluate([event]) == []


def test_sudo_aggregates_multiple_commands_by_same_user() -> None:
    rule = SudoSensitiveCommandRule(
        make_rule_config(
            id="sudo-sensitive-command",
            type="sudo-sensitive-command",
            source=LogSource.AUTH,
            sensitive_patterns=_SENSITIVE_PATTERNS,
        )
    )
    events = [
        _sudo_event(
            "alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/usr/bin/cat /etc/shadow", 1
        ),
        _sudo_event(
            "alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/usr/bin/cat /etc/passwd", 2
        ),
    ]

    findings = rule.evaluate(events)

    assert len(findings) == 1
    assert findings[0].count == 2
