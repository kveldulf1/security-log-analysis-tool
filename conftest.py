"""Pytest bootstrap: make the shared ``fixtures`` package importable.

Adds the ``tests`` directory to ``sys.path`` so unit tests, behave steps, and
later detector suites can ``from fixtures import apache_line, syslog_line``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).parent / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
