@detection
Feature: Detection rules flag suspicious activity
  Rules run against the committed sample logs using the default rules.yaml.

  Background:
    Given the sample logs are analyzed with the default rules

  Scenario: web brute force is detected
    Then a finding for rule "web-brute-force" on ip "10.0.0.50" exists

  Scenario: ssh brute force followed by success is detected as critical
    Then a finding for rule "ssh-brute-force-success" on ip "10.0.0.50" exists
    And that finding has severity "critical"

  Scenario: scanner burst is detected
    Then a finding for rule "scanner-burst" on ip "203.0.113.5" exists

  Scenario: path traversal is detected
    Then a finding for rule "path-traversal" on ip "203.0.113.5" exists

  Scenario: sqli probe is detected
    Then a finding for rule "sqli-probe" on ip "198.51.100.23" exists

  Scenario: ssh invalid-user enumeration is detected
    Then a finding for rule "ssh-invalid-user-enum" on ip "203.0.113.5" exists

  Scenario: sudo sensitive command is detected
    Then a finding for rule "sudo-sensitive-command" with user "alice" exists

  @negative
  Scenario: the O'Brien search is not flagged as SQL injection
    Then no finding for rule "sqli-probe" on ip "192.0.2.55" exists

  @negative
  Scenario: the benign sudo command is not flagged
    Then no finding for rule "sudo-sensitive-command" with user "bob" exists
