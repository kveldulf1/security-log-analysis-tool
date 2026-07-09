"""Builder for ``RuleConfig`` used by detector unit tests (bypasses YAML)."""

from __future__ import annotations

from typing import Any

from security_log_analysis_tool.config import RuleConfig
from security_log_analysis_tool.models import LogSource, Severity


def make_rule_config(
    *,
    id: str = "test-rule",
    type: str,
    source: LogSource | None = None,
    severity: Severity = Severity.HIGH,
    window_seconds: int = 120,
    enabled: bool = True,
    **params: Any,
) -> RuleConfig:
    return RuleConfig(
        id=id,
        type=type,
        enabled=enabled,
        severity=severity,
        source=source,
        window_seconds=window_seconds,
        params=params,
    )
