"""Step implementations for detection.feature and correlation.feature.

Both features run the real engine against the committed sample logs and the
default rules — the same fixtures the CLI's own DoD check uses — so these
scenarios stay a living document over the real detection behaviour.
"""

from __future__ import annotations

from behave import given, then

from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.pipeline.engine import AnalysisEngine


@given("the sample logs are analyzed with the default rules")
def step_analyze_sample_logs(context) -> None:
    config = load_rules(context.rules_path)
    engine = AnalysisEngine(config)
    context.result = engine.analyze(
        [str(context.sample_logs / "access.log"), str(context.sample_logs / "auth.log")]
    )


@then('a finding for rule "{rule_id}" on ip "{ip}" exists')
def step_finding_exists_for_rule_ip(context, rule_id: str, ip: str) -> None:
    matches = [f for f in context.result.findings if f.rule_id == rule_id and f.ip == ip]
    assert matches, f"expected a {rule_id} finding on {ip}"
    context.matched_finding = matches[0]


@then('no finding for rule "{rule_id}" on ip "{ip}" exists')
def step_no_finding_for_rule_ip(context, rule_id: str, ip: str) -> None:
    matches = [f for f in context.result.findings if f.rule_id == rule_id and f.ip == ip]
    assert not matches, f"did not expect a {rule_id} finding on {ip}"


@then('a finding for rule "{rule_id}" with user "{user}" exists')
def step_finding_exists_for_rule_user(context, rule_id: str, user: str) -> None:
    matches = [f for f in context.result.findings if f.rule_id == rule_id and user in f.users]
    assert matches, f"expected a {rule_id} finding for user {user}"
    context.matched_finding = matches[0]


@then('no finding for rule "{rule_id}" with user "{user}" exists')
def step_no_finding_for_rule_user(context, rule_id: str, user: str) -> None:
    matches = [f for f in context.result.findings if f.rule_id == rule_id and user in f.users]
    assert not matches, f"did not expect a {rule_id} finding for user {user}"


@then('that finding has severity "{severity}"')
def step_matched_finding_severity(context, severity: str) -> None:
    assert context.matched_finding.severity.name.lower() == severity.lower()


@then('a correlated finding on ip "{ip}" exists')
def step_correlated_finding_exists(context, ip: str) -> None:
    matches = [f for f in context.result.findings if f.correlated_rule_ids and f.ip == ip]
    assert matches, f"expected a correlated finding on {ip}"
    context.matched_finding = matches[0]


@then('no correlated finding on ip "{ip}" exists')
def step_no_correlated_finding(context, ip: str) -> None:
    matches = [f for f in context.result.findings if f.correlated_rule_ids and f.ip == ip]
    assert not matches, f"did not expect a correlated finding on {ip}"


@then('that correlated finding has severity "{severity}"')
def step_correlated_finding_severity(context, severity: str) -> None:
    assert context.matched_finding.severity.name.lower() == severity.lower()


@then("that correlated finding references at least {count:d} distinct rules")
def step_correlated_rule_count(context, count: int) -> None:
    assert len(context.matched_finding.correlated_rule_ids) >= count
