@export
Feature: Findings export
  Findings can be exported as JSON, CSV, or SARIF for downstream tooling.

  Background:
    Given the sample logs are analyzed with the default rules

  Scenario: JSON export contains every finding
    When the findings are exported as "json" to a temporary file
    Then the exported file contains the same number of findings

  Scenario: CSV export contains one row per finding
    When the findings are exported as "csv" to a temporary file
    Then the exported CSV has one row per finding

  Scenario: SARIF export validates against the SARIF 2.1.0 schema
    When the findings are exported as "sarif" to a temporary file
    Then the exported SARIF file is schema-valid

  @negative
  Scenario: SARIF export never leaks a raw secret from evidence
    Given a finding containing the secret "Password123!"
    When the findings are exported as "sarif" to a temporary file
    Then the exported file does not contain "Password123!"
