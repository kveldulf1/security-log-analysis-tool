"""Shared test fixtures: log-line builders and adversarial samples.

These builders are the single source of well-formed log lines for unit tests,
behave step implementations, and (later) detector good/bad slices — so a format
tweak updates one place. Kept deliberately dependency-free.
"""

from .log_lines import (
    ADVERSARIAL_LINES,
    apache_line,
    syslog_line,
)

__all__ = ["ADVERSARIAL_LINES", "apache_line", "syslog_line"]
