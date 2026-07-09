"""Tests for the SMTP email alert sink against a real local aiosmtpd mock server.

No real credentials or network calls: aiosmtpd runs an in-process SMTP server
on localhost, so this proves message construction, delivery, and redaction
without touching a live mailbox.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Message as MessageHandler

from security_log_analysis_tool.alerts.email_sink import EmailSink, build_email_sink_from_env
from security_log_analysis_tool.models import Evidence, Finding, Severity


class _CapturingHandler(MessageHandler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list = []

    def handle_message(self, message) -> None:  # noqa: ANN001
        self.messages.append(message)


def _free_port() -> int:
    """Pick a free localhost port up front.

    ``Controller(port=0)`` asks the OS to auto-assign a port, but aiosmtpd's
    readiness check on Windows connects using the pre-bind port value (still
    0) instead of the resolved one, so auto-assignment fails here. Binding a
    throwaway socket first and reusing its port sidesteps that.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def smtp_server() -> Iterator[tuple[Controller, _CapturingHandler, int]]:
    handler = _CapturingHandler()
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield controller, handler, controller.port
    finally:
        controller.stop()


def _finding(*, severity: Severity = Severity.CRITICAL, password_leak: bool = False) -> Finding:
    description = "brute-force detected from 10.0.0.50"
    if password_leak:
        description += " password=Password123!"
    now = datetime(2025, 7, 3, 10, 15, 32, tzinfo=UTC)
    return Finding(
        finding_id="f-1",
        rule_id="web-brute-force",
        severity=severity,
        title="Brute-force login attempts",
        description=description,
        first_seen=now,
        last_seen=now,
        count=7,
        ip="10.0.0.50",
        users=("alice",),
        evidence=(Evidence(file="access.log", line_no=42, excerpt="..."),),
    )


def test_sends_digest_to_mock_smtp_server(smtp_server) -> None:
    controller, handler, port = smtp_server
    sink = EmailSink(
        host="127.0.0.1",
        port=port,
        username="",
        password="",
        sender="alerts@example.com",
        to="soc@example.com",
        use_starttls=False,
    )

    sink.send((_finding(),), job_id="job-123")

    assert len(handler.messages) == 1
    message = handler.messages[0]
    assert message["From"] == "alerts@example.com"
    assert message["To"] == "soc@example.com"
    assert "job-123" in message["Subject"]
    body = message.get_payload()
    assert "Brute-force login attempts" in body
    assert "10.0.0.50" in body


def test_email_body_redacts_leaked_secret(smtp_server) -> None:
    controller, handler, port = smtp_server
    sink = EmailSink(
        host="127.0.0.1",
        port=port,
        username="",
        password="",
        sender="alerts@example.com",
        to="soc@example.com",
        use_starttls=False,
    )

    sink.send((_finding(password_leak=True),), job_id="job-456")

    body = handler.messages[0].get_payload()
    assert "Password123!" not in body
    assert "[REDACTED]" in body


def test_empty_findings_sends_no_email(smtp_server) -> None:
    controller, handler, port = smtp_server
    sink = EmailSink(
        host="127.0.0.1",
        port=port,
        username="",
        password="",
        sender="alerts@example.com",
        to="soc@example.com",
        use_starttls=False,
    )

    sink.send((), job_id="job-empty")

    assert handler.messages == []


def test_send_to_unreachable_host_raises_and_does_not_hang() -> None:
    sink = EmailSink(
        host="127.0.0.1",
        port=1,  # nothing listens here
        username="",
        password="",
        sender="alerts@example.com",
        to="soc@example.com",
        use_starttls=False,
        timeout=1.0,
    )
    with pytest.raises(OSError):
        sink.send((_finding(),), job_id="job-789")


def test_build_email_sink_from_env_returns_none_when_unconfigured() -> None:
    assert build_email_sink_from_env({}) is None


def test_build_email_sink_from_env_builds_configured_sink() -> None:
    env = {
        "SLAT_SMTP_HOST": "smtp.example.com",
        "SLAT_SMTP_PORT": "2525",
        "SLAT_SMTP_USERNAME": "alerts@example.com",
        "SLAT_SMTP_PASSWORD": "app-password-placeholder",
        "SLAT_SMTP_TO": "soc@example.com",
        "SLAT_SMTP_STARTTLS": "false",
    }
    sink = build_email_sink_from_env(env)
    assert sink is not None
    assert sink.name == "email"
