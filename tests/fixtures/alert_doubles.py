"""Test doubles for the alert dispatcher."""

from __future__ import annotations


class RecordingDispatcher:
    """Stands in for the real AlertDispatcher: no sinks fire, calls are recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def dispatch(self, findings, *, job_id: str):
        self.calls.append((job_id, len(findings)))
        return ()
