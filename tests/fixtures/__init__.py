"""Shared test fixtures: log-line builders and adversarial samples.

These builders are the single source of well-formed log lines for unit tests,
behave step implementations, and (later) detector good/bad slices — so a format
tweak updates one place. Kept deliberately dependency-free.
"""

from .alert_doubles import RecordingDispatcher
from .log_lines import (
    ADVERSARIAL_LINES,
    apache_line,
    syslog_line,
)
from .rule_config import make_rule_config

# fixtures.console_script (find_console_script) is deliberately NOT re-exported
# here: it imports pytest, and this package is also imported by behave steps.

__all__ = [
    "ADVERSARIAL_LINES",
    "RecordingDispatcher",
    "apache_line",
    "make_rule_config",
    "syslog_line",
]
