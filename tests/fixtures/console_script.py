"""Locate the installed ``security-log-analysis-tool`` console script for e2e tests."""

from __future__ import annotations

import contextlib
import os
import shutil
import sysconfig
from pathlib import Path

import pytest


def find_console_script() -> str:
    """Return the installed console script's path, or fail the calling test."""

    found = shutil.which("security-log-analysis-tool")
    if found:
        return found
    script_dirs = [Path(sysconfig.get_path("scripts"))]
    with contextlib.suppress(KeyError):
        script_dirs.append(Path(sysconfig.get_path("scripts", f"{os.name}_user")))
    for directory in script_dirs:
        for name in ("security-log-analysis-tool", "security-log-analysis-tool.exe"):
            candidate = directory / name
            if candidate.exists():
                return str(candidate)
    pytest.fail(
        "installed console script 'security-log-analysis-tool' not found on PATH or in "
        f"{[str(d) for d in script_dirs]}; run `pip install -e .[dev]` first"
    )
