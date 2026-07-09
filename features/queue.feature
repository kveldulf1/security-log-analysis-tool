@queue
Feature: The job queue runs concurrent analyses without hanging
  The in-process queue accepts analysis jobs, runs them on a worker pool, pushes
  back when saturated, and survives a failing job — the "enterprise concurrency"
  answer at homework scale.

  @smoke
  Scenario: twenty concurrent analyses all finish
    Given a running job queue with 4 workers
    When I submit 20 concurrent analysis jobs
    Then all jobs finish successfully
    And the queue shuts down without hanging

  @negative
  Scenario: a failing job does not poison the pool
    Given a running job queue with 2 workers
    When I submit a job for a file that does not exist
    And I submit 3 concurrent analysis jobs
    Then the bad job is marked failed
    And all good jobs finish successfully
    And the queue shuts down without hanging

  Scenario: a queued job can be cancelled before it runs
    Given a job queue with all workers busy
    When I submit one more job and cancel it
    Then that job is cancelled without running

  @negative
  Scenario: excess submissions are rejected with backpressure
    Given a saturated job queue
    Then further submissions are rejected as queue-full
