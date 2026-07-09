"""Unit tests for the AnalysisEngine: parse -> detect -> correlate pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_log_analysis_tool.config import ConfigError, load_rules
from security_log_analysis_tool.models import LogEvent, LogSource, Severity
from security_log_analysis_tool.pipeline.engine import AnalysisEngine

_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _ROOT / "config" / "rules.yaml"


@pytest.fixture(scope="module")
def result():
    config = load_rules(_RULES_PATH)
    engine = AnalysisEngine(config)
    return engine.analyze(
        [str(_ROOT / "sample_logs/access.log"), str(_ROOT / "sample_logs/auth.log")]
    )


def test_exactly_one_malformed_line(result) -> None:
    assert len(result.failures) == 1


@pytest.mark.smoke
def test_web_ssh_showcase_correlation_present(result) -> None:
    correlated = [f for f in result.findings if f.correlated_rule_ids]
    match = next((f for f in correlated if f.ip == "10.0.0.50"), None)
    assert match is not None
    assert len(match.correlated_rule_ids) >= 2


@pytest.mark.smoke
def test_scan_enum_showcase_correlation_present(result) -> None:
    correlated = [f for f in result.findings if f.correlated_rule_ids]
    match = next((f for f in correlated if f.ip == "203.0.113.5"), None)
    assert match is not None
    assert len(match.correlated_rule_ids) >= 2


def test_obrien_search_not_flagged_as_sqli(result) -> None:
    sqli = [f for f in result.findings if f.rule_id == "sqli-probe"]
    assert all(f.ip != "192.0.2.55" for f in sqli)


def test_benign_sudo_command_not_flagged(result) -> None:
    sudo_findings = [f for f in result.findings if f.rule_id == "sudo-sensitive-command"]
    assert all("bob" not in f.users for f in sudo_findings)
    assert any("alice" in f.users for f in sudo_findings)


def test_at_least_one_high_or_above_finding(result) -> None:
    assert any(f.severity >= Severity.HIGH for f in result.findings)


def test_clean_log_yields_zero_findings(tmp_path: Path) -> None:
    clean_log = tmp_path / "access.log"
    clean_log.write_text(
        '192.0.2.10 - - [03/Jul/2025:10:00:00 +0000] "GET / HTTP/1.1" 200 100 "-" "UA"\n',
        encoding="utf-8",
    )
    config = load_rules(_RULES_PATH)
    engine = AnalysisEngine(config)
    clean_result = engine.analyze([str(clean_log)])

    assert clean_result.findings == ()
    assert clean_result.failures == ()


def test_malformed_line_is_warning_logged(caplog: pytest.LogCaptureFixture) -> None:
    config = load_rules(_RULES_PATH)
    engine = AnalysisEngine(config)

    with caplog.at_level("WARNING", logger="security_log_analysis_tool.pipeline.engine"):
        fresh_result = engine.analyze(
            [str(_ROOT / "sample_logs/access.log"), str(_ROOT / "sample_logs/auth.log")]
        )

    assert len(fresh_result.failures) == 1
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 1
    assert "parse failure" in warning_records[0].message


def test_nonexistent_file_raises_config_error() -> None:
    config = load_rules(_RULES_PATH)
    engine = AnalysisEngine(config)
    with pytest.raises(ConfigError):
        engine.analyze(["does/not/exist.log"])


def test_reference_inference_uses_web_events_not_wall_clock() -> None:
    web_event = LogEvent(
        source=LogSource.WEB,
        file="f",
        line_no=1,
        timestamp=datetime(2025, 7, 3, 10, 0, 0, tzinfo=UTC),
        raw="x",
    )

    reference = AnalysisEngine._infer_reference([web_event])

    assert reference == datetime(2025, 7, 3, 10, 0, 0, tzinfo=UTC)


def test_reference_inference_falls_back_to_now_without_events() -> None:
    reference = AnalysisEngine._infer_reference([])

    assert abs((reference - datetime.now(UTC)).total_seconds()) < 5
