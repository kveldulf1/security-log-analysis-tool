"""Detector registry: rule ``type`` name -> factory that builds a stateful Rule
from a validated ``RuleConfig``.

``multi-vector-correlation`` is not built here — it is a cross-rule correlation
concern owned by :mod:`security_log_analysis_tool.correlation.engine`, not a
per-event detector.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import RuleConfig
from .base import Rule
from .brute_force import BruteForceRule, BruteForceSuccessRule
from .login_anomaly import RapidSuccessAfterFailuresRule
from .rate_limit import RateLimitAbuseRule
from .scanner import ScannerBurstRule
from .ssh_enum import SshInvalidUserEnumRule
from .sudo_rules import SudoSensitiveCommandRule
from .web_attacks import PathTraversalRule, SqliProbeRule

RuleFactory = Callable[[RuleConfig], Rule]

_REGISTRY: dict[str, RuleFactory] = {
    "brute-force": BruteForceRule,
    "brute-force-success": BruteForceSuccessRule,
    "path-traversal": PathTraversalRule,
    "sqli-probe": SqliProbeRule,
    "scanner-burst": ScannerBurstRule,
    "rate-limit-abuse": RateLimitAbuseRule,
    "sudo-sensitive-command": SudoSensitiveCommandRule,
    "ssh-invalid-user-enum": SshInvalidUserEnumRule,
    "rapid-success-after-failures": RapidSuccessAfterFailuresRule,
}


def build_rule(config: RuleConfig) -> Rule:
    """Build a stateful detector instance for ``config``.

    ``config.type`` is already validated by the config loader against the known
    rule types, so a lookup miss here only happens for the correlation-only type —
    callers are expected to filter that out before calling this (see
    :mod:`security_log_analysis_tool.pipeline.engine`).
    """

    factory = _REGISTRY.get(config.type)
    if factory is None:
        raise ValueError(f"no detector registered for rule type {config.type!r}")
    return factory(config)


__all__ = ["Rule", "build_rule"]
