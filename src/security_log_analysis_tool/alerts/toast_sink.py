"""Windows toast alert sink: shells out to ``toast.ps1``, injectable runner.

Off-Windows this sink no-ops — there is no WinRT toast API to call — and on
Windows it invokes ``powershell.exe`` running the ported script. The
subprocess runner is injectable so tests never spawn a real process.
"""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..models import Finding
from ..redaction import redact

_SCRIPT_PATH = Path(__file__).parent / "toast.ps1"

Runner = Callable[[list[str]], object]


def _default_runner(command: list[str]) -> object:
    return subprocess.run(command, capture_output=True, timeout=10, check=False)


class ToastSink:
    name = "toast"

    def __init__(
        self,
        *,
        runner: Runner = _default_runner,
        is_windows: bool | None = None,
        script_path: Path = _SCRIPT_PATH,
    ) -> None:
        self._runner = runner
        self._is_windows = platform.system() == "Windows" if is_windows is None else is_windows
        self._script_path = script_path

    def send(self, findings: tuple[Finding, ...], *, job_id: str) -> None:
        if not self._is_windows or not findings:
            return

        title = redact(f"{len(findings)} finding(s) - job {job_id}")
        top = findings[0]
        body = redact(f"[{top.severity.name}] {top.title}")
        if len(findings) > 1:
            body += " (+more)"

        self._runner(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self._script_path),
                "-Title",
                title,
                "-Body",
                body,
            ]
        )
