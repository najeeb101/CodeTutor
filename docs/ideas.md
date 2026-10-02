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

- **(If the queue gets long) Fairness in the claim itself.** Done in Step 3 at the API: at
  most 3 waiting submissions and 10 per minute per user (docs/api.md §4). The claim still takes
  the oldest job, so with many users a newcomer waits behind 3 × (number of users) jobs. A
  claim query that prefers users with fewer running jobs would share workers more evenly.

- **(Before hosting) A request-size limit.** uvicorn reads the whole body into memory before
  `enqueue_submission` checks the 50 000-character limit, so a 1 GB POST is read in full. The
  reverse proxy in front of the API should cap it (nginx `client_max_body_size`, about 256 KB),
  or an ASGI middleware could count the bytes as they arrive.

- **(Before hosting) A per-IP limit on login.** The dev login creates a user for any new name,
  so one person can get around the per-user rate limits with many names. Real authentication
  fixes most of it; a per-IP limit on `POST /api/login` and on submits covers the rest.

- **(Step 4+, UI) Queue position.** "2 submissions ahead of you": count the queued or running
  jobs with a smaller id (the partial claim index makes this cheap).

- **(If polling costs matter) Push results instead of polling.** The UI asks once a second
  until a job is done. Server-Sent Events (one open HTTP response per waiting student) plus
  Postgres `LISTEN/NOTIFY` from the worker would push the result at once. Keep polling as the
  fallback.

- **(Grader, needs its own plan) A returned lone surrogate is graded `crashed`.** Found
  2026-10-02: `return "\ud800x"` gives `crashed` ("exited with code 0 without a result"), not
  `wrong_answer`, because the runner's report can't be encoded. Harmless for CS1 problems, but the
  label is wrong. A fix would change grading, so it needs a GRADER_VERSION bump.

- **(If the UI grows) Playwright instead of the hand-written browser check.** `make web-e2e`
  (Week 3 Step 5) drives Chrome through its DevTools protocol with no packages. Playwright
  would give auto-waiting, traces and a test runner, at the cost of a package and ~150-300 MB
  of browsers (plus Chromium's system libraries in WSL). Worth it once there are many UI flows.

- **(If the API grows) Generate `web/lib/types.ts` from `/openapi.json`.** The TypeScript types
  are written by hand from the pydantic models and can drift. A generator (e.g.
  openapi-typescript, a new dev package) would keep them in sync, with a check in
  `make web-check`.

- **(UI) "Solved" marks in the problem list.** It needs the student's best result per problem:
  one small endpoint (`GET /api/me/progress`) or a summary of `GET /api/submissions`.

- **(When Monaco updates) Re-check `npm audit`.** monaco-editor 0.57 bundles DOMPurify 3.4.15
  (low-severity XSS through `IN_PLACE` mode, which Monaco never uses). Upgrade when a Monaco
  release ships DOMPurify >= 3.4.16.
