@auth
Feature: Authentication and authorization
  Roles are the smallest realistic SOC set: analyst and admin. Enforcement lives
  at the service layer, not just in what a UI chooses to show.

  Background:
    Given a fresh user store
    And an admin user "amelia.reyes" with password "Password123!"
    And an analyst user "oscar.lindqvist" with password "P@ssword123?"

  @smoke
  Scenario: an analyst session cannot perform an admin-only operation
    Given an analyst session for "oscar.lindqvist"
    When they attempt to manage users
    Then the attempt is denied with an authorization error

  Scenario: an admin session can perform an admin-only operation
    Given an admin session for "amelia.reyes"
    When they attempt to manage users
    Then the attempt succeeds

  Scenario: a locked account is rejected even with the correct password
    Given 5 consecutive failed login attempts for "oscar.lindqvist"
    When "oscar.lindqvist" logs in with the correct password
    Then the login is rejected as locked

  Scenario: a weak password is rejected at account creation
    When an admin creates a user "weak.walter" with password "short"
    Then the creation is rejected as a weak password

  Scenario Outline: SQL-injection-shaped credentials never authenticate
    When someone logs in as "<username>" with password "<password>"
    Then the login is rejected
    And no new user row is created

    Examples:
      | username              | password |
      | admin' OR '1'='1' --  | anything |
      | ' OR 1=1; --          | anything |
