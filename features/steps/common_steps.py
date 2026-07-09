"""Shared step implementations reused by every feature file.

Later sessions add feature-specific steps (detection, correlation, auth, queue)
that build on these generic parsing/config steps.
"""

from __future__ import annotations

from behave import given, then, when

from security_log_analysis_tool import __version__
from security_log_analysis_tool.config import load_rules
from security_log_analysis_tool.models import LogEvent, ParseFailure
from security_log_analysis_tool.parsers import get_parser


@given("the security-log-analysis-tool package")
def step_have_package(context) -> None:
    context.package_version = __version__


@when("I read its version")
def step_read_version(context) -> None:
    context.result = context.package_version


@then("the version is a non-empty string")
def step_version_non_empty(context) -> None:
    assert isinstance(context.result, str) and context.result


@given("the default rules configuration")
def step_load_default_rules(context) -> None:
    context.app_config = load_rules(context.rules_path)


@then("the rules load without error")
def step_rules_loaded(context) -> None:
    assert context.app_config.rules


@given('a "{fmt}" parser')
def step_get_parser(context, fmt: str) -> None:
    context.parser = get_parser(fmt)


@when('it parses the line "{line}"')
def step_parse_line(context, line: str) -> None:
    context.parsed = context.parser.parse_line("<behave>", 1, line)


@then("the result is a valid event")
def step_result_is_event(context) -> None:
    assert isinstance(context.parsed, LogEvent)


@then("the result is a parse failure")
def step_result_is_failure(context) -> None:
    assert isinstance(context.parsed, ParseFailure)
