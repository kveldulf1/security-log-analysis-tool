"""Tests for ``build_dispatcher``: the config→sinks wiring shared by CLI and TUI."""

from __future__ import annotations

import logging

from security_log_analysis_tool.alerts import (
    AlertDispatcher,
    EmailSink,
    ToastSink,
    build_dispatcher,
)
from security_log_analysis_tool.config import AlertConfig
from security_log_analysis_tool.models import Severity

_SMTP_ENV = {
    "SLAT_SMTP_HOST": "smtp.example.test",
    "SLAT_SMTP_TO": "soc@example.test",
    "SLAT_SMTP_USERNAME": "mailer",
    "SLAT_SMTP_PASSWORD": "not-a-real-password",
}


def _sinks(dispatcher: AlertDispatcher):
    return dispatcher._sinks  # noqa: SLF001 — asserting wiring, no public accessor


def test_builds_toast_and_email_when_fully_configured() -> None:
    config = AlertConfig(min_severity=Severity.HIGH, sinks=("toast", "email"))

    dispatcher = build_dispatcher(config, env=_SMTP_ENV)

    kinds = [type(sink) for sink in _sinks(dispatcher)]
    assert kinds == [ToastSink, EmailSink]


def test_email_sink_skipped_when_smtp_env_missing(caplog) -> None:
    config = AlertConfig(min_severity=Severity.HIGH, sinks=("email",))

    with caplog.at_level(logging.INFO):
        dispatcher = build_dispatcher(config, env={})

    assert _sinks(dispatcher) == ()
    assert any("SMTP environment is missing" in record.message for record in caplog.records)


def test_unknown_sink_name_skipped_with_warning(caplog) -> None:
    config = AlertConfig(min_severity=Severity.HIGH, sinks=("pager", "toast"))

    with caplog.at_level(logging.WARNING):
        dispatcher = build_dispatcher(config, env={})

    assert [type(sink) for sink in _sinks(dispatcher)] == [ToastSink]
    assert any("unknown alert sink" in record.message for record in caplog.records)


def test_empty_sinks_builds_dispatcher_with_no_sinks() -> None:
    config = AlertConfig(min_severity=Severity.HIGH, sinks=())

    dispatcher = build_dispatcher(config, env={})

    assert _sinks(dispatcher) == ()


def test_malformed_smtp_port_skips_email_sink_instead_of_raising(caplog) -> None:
    config = AlertConfig(min_severity=Severity.HIGH, sinks=("email", "toast"))
    env = {**_SMTP_ENV, "SLAT_SMTP_PORT": "default"}  # not an integer

    with caplog.at_level(logging.WARNING):
        dispatcher = build_dispatcher(config, env=env)

    # Best-effort contract: the bad email config is skipped with a warning and
    # the remaining sinks still build — never an exception to the caller.
    assert [type(sink) for sink in _sinks(dispatcher)] == [ToastSink]
    assert any("email sink misconfigured" in record.message for record in caplog.records)


def test_default_env_layers_dotenv_under_process_env(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "alerts.env"
    env_file.write_text(
        "SLAT_SMTP_HOST=file.example.test\nSLAT_SMTP_TO=file@example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SLAT_ENV_FILE", str(env_file))
    monkeypatch.setenv("SLAT_SMTP_HOST", "env.example.test")  # process env wins
    config = AlertConfig(min_severity=Severity.HIGH, sinks=("email",))

    dispatcher = build_dispatcher(config)  # no env → default layering path

    sinks = _sinks(dispatcher)
    assert [type(sink) for sink in sinks] == [EmailSink]
    assert sinks[0]._host == "env.example.test"  # noqa: SLF001
    assert sinks[0]._to == "file@example.test"  # noqa: SLF001
