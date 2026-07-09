"""Tests for the rules loader and .env reader, positive and negative."""

from __future__ import annotations

from pathlib import Path

import pytest

from security_log_analysis_tool.config import (
    AppConfig,
    ConfigError,
    apply_env,
    load_env_file,
    load_rules,
)
from security_log_analysis_tool.models import LogSource, Severity

_GOOD_RULES = """
version: 1
defaults:
  window_seconds: 120
alerts:
  min_severity: high
  sinks: [toast, email]
rules:
  - id: web-brute-force
    type: brute-force
    source: web
    severity: high
    threshold: 5
    statuses: [401, 403]
  - id: path-traversal
    type: path-traversal
    source: web
    severity: high
    enabled: false
    patterns:
      - "\\\\.\\\\./"
      - "%2e%2e"
  - id: sudo-sensitive-command
    type: sudo-sensitive-command
    source: auth
    severity: critical
    sensitive_patterns:
      - "/etc/shadow"
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "rules.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_valid_rules(tmp_path: Path) -> None:
    cfg = load_rules(_write(tmp_path, _GOOD_RULES))
    assert isinstance(cfg, AppConfig)
    assert cfg.version == 1
    assert cfg.default_window_seconds == 120
    assert cfg.alerts.min_severity is Severity.HIGH
    assert cfg.alerts.sinks == ("toast", "email")
    assert len(cfg.rules) == 3

    web = cfg.rules[0]
    assert web.id == "web-brute-force"
    assert web.type == "brute-force"
    assert web.source is LogSource.WEB
    assert web.severity is Severity.HIGH
    assert web.window_seconds == 120  # inherited from defaults
    assert web.params["threshold"] == 5
    assert web.params["statuses"] == [401, 403]

    # enabled flag honoured
    assert [r.id for r in cfg.enabled_rules()] == ["web-brute-force", "sudo-sensitive-command"]


def test_real_shipped_rules_file_loads() -> None:
    cfg = load_rules(Path("config/rules.yaml"))
    assert cfg.rules
    # Every shipped rule uses a known type (loader would have raised otherwise).
    assert all(r.type for r in cfg.rules)


def test_missing_file_raises_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_rules(tmp_path / "nope.yaml")


def test_bad_yaml_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_rules(_write(tmp_path, "rules: [oops: :\n  - broken"))


def test_unknown_rule_type_lists_valid_types(tmp_path: Path) -> None:
    text = "rules:\n  - id: x\n    type: no-such-type\n"
    with pytest.raises(ConfigError) as exc:
        load_rules(_write(tmp_path, text))
    msg = str(exc.value)
    assert "unknown rule type" in msg
    assert "brute-force" in msg  # valid types are listed


def test_bad_regex_raises_config_error(tmp_path: Path) -> None:
    text = 'rules:\n  - id: x\n    type: path-traversal\n    patterns: ["("]\n'
    with pytest.raises(ConfigError, match="invalid regex"):
        load_rules(_write(tmp_path, text))


def test_duplicate_rule_id_rejected(tmp_path: Path) -> None:
    text = "rules:\n  - id: dup\n    type: brute-force\n  - id: dup\n    type: sqli-probe\n"
    with pytest.raises(ConfigError, match="duplicate rule id"):
        load_rules(_write(tmp_path, text))


def test_missing_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing a non-empty string 'id'"):
        load_rules(_write(tmp_path, "rules:\n  - type: brute-force\n"))


def test_empty_rules_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="non-empty list"):
        load_rules(_write(tmp_path, "rules: []\n"))


def test_quoted_enabled_string_rejected(tmp_path: Path) -> None:
    # A quoted "false" must not silently coerce to True and re-enable the rule.
    text = 'rules:\n  - id: x\n    type: brute-force\n    enabled: "false"\n'
    with pytest.raises(ConfigError, match="'enabled' must be a boolean"):
        load_rules(_write(tmp_path, text))


def test_bad_severity_rejected(tmp_path: Path) -> None:
    text = "rules:\n  - id: x\n    type: brute-force\n    severity: apocalyptic\n"
    with pytest.raises(ConfigError, match="unknown severity"):
        load_rules(_write(tmp_path, text))


def test_bad_source_rejected(tmp_path: Path) -> None:
    text = "rules:\n  - id: x\n    type: brute-force\n    source: mainframe\n"
    with pytest.raises(ConfigError, match="unknown source"):
        load_rules(_write(tmp_path, text))


def test_top_level_not_mapping_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        load_rules(_write(tmp_path, "- just\n- a\n- list\n"))


# --- .env loader ---


def test_load_env_file_parses_lines(tmp_path: Path) -> None:
    env_text = (
        "# a comment\n"
        "\n"
        "SLAT_USERNAME=analyst\n"
        'export SLAT_SMTP_PASSWORD="p@ss word"\n'
        "SLAT_SMTP_TO='soc@example.com'\n"
        "EQUALS_IN_VALUE=a=b=c\n"
        "NOEQUALS\n"
    )
    p = tmp_path / ".env"
    p.write_text(env_text, encoding="utf-8")
    env = load_env_file(p)
    assert env == {
        "SLAT_USERNAME": "analyst",
        "SLAT_SMTP_PASSWORD": "p@ss word",
        "SLAT_SMTP_TO": "soc@example.com",
        "EQUALS_IN_VALUE": "a=b=c",
    }


def test_load_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / ".env") == {}


def test_apply_env_does_not_overwrite_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAT_EXISTING", "keep")
    apply_env({"SLAT_EXISTING": "new", "SLAT_FRESH": "set"})
    import os

    assert os.environ["SLAT_EXISTING"] == "keep"
    assert os.environ["SLAT_FRESH"] == "set"
    apply_env({"SLAT_EXISTING": "forced"}, overwrite=True)
    assert os.environ["SLAT_EXISTING"] == "forced"
