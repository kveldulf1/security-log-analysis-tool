"""SMTP email alert sink: one digest per job, STARTTLS by default, redacted content.

Credentials come only from ``.env`` (never a CLI flag or config file) via
:func:`build_email_sink_from_env`, matching the locked SMTP decision and the
project's secrets-hygiene rule.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from ..models import Finding
from ..redaction import redact

_TRUTHY_ENV = {"1", "true", "yes", "on"}


class EmailSink:
    name = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        to: str,
        use_starttls: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._to = to
        self._use_starttls = use_starttls
        self._timeout = timeout

    def send(self, findings: tuple[Finding, ...], *, job_id: str) -> None:
        if not findings:
            return
        message = self._build_message(findings, job_id=job_id)
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            if self._use_starttls:
                smtp.starttls()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(message)

    def _build_message(self, findings: tuple[Finding, ...], *, job_id: str) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = redact(
            f"[security-log-analysis-tool] {len(findings)} finding(s) - job {job_id}"
        )
        message["From"] = self._sender
        message["To"] = self._to

        lines = [f"Job {job_id}: {len(findings)} finding(s) at or above the alert threshold.", ""]
        for finding in findings:
            lines.append(
                redact(
                    f"- [{finding.severity.name}] {finding.title} "
                    f"(rule={finding.rule_id}, ip={finding.ip}, count={finding.count})"
                )
            )
            if finding.description:
                lines.append(redact(finding.description))
        message.set_content(redact("\n".join(lines)))
        return message


def build_email_sink_from_env(env: dict[str, str]) -> EmailSink | None:
    """Build an :class:`EmailSink` from ``.env``-style values, or ``None`` if unconfigured."""

    host = env.get("SLAT_SMTP_HOST", "").strip()
    to = env.get("SLAT_SMTP_TO", "").strip()
    if not host or not to:
        return None

    username = env.get("SLAT_SMTP_USERNAME", "")
    return EmailSink(
        host=host,
        port=int(env.get("SLAT_SMTP_PORT", "587")),
        username=username,
        password=env.get("SLAT_SMTP_PASSWORD", ""),
        sender=env.get("SLAT_SMTP_FROM") or username or "alerts@localhost",
        to=to,
        use_starttls=env.get("SLAT_SMTP_STARTTLS", "true").strip().lower() in _TRUTHY_ENV,
    )
