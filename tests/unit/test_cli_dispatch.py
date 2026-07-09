"""Tests for the auto-discovering CLI dispatcher.

Proves the key session-1 guarantee: dropping a module into the ``commands``
package makes a new subcommand appear WITHOUT editing ``cli.py``, and that
configuration/usage errors raised by a command surface as exit code 2 (no
traceback).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from security_log_analysis_tool import cli, commands

_COMMANDS_DIR = Path(commands.__file__).parent

_PROBE_SOURCE = '''\
"""Throwaway probe command used only by tests."""

from security_log_analysis_tool.config import ConfigError


def register(subparsers):
    p = subparsers.add_parser("probe-xyz", help="probe help text")
    p.add_argument("--boom", action="store_true")
    p.add_argument("--none", action="store_true")
    p.set_defaults(func=run)


def run(args):
    if args.boom:
        raise ConfigError("simulated bad configuration")
    print("probe ran")
    return None if args.none else 0
'''


@pytest.fixture
def probe_module() -> Iterator[None]:
    """Write a probe command module into the package, yield, then remove it."""

    # discover_commands() skips names starting with "_", so use a discoverable name.
    module_path = _COMMANDS_DIR / "zz_probe_xyz.py"
    module_path.write_text(_PROBE_SOURCE, encoding="utf-8")
    importlib.invalidate_caches()
    try:
        yield
    finally:
        module_path.unlink(missing_ok=True)
        for cached in _COMMANDS_DIR.glob("__pycache__/zz_probe_xyz*.pyc"):
            cached.unlink(missing_ok=True)
        importlib.invalidate_caches()


def test_smoke_no_subcommand_is_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "ready" in capsys.readouterr().out


def test_dropped_command_appears_in_help(
    probe_module: None, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = cli.build_parser()
    help_text = parser.format_help()
    assert "probe-xyz" in help_text


def test_dropped_command_runs(probe_module: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["probe-xyz"]) == 0
    assert "probe ran" in capsys.readouterr().out


def test_command_returning_none_exits_zero(
    probe_module: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["probe-xyz", "--none"]) == 0


def test_config_error_becomes_exit_2_no_traceback(
    probe_module: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["probe-xyz", "--boom"])
    captured = capsys.readouterr()
    assert code == 2
    assert "simulated bad configuration" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "security-log-analysis-tool" in capsys.readouterr().out
