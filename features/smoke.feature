@smoke
Feature: Foundations are wired up
  The behave harness runs against the real package, parsers, and rules loader.

  Scenario: the package reports a version
    Given the security-log-analysis-tool package
    When I read its version
    Then the version is a non-empty string

  Scenario: the default rules configuration loads
    Given the default rules configuration
    Then the rules load without error

  Scenario Outline: parsers classify lines correctly
    Given a "<fmt>" parser
    When it parses the line "<line>"
    Then the result is a valid event

    Examples:
      | fmt    | line                                                                                      |
      | apache | 10.0.0.50 - - [03/Jul/2025:10:15:32 +0000] "POST /login HTTP/1.1" 200 1234                 |
      | syslog | Jul  3 10:15:32 web-01 sshd[1234]: Accepted password for alice from 10.0.0.50 port 22 ssh2 |
