@correlation
Feature: Cross-source multi-vector correlation
  A single IP triggering multiple rules across web and auth logs within a
  window is escalated to one CRITICAL correlated finding.

  Background:
    Given the sample logs are analyzed with the default rules

  Scenario: the web+ssh brute force attack is correlated
    Then a correlated finding on ip "10.0.0.50" exists
    And that correlated finding has severity "critical"
    And that correlated finding references at least 2 distinct rules

  Scenario: the scan+enumeration attack is correlated
    Then a correlated finding on ip "203.0.113.5" exists
    And that correlated finding references at least 2 distinct rules

  @negative
  Scenario: an isolated single-rule IP is not correlated
    Then no correlated finding on ip "192.0.2.10" exists
