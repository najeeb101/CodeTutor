# Ideas for later weeks

Ideas that come up during a week but belong to a later week. Add them here instead of building them.


- **(Week 5, integrity) AST check for banned calls.** `merge_sorted` asks students not to use
  `sort()`/`sorted()`, but a timing test can't catch it (`sorted(a + b)` runs in C and is faster
  than a correct Python merge; measured 0.2 ms vs 1.8 ms at n = 10 000). An AST scan of the
  submission could flag banned calls. It should be a *flag for a human*, never an automatic 0.

- **(Week 6, RL reward) Efficiency tests are worth very little under partial credit.** The naive
  `is_prime` (tries every number up to n) passes 13 of 14 tests and gets reward 0.93; only the one
  big prime times out. So an RL model gets almost no push to learn the fast algorithm. Options to
  test in Week 6: give efficiency tests more weight, or a bonus only when *all* tests pass.
  Measure first; don't change the reward blindly.

- **(Hosting, before strangers use it) A database role for the API without access to
  `problem_versions`.** The hidden tests live in that table (the worker grades from it). The API
  never queries it, but only code review stops it today. With a separate Postgres role for the
  API (`GRANT SELECT` on `problems`, `submissions`, `test_results`, … but not on
  `problem_versions`), the database itself would refuse. The worker keeps its own role.

- **(Week 3+, if sync runs automatically) Guard against two syncs at once.** Sync is run by
  hand today. If a deploy step ever runs it on several machines at the same time, take
  `pg_advisory_xact_lock(<fixed number>)` at the start of the sync transaction, so the second
  sync waits for the first.

- **(If version bumps get annoying) Split `content_hash` into "affects grading" and "doesn't".**
  Today any change to a problem folder (even a hint typo or a new buggy file) needs a version
  bump before sync, because a stored copy never changes. A second hash over only what grading
  uses (tests, function name, limits, input check) could allow in-place updates of the rest.
  More rules to explain, so only do it if bumps become a real cost (e.g. for Week 2 eval
  results, which warn about answers graded on an older version).

- **(Week 3+, if latency matters) Wake workers with Postgres `LISTEN/NOTIFY`.** An idle worker
  polls once per second today. The API could `NOTIFY grading` after inserting a submission, and
  workers `LISTEN` for it, so grading starts at once. Keep the poll as a fallback (a missed
  notification must never strand a job).

- **(Before strangers use it) Tell a Docker failure apart from a student's crash.** If the
  Docker daemon dies mid-grading, the result is `crashed` and the student is blamed. The worker
  could re-check Docker (`docker image inspect`, like `DockerSandbox()` does at start) after a
  `crashed` result, and release the job for a retry instead of saving it. Same principle as the
  Week 2 finish_reason fix: infrastructure noise must not count against the code.

- **(With the API) Fairness between users.** The queue is first in, first out, so one user
  submitting 100 times delays everyone. Options: a per-user rate limit in the API, or a claim
  query that prefers users with fewer running jobs.

- **(Grader, needs its own plan) A returned lone surrogate is graded `crashed`.** Found
  2026-10-02: `return "\ud800x"` gives `crashed` ("exited with code 0 without a result"), not
  `wrong_answer`, because the runner's report can't be encoded. Harmless for CS1 problems, but the
  label is wrong. A fix would change grading, so it needs a GRADER_VERSION bump.
