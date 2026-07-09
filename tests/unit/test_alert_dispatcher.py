"""Tests for AlertDispatcher: severity gating, and a failing sink never raises."""

from __future__ import annotations

from datetime import UTC, datetime

from security_log_analysis_tool.alerts import AlertDispatcher, SinkOutcome
from security_log_analysis_tool.models import Finding, Severity


def _finding(severity: Severity) -> Finding:
    now = datetime(2025, 7, 3, 10, 15, 32, tzinfo=UTC)
    return Finding(
        finding_id="f-1",
        rule_id="rule-x",
        severity=severity,
        title="title",
        description="description",
        first_seen=now,
        last_seen=now,
        count=1,
    )


class _RecordingSink:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Finding, ...], str]] = []

    def send(self, findings: tuple[Finding, ...], *, job_id: str) -> None:
        self.calls.append((findings, job_id))


class _FailingSink:
    name = "failing"

    def send(self, findings: tuple[Finding, ...], *, job_id: str) -> None:
        raise RuntimeError("sink exploded")


def test_dispatch_below_threshold_is_skipped() -> None:
    sink = _RecordingSink()
    dispatcher = AlertDispatcher((sink,), min_severity=Severity.HIGH)

    outcomes = dispatcher.dispatch((_finding(Severity.LOW), _finding(Severity.MEDIUM)), job_id="j1")

    assert outcomes == ()
    assert sink.calls == []


def test_dispatch_at_or_above_threshold_reaches_sink() -> None:
    sink = _RecordingSink()
    dispatcher = AlertDispatcher((sink,), min_severity=Severity.HIGH)

    findings = (_finding(Severity.LOW), _finding(Severity.CRITICAL))
    outcomes = dispatcher.dispatch(findings, job_id="j2")

    assert len(sink.calls) == 1
    delivered, job_id = sink.calls[0]
    assert job_id == "j2"
    assert delivered == (findings[1],)  # only the eligible one
    assert outcomes == (SinkOutcome(sink="recording", ok=True),)


def test_failing_sink_never_raises_into_the_caller() -> None:
    good = _RecordingSink()
    bad = _FailingSink()
    dispatcher = AlertDispatcher((bad, good), min_severity=Severity.HIGH)

    outcomes = dispatcher.dispatch((_finding(Severity.CRITICAL),), job_id="j3")

    assert len(good.calls) == 1  # a failing sink does not block the next one
    assert outcomes[0] == SinkOutcome(sink="failing", ok=False, error="sink exploded")
    assert outcomes[1].sink == "recording"
    assert outcomes[1].ok is True


def test_dispatch_with_no_sinks_configured_is_a_safe_no_op() -> None:
    dispatcher = AlertDispatcher((), min_severity=Severity.LOW)
    outcomes = dispatcher.dispatch((_finding(Severity.CRITICAL),), job_id="j4")
    assert outcomes == ()
