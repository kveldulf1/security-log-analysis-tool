"""Core domain models shared across parsers, detectors, correlation, and output.

All models are frozen dataclasses so that events and findings are immutable once
produced — a parsed line cannot be mutated by a downstream detector, and a finding
is a stable value that can be safely shared across threads in the job queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any


class LogSource(StrEnum):
    """Which log family an event came from."""

    WEB = "web"  # Apache/nginx access log
    AUTH = "auth"  # syslog auth.log


class Severity(IntEnum):
    """Finding severity. IntEnum so thresholds compare naturally (>= HIGH)."""

    LOW = 10
    MEDIUM = 20
    HIGH = 30
    CRITICAL = 40

    @classmethod
    def from_name(cls, name: str) -> Severity:
        try:
            return cls[name.strip().upper()]
        except KeyError as exc:
            valid = ", ".join(s.name.lower() for s in cls)
            raise ValueError(f"unknown severity {name!r}; valid: {valid}") from exc


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"


class Permission(StrEnum):
    """Discrete capabilities enforced at the service layer (see auth/authz.py)."""

    RUN_ANALYSIS = "run_analysis"
    STOP_OWN_JOB = "stop_own_job"
    STOP_ANY_JOB = "stop_any_job"
    VIEW_FINDINGS = "view_findings"
    VIEW_OWN_TOOL_LOGS = "view_own_tool_logs"
    VIEW_ALL_TOOL_LOGS = "view_all_tool_logs"
    EXPORT_FINDINGS = "export_findings"
    MANAGE_USERS = "manage_users"
    MANAGE_RULES = "manage_rules"


@dataclass(frozen=True, slots=True)
class LogEvent:
    """A single normalized log line.

    Parsers map a raw line to exactly one of ``LogEvent`` or ``ParseFailure`` with
    no I/O. ``timestamp`` is always timezone-aware and normalized to UTC.
    """

    source: LogSource
    file: str
    line_no: int
    timestamp: datetime
    raw: str
    ip: str | None = None
    user: str | None = None
    method: str | None = None
    path: str | None = None
    status: int | None = None
    size: int | None = None
    message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParseFailure:
    """A line that could not be parsed. Counted and WARN-logged, never raised."""

    file: str
    line_no: int
    reason: str


@dataclass(frozen=True, slots=True)
class Evidence:
    """A redacted pointer back to a source line supporting a finding."""

    file: str
    line_no: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class Finding:
    """A detection result. ``description`` and evidence excerpts are pre-redacted."""

    finding_id: str
    rule_id: str
    severity: Severity
    title: str
    description: str
    first_seen: datetime
    last_seen: datetime
    count: int
    ip: str | None = None
    users: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    correlated_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class User:
    username: str
    password_hash: str
    role: Role
    failed_attempts: int = 0
    locked_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    status: JobStatus
    files: tuple[str, ...]
    submitted_by: str
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    findings: tuple[Finding, ...] = ()
    error: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
