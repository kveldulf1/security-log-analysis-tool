"""Tests for logging setup: caplog compat, rotation, and file redaction."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from security_log_analysis_tool.logging_setup import (
    JsonLogFormatter,
    RedactionFilter,
    configure_logging,
    reset_logging,
)


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    reset_logging()


def test_configure_writes_both_files(tmp_path: Path) -> None:
    paths = configure_logging(log_dir=tmp_path, console=False, level="INFO")
    logging.getLogger("slat.test").info("hello world")
    reset_logging()  # flush + close
    assert paths.text.exists()
    assert paths.json.exists()
    assert "hello world" in paths.text.read_text(encoding="utf-8")
    line = paths.json.read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["message"] == "hello world"
    assert record["level"] == "INFO"
    assert record["timestamp"].endswith("+00:00")  # UTC


def test_caplog_still_works(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        logging.getLogger("slat.test").warning("a warning")
    assert "a warning" in caplog.text


def test_secret_redacted_in_both_files(tmp_path: Path) -> None:
    paths = configure_logging(log_dir=tmp_path, console=False, level="INFO")
    log = logging.getLogger("slat.auth")
    # Secret passed via %-arg (the realistic accidental-logging path).
    log.warning("failed login password=%s", "Password123!")
    log.info("token=%s emitted", "super-secret-token-value")
    reset_logging()

    text_bytes = paths.text.read_bytes()
    json_bytes = paths.json.read_bytes()
    for blob in (text_bytes, json_bytes):
        assert b"Password123!" not in blob
        assert b"super-secret-token-value" not in blob
        assert b"[REDACTED]" in blob


def test_exception_text_redacted(tmp_path: Path) -> None:
    paths = configure_logging(log_dir=tmp_path, console=False, level="ERROR")
    log = logging.getLogger("slat.err")
    try:
        raise ValueError("boom password=Password123!")
    except ValueError:
        log.exception("handling failure")
    reset_logging()
    assert b"Password123!" not in paths.text.read_bytes()
    assert b"Password123!" not in paths.json.read_bytes()


def test_rotation_creates_backups(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path, console=False, level="INFO", max_bytes=1024, backup_count=2)
    log = logging.getLogger("slat.rot")
    for i in range(500):
        log.info("filler line number %d with some padding text to grow the file", i)
    reset_logging()
    assert (tmp_path / "app.log").exists()
    assert (tmp_path / "app.log.1").exists()  # rolled over at least once


def test_redaction_filter_unit() -> None:
    f = RedactionFilter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="password=%s",
        args=("hunter2hunter2",),
        exc_info=None,
    )
    assert f.filter(record) is True
    assert "hunter2hunter2" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_json_formatter_is_valid_json() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="x",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="hi %s",
        args=("there",),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["message"] == "hi there"
    assert parsed["level"] == "ERROR"
