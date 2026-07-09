"""Application configuration: the rules loader and a tiny ``.env`` reader.

The rules loader is fail-closed and speaks in actionable errors, never tracebacks:
a malformed ``rules.yaml`` (bad YAML, unknown rule type, uncompilable regex) raises
``ConfigError``, which the CLI turns into a clean ``exit 2`` with a message a human
can act on. YAML is parsed with ``safe_load`` only — a rules file is untrusted input
like any other.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import LogSource, Severity

# Detector types the engine knows how to build. A rule's ``type`` selects one of
# these; its ``id`` names the instance (so two brute-force rules can differ only
# by source). Session 2 implements the detectors; the loader validates the names.
VALID_RULE_TYPES: frozenset[str] = frozenset(
    {
        "brute-force",
        "brute-force-success",
        "path-traversal",
        "sqli-probe",
        "scanner-burst",
        "rate-limit-abuse",
        "sudo-sensitive-command",
        "ssh-invalid-user-enum",
        "rapid-success-after-failures",
        "multi-vector-correlation",
    }
)

# Param keys whose values are regex strings — compiled at load to surface bad
# patterns early (and to give detectors a ReDoS-reviewed, pre-validated set).
_REGEX_PARAM_KEYS: frozenset[str] = frozenset({"patterns", "sensitive_patterns"})

_DEFAULT_WINDOW_SECONDS = 60


class ConfigError(Exception):
    """Raised for any invalid configuration. Carries a human-actionable message."""


@dataclass(frozen=True, slots=True)
class RuleConfig:
    id: str
    type: str
    enabled: bool
    severity: Severity
    source: LogSource | None
    window_seconds: int
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AlertConfig:
    min_severity: Severity
    sinks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AppConfig:
    version: int
    default_window_seconds: int
    alerts: AlertConfig
    rules: tuple[RuleConfig, ...]

    def enabled_rules(self) -> tuple[RuleConfig, ...]:
        return tuple(r for r in self.rules if r.enabled)


def load_rules(path: str | Path) -> AppConfig:
    """Load and validate a rules YAML file into an :class:`AppConfig`.

    Raises :class:`ConfigError` with an actionable message on any problem.
    """

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"rules file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read rules file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"rules file {path} is not valid YAML: {exc}") from exc

    if data is None or not isinstance(data, dict):
        raise ConfigError(f"rules file {path} must be a YAML mapping at the top level")

    return _build_config(data, path)


def _build_config(data: dict[str, Any], path: Path) -> AppConfig:
    version = data.get("version", 1)
    if not isinstance(version, int):
        raise ConfigError(f"{path}: 'version' must be an integer, got {version!r}")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"{path}: 'defaults' must be a mapping")
    default_window = defaults.get("window_seconds", _DEFAULT_WINDOW_SECONDS)
    if not isinstance(default_window, int) or default_window <= 0:
        raise ConfigError(f"{path}: defaults.window_seconds must be a positive integer")

    alerts = _build_alerts(data.get("alerts") or {}, path)

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError(f"{path}: 'rules' must be a non-empty list")

    rules: list[RuleConfig] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_rules):
        rule = _build_rule(raw, index, default_window, path)
        if rule.id in seen_ids:
            raise ConfigError(f"{path}: duplicate rule id {rule.id!r}")
        seen_ids.add(rule.id)
        rules.append(rule)

    return AppConfig(
        version=version,
        default_window_seconds=default_window,
        alerts=alerts,
        rules=tuple(rules),
    )


def _build_alerts(raw: dict[str, Any], path: Path) -> AlertConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: 'alerts' must be a mapping")
    min_sev_name = raw.get("min_severity", "high")
    try:
        min_severity = Severity.from_name(str(min_sev_name))
    except ValueError as exc:
        raise ConfigError(f"{path}: alerts.{exc}") from exc
    sinks = raw.get("sinks", [])
    if not isinstance(sinks, list) or not all(isinstance(s, str) for s in sinks):
        raise ConfigError(f"{path}: alerts.sinks must be a list of strings")
    return AlertConfig(min_severity=min_severity, sinks=tuple(sinks))


def _build_rule(raw: Any, index: int, default_window: int, path: Path) -> RuleConfig:
    where = f"{path}: rules[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")

    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ConfigError(f"{where} is missing a non-empty string 'id'")

    rule_type = raw.get("type")
    if rule_type not in VALID_RULE_TYPES:
        valid = ", ".join(sorted(VALID_RULE_TYPES))
        raise ConfigError(
            f"{where} ({rule_id}): unknown rule type {rule_type!r}; valid types: {valid}"
        )

    try:
        severity = Severity.from_name(str(raw.get("severity", "medium")))
    except ValueError as exc:
        raise ConfigError(f"{where} ({rule_id}): {exc}") from exc

    source = _parse_source(raw.get("source"), where, rule_id)

    window_seconds = raw.get("window_seconds", default_window)
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise ConfigError(f"{where} ({rule_id}): window_seconds must be a positive integer")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(
            f"{where} ({rule_id}): 'enabled' must be a boolean true/false, got {enabled!r}"
        )

    reserved = {"id", "type", "enabled", "severity", "source", "window_seconds"}
    params = {k: v for k, v in raw.items() if k not in reserved}
    _validate_regex_params(params, where, rule_id)

    return RuleConfig(
        id=rule_id,
        type=str(rule_type),
        enabled=enabled,
        severity=severity,
        source=source,
        window_seconds=window_seconds,
        params=params,
    )


def _parse_source(value: Any, where: str, rule_id: str) -> LogSource | None:
    if value is None:
        return None
    try:
        return LogSource(str(value))
    except ValueError as exc:
        valid = ", ".join(s.value for s in LogSource)
        raise ConfigError(
            f"{where} ({rule_id}): unknown source {value!r}; valid sources: {valid}"
        ) from exc


def _validate_regex_params(params: dict[str, Any], where: str, rule_id: str) -> None:
    for key in _REGEX_PARAM_KEYS:
        if key not in params:
            continue
        patterns = params[key]
        if not isinstance(patterns, list):
            raise ConfigError(f"{where} ({rule_id}): '{key}' must be a list of regexes")
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise ConfigError(f"{where} ({rule_id}): every '{key}' entry must be a string")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(
                    f"{where} ({rule_id}): invalid regex in '{key}': {pattern!r} ({exc})"
                ) from exc


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping. Missing file yields ``{}``.

    Supports ``KEY=VALUE``, ``export KEY=VALUE``, ``#`` comments, blank lines, and
    single/double quoted values. Does not touch ``os.environ`` (see ``apply_env``).
    """

    path = Path(path)
    if not path.exists():
        return {}

    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


def apply_env(mapping: dict[str, str], *, overwrite: bool = False) -> None:
    """Merge ``mapping`` into ``os.environ`` (existing keys kept unless overwrite)."""

    for key, value in mapping.items():
        if overwrite or key not in os.environ:
            os.environ[key] = value
