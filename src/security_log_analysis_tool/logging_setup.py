"""Application logging: Rich console + rotating text/JSON files, always redacted.

``configure_logging`` installs three handlers on the root logger — a Rich console
handler, a rotating ``app.log`` (human text), and a rotating ``app.jsonl`` (one JSON
object per line) — each carrying a :class:`RedactionFilter`. Because the filter sits
on every handler, no credential or PII can reach any sink, and the formatters redact
exception text too. Built on stdlib ``logging`` so ``caplog`` and friends keep working.
"""

from __future__ import annotations

import json
import logging
import logging.config
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .redaction import redact

_TEXT_FILENAME = "app.log"
_JSON_FILENAME = "app.jsonl"


class RedactionFilter(logging.Filter):
    """Rewrite each record so its rendered message is redacted at every handler.

    We collapse ``msg``/``args`` into a single redacted string once, which keeps the
    scrubbing idempotent across multiple handlers sharing the same record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class _RedactingTextFormatter(logging.Formatter):
    converter = staticmethod(time.gmtime)  # UTC timestamps

    def formatException(self, ei) -> str:  # type: ignore[no-untyped-def]
        return redact(super().formatException(ei))


class JsonLogFormatter(logging.Formatter):
    """One JSON object per record: UTC timestamp, level, logger, message, exc."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class LoggingPaths:
    text: Path
    json: Path


def configure_logging(
    *,
    log_dir: str | Path = ".",
    level: str = "INFO",
    console: bool = True,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> LoggingPaths:
    """Install the root logging configuration and return the file paths written."""

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    text_path = directory / _TEXT_FILENAME
    json_path = directory / _JSON_FILENAME

    handlers: dict[str, dict] = {
        "file_text": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(text_path),
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
            "level": level,
            "formatter": "text",
            "filters": ["redaction"],
        },
        "file_json": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(json_path),
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
            "level": level,
            "formatter": "json",
            "filters": ["redaction"],
        },
    }
    if console:
        handlers["console"] = {
            "class": "rich.logging.RichHandler",
            "level": level,
            "filters": ["redaction"],
            "markup": False,
            "rich_tracebacks": False,
            "show_path": False,
        }

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "redaction": {"()": f"{__name__}.RedactionFilter"},
        },
        "formatters": {
            "text": {
                "()": f"{__name__}._RedactingTextFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
            "json": {"()": f"{__name__}.JsonLogFormatter"},
        },
        "handlers": handlers,
        "root": {"level": level, "handlers": list(handlers)},
    }
    logging.config.dictConfig(config)
    return LoggingPaths(text=text_path, json=json_path)


def reset_logging() -> None:
    """Detach and close all root handlers (test isolation / clean shutdown)."""

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
