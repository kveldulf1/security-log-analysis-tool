"""Tests for the toast alert sink: injected runner, off-Windows no-op, redaction."""

from __future__ import annotations

from datetime import UTC, datetime

from security_log_analysis_tool.alerts.toast_sink import ToastSink
from security_log_analysis_tool.models import Finding, Severity


def _finding(title: str = "Brute-force login attempts") -> Finding:
    now = datetime(2025, 7, 3, 10, 15, 32, tzinfo=UTC)
    return Finding(
        finding_id="f-1",
        rule_id="web-brute-force",
        severity=Severity.CRITICAL,
        title=title,
        description="password=Password123!",
        first_seen=now,
        last_seen=now,
        count=7,
        ip="10.0.0.50",
    )


def test_off_windows_is_a_no_op() -> None:
    calls: list[list[str]] = []
    sink = ToastSink(runner=calls.append, is_windows=False)
    sink.send((_finding(),), job_id="job-123")
    assert calls == []


def test_empty_findings_is_a_no_op_even_on_windows() -> None:
    calls: list[list[str]] = []
    sink = ToastSink(runner=calls.append, is_windows=True)
    sink.send((), job_id="job-123")
    assert calls == []


def test_on_windows_invokes_injected_runner() -> None:
    calls: list[list[str]] = []
    sink = ToastSink(runner=calls.append, is_windows=True)
    sink.send((_finding(),), job_id="job-123")

    assert len(calls) == 1
    command = calls[0]
    assert command[0] == "powershell.exe"
    assert "-File" in command
    assert "-Title" in command
    assert "-Body" in command


def test_toast_body_redacts_leaked_secret() -> None:
    calls: list[list[str]] = []
    sink = ToastSink(runner=calls.append, is_windows=True)
    sink.send((_finding(),), job_id="job-123")

    body_index = calls[0].index("-Body") + 1
    body = calls[0][body_index]
    assert "Password123!" not in body


def test_toast_mentions_finding_count_and_job_id() -> None:
    calls: list[list[str]] = []
    sink = ToastSink(runner=calls.append, is_windows=True)
    sink.send((_finding(), _finding(title="Second finding")), job_id="job-xyz")

    title_index = calls[0].index("-Title") + 1
    title = calls[0][title_index]
    assert "2 finding" in title
    assert "job-xyz" in title


def test_runner_exception_propagates_to_caller_not_swallowed_here() -> None:
    """ToastSink itself does not swallow exceptions -- the dispatcher does that."""

    def failing_runner(_command: list[str]) -> None:
        raise RuntimeError("powershell not found")

    sink = ToastSink(runner=failing_runner, is_windows=True)
    try:
        sink.send((_finding(),), job_id="job-123")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate from the injected runner")


def test_script_path_defaults_to_the_shipped_toast_ps1() -> None:
    calls: list[list[str]] = []
    sink = ToastSink(runner=calls.append, is_windows=True)
    sink.send((_finding(),), job_id="job-123")
    file_index = calls[0].index("-File") + 1
    assert calls[0][file_index].endswith("toast.ps1")
