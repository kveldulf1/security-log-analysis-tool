"""behave environment hooks.

Sets up the shared context used by step implementations. Steps reuse the same
fixture builders and engine seams as the pytest unit tests, so the Gherkin
scenarios stay a living document over the real code rather than a parallel mock.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _ROOT / "tests"

# Make the shared `fixtures` package importable inside step modules.
for path in (str(_TESTS_DIR), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


def before_all(context) -> None:
    context.root = _ROOT
    context.sample_logs = _ROOT / "sample_logs"
    context.rules_path = _ROOT / "config" / "rules.yaml"


def before_scenario(context, scenario) -> None:
    # Per-scenario scratch space; cleared between scenarios.
    context.result = None
    context.parsed = None
