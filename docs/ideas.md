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

- **(Week 4 Step 2+, measure first) A model as a second guardrail layer.** Ask a small model
  "does this hint contain code or give the whole answer away?" after the text checks. It could
  catch the known misses (code inside a sentence, renamed variables, a whole algorithm as a first
  hint). Measure it on `tests/hints/guardrail_cases.yaml` and real hints before using it: it adds
  a model call per hint, and a judge can be wrong too.

- **(Week 5, with the integrity checks) Rename-proof solution matching in the guardrail.**
  Compare token streams with names replaced (`tally[w]` ≈ `counts[word]`), the same idea as the
  AST-normalized similarity planned for copy detection. Needs care: short lines would then match
  far more prose.

- **(When notes grow to thousands of sections) Indexes for search.** An HNSW index on
  `note_chunks.embedding` (`vector_cosine_ops`) and a stored `tsvector` column with a GIN index.
  At 41 rows a full scan is exact and fast, and an approximate index would only add recall loss.

- **(Week 4 Step 2+, cheap to measure) Search experiments.** (1) Without nomic's task prefixes,
  to see how much they matter. (2) Boost sections of the problem's own module. (3) Store the
  embedding model's digest, not only its name, so a re-pulled model re-embeds the notes.

- **(Optional, if traces need a UI) Langfuse.** The brief planned Langfuse for tutor traces;
  Week 4 kept them as `hints` rows instead (decided 2026-10-02, not added 2026-10-06). An
  exporter could send finished hints to Langfuse Cloud (Hobby: 50k units/month, 30 days of
  data) for its trace viewer and dashboards. Costs: a new package, a key in `.env`, and hint
  text (student code inside) leaving the machine, so only with made-up or consenting users.

- **(Tutor eval, more data) Narrow the intervals.** 54 situations × 5 answers can't tell the
  tutor's +0.04 / +0.06 from 0. n = 10 makes the within-situation noise smaller (the intervals
  shrink by up to ~√2; the spread between situations stays) and takes ~1 h more on mains. A
  second student model (e.g. the 7B as the student, another family as the tutor) shows whether
  the result is about hints or about one model.

- **(Tutor prompt v2, measure with the eval) Two failure cases from Step 4.** (1) 16 of 54
  level-2 hints talk about "the student" instead of "you". (2) The teacher's hint 1 for
  group_anagrams lists three leads; the tutor picked the wrong one ("repeated words" instead of
  repeated letters) and the fix rate fell 0.80 → 0.00. Ideas: tell the model to name only what
  the visible/hidden results support, and add a "you" check to the guardrail's output checks.
  Bump `TUTOR_PROMPT_VERSION` and re-run the tutor conditions (the `none` answers are reused).

- **(Week 8 planning, or after Week 5 Step 3 if time allows) MCQ and true/false practice
  questions.** Najeeb's idea (2026-10-06): short concept questions per module, so students check
  their understanding, not only their code. Design sketch: one YAML file per module next to the
  course notes (question, options, the right one, a one-line explanation, concept tags); wrong
  options taken from real mistakes (each buggy file's misconception, e.g. `"a  b".split(" ")`);
  answers saved per user and item. Bonus: right/wrong answers are ideal items for the Rasch
  skill model (Week 5 Step 3), a second source of evidence besides code. Costs: 40-80 questions
  (Claude drafts, Najeeb reviews), new tables (schema change), API endpoints, a UI page; ~1-2
  days. Scope: a practice quiz, not an exam (exams are out of scope in the brief); the brief's
  job map lists a "placement quiz" as Light.

- **(Week 8, Step 3b) Show the risk score.** Add the early-warning score to the instructor API
  and a column on the dashboard (with the cutoff week and "a reason to check in, never a
  verdict"). Needs the model fitted on a class and stored with its version; real classes need
  real labels first (docs/early-warning.md §5).
- **(Week 8) Store and show the estimates.** Week 5 computes flags and Rasch estimates but only
  writes `integrity_flags`; skill and difficulty live in a report. For the instructor dashboard:
  a table for estimates (with the data version and date), screens for flags (reasons first,
  needs-review list per student) and skills. Keep "for a teacher, never a grade" in the wording.
- **(Later, needs real data) More integrity evidence.** The measured limit is honest students who
  paste whole programs from their own editor (76 of 79 false flags on the held-out class). New
  evidence is needed, not new thresholds: e.g. how often a student pastes and whether the pasted
  code was failing before, tests run before submit, time between runs. Tune on real classes only
  after consent and privacy are decided.
- **(Week 8 or later) Rasch beyond first tries.** Partial credit (the reward from `grade()`),
  a practice effect per attempt, or Elo for live updates. Worth it only where answers are
  missing in a biased way; on the complete simulated data counting was nearly as good.

