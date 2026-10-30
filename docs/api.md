# HTTP API (Weeks 3-4)

FastAPI service for the web UI (Step 4): list problems, show one problem (student view), log
in by name, submit code, read the result, list my submissions, and (Week 4) ask the AI tutor
for a hint and rate it. The API **never grades and never writes hints**. It saves a row (that
row is the job), and a worker does the work: the grading worker ([worker.md](worker.md)) or
the tutor worker ([tutor.md](tutor.md) §4).

Code: `src/codetutor/api/` (`app.py` builds the app, `routes.py` has the endpoints,
`submissions.py` the submit logic and rate limits, `hints.py` the hint requests and ratings,
`schemas.py` the request/response models, `deps.py` the session and the logged-in user).
Tests: `tests/test_api.py`, `tests/test_api_hints.py`.

## 1. Endpoints (all under `/api`)

| Method + path | Login | What it does | Answers |
|---|---|---|---|
| `GET /api/health` | no | `SELECT 1` on the database | 200 `{"status":"ok"}`; 503 if the DB is down |
| `POST /api/login` `{"name"}` | no | find or create the user (dev login, §2) | 200 `{"id","name"}`; 422 bad name |
| `GET /api/problems` | no | active problems, by module, then order | 200 `[{id,title,module,module_name,order,difficulty}]` |
| `GET /api/problems/{id}` | no | the student view (`StudentProblem`) | 200; 404 unknown or retired |
| `POST /api/submissions` `{"problem_id","problem_version","code","editor_stats"?}` | yes | rate limits (§4), then queue it | **202** `{"id","job_status":"queued"}` + `Location`; 404 / 409 / 422 / 429 |
| `GET /api/submissions/{id}` | yes | status, code, and the result once done | 200; 404 missing **or someone else's** |
| `GET /api/submissions?problem_id=&limit=20` | yes | my submissions, newest first (limit 1–100) | 200 list of summaries (no code) |
| `POST /api/hints` `{"problem_id","problem_version","level", "submission_id" or "code", "question"?}` | yes | rate limits (§4), level order, then queue it | **202** `{"id","job_status":"queued"}` + `Location`; 404 / 409 / 422 / 429 |
| `GET /api/hints/{id}` | yes | status, then the hint `text` and `source` | 200; 404 missing **or someone else's** |
| `GET /api/hints?problem_id=&limit=20` | yes | my hints, newest first (limit 1–100) | 200 list |
| `PUT /api/hints/{id}/rating` `{"rating": 1 or -1}` | yes | 👍 / 👎; a new rating replaces the old one | 200 the hint; 404; 409 not done yet; 422 |

FastAPI also serves its automatic documentation at `http://127.0.0.1:8000/docs`.
`test_the_api_has_exactly_the_planned_endpoints` pins this list: a new endpoint needs a
deliberate test change.

### Submit, then poll
Grading takes 1–38 s, so a submit answers at once with **202 Accepted** and the submission's
URL in `Location`. The UI then asks `GET /api/submissions/{id}` about once a second until
`job_status` is `done` (the `result` is filled) or `failed`. Measured live: the submit request
took 0.05 s, and a fizzbuzz result was ready 1.1 s later (worker in Docker).

### The editor summary (Week 5)
The web UI also sends `editor_stats` with each submit: what its editor saw since the page was
opened or since the last submit. Times and counts only, no keystrokes:

| Field | Meaning |
|---|---|
| `since_open_ms` | ms since the page was opened, or since the last submit |
| `active_ms` | ms from the first edit to this submit (0 if nothing was edited) |
| `typed_chars` | characters inserted by edits that were not pastes |
| `pasted_chars`, `paste_count`, `largest_paste_chars` | pastes in this window |
| `edit_count` | edits, pastes included |
| `restored_draft` | the code came from a saved draft (a fast submit after a reload is normal) |

`EditorStats` (`api/schemas.py`) checks it: every field is required, whole numbers only
(`strict`: `"5"` or `5.0` is a 422), `>= 0`, at most 30 days / 10,000,000, no unknown keys, and
consistent (`largest_paste_chars <= pasted_chars`; `paste_count` is 0 exactly when
`pasted_chars` is; `active_ms <= since_open_ms`). A bad summary refuses the whole submit
(422), so the UI keeps every number inside these rules. The field is optional: scripts
(`submit.py`) send none, and the row's column stays SQL NULL ("no data", never a signal by
itself). It is stored in `submissions.editor_stats` and **never returned** by any endpoint.

**The browser can lie.** Anyone can send `pasted_chars: 0` with pasted code. The summary is
a *signal for a human* (Week 5 integrity checks), never proof; server-side checks that a client
can't fake (code similarity) carry more weight. The UI tells the student, under the editor,
that it sends this summary.

Measured live (2026-10-06, headless Chrome): typing 11 characters and pasting a 24-character
block gave `typed_chars: 11`, `pasted_chars: 24`, `paste_count: 1`, `edit_count: 12`; a
reload with a draft, then submit, gave all zeros with `restored_draft: true`; "Reset", then
submit, gave all zeros (our own replacements are not counted as typing).

### Ask for a hint, then poll (Week 4)
The same pattern as submitting: `POST /api/hints` answers **202** with the hint's URL, the
tutor worker writes the hint (warm: 1–5 s; the live check had answers 3.8 s and 5.7 s after the
request), and the UI polls `GET /api/hints/{id}`. A hint answer has 12 fields: `id`,
`problem_id`, `problem_version`, `submission_id`, `level`, `question`, `created_at`,
`job_status`, `text` (null until done), `source`, `rating`, `message`.
- **What it is about:** exactly one of `submission_id` (my graded submission of this problem
  and version: the tutor sees its visible results and the hidden pass/fail count) or `code`
  (not graded yet). A submission that isn't graded yet → 409; someone else's → 404.
- **Levels in order:** 1 (a nudge) → 2 (more specific) → 3 (the teacher's last hint, which
  gives most of the answer). Level L needs a finished hint of level L−1 or higher for this
  problem first, else 409 `"ask for a level L-1 hint first"`. Asking again at a level is fine.
- **`source`:** `"model"` (the AI tutor wrote it and it passed every check), `"fallback"` (the
  tutor's hints were blocked or the model failed: the teacher's hint of that level),
  `"reference"` (level 3). The UI says "from the AI tutor" or "from your teacher".
- **Rating:** only my finished hints; the last rating wins (`rated_at` is updated). Ratings
  are the preference data for Weeks 6–7.

### Display text (Python `repr`)
Values that a student sees also come as text, formatted by Python's `repr()` and cut at 500
characters (`MAX_REPR_CHARS`). JavaScript has one number type, so `JSON.parse("32.0")` gives
`32`, and a browser would show the wrong type (the grader treats 30 and 30.0 differently), and
`null`/`true` instead of `None`/`True`:
- each example (visible test) of a problem: `args_repr` (e.g. `"[1, 2], 3"`) and
  `expected_repr` (e.g. `"32.0"`, `"'Fizz'"`, `"None"`);
- each **revealed** test of a result: `args_repr`, `expected_repr`, `actual_repr`
  (`actual_repr` is null when the test has an `error`: the error says what happened). Hidden
  tests have no display text, just as they have no values.

The raw JSON values stay in the answer too. The eval prompt shows models the same `repr` text
(`evals/prompt.py`). Tests: `test_examples_carry_python_display_text`,
`test_a_graded_result_never_shows_hidden_test_details`,
`test_a_test_with_an_error_has_no_actual_text`, `test_long_display_text_is_cut`.

### Error codes
| Code | When | `detail` |
|---|---|---|
| 401 | no `X-User-Id` header, or an unknown user id | text |
| 404 | unknown or retired problem; a submission or hint that is missing or not yours | text |
| 409 | `problem_version` is not the current version (a sync ran after the student loaded it): reload the problem. Hints also: the previous level first; the submission isn't graded yet or is on an older version; rating a hint that isn't done | text |
| 422 | the request doesn't match its model, or the code can't be accepted (too long, NUL) | list of `{type, loc, msg}`, or text |
| 429 | a rate limit (§4); the `Retry-After` header says how many seconds to wait | text |
| 503 | the database can't be reached | text |

Our own 422 handler never copies the bad value back into the answer. FastAPI's default does,
and with a lone surrogate (`"\ud800"`, valid JSON but not encodable as UTF-8) the server
crashed with a 500 (found by `test_a_lone_surrogate_is_a_422_not_a_crash`). Errors are now
written as ASCII-escaped JSON.

## 2. Dev login (NOT secure)
`POST /api/login {"name": "sara"}` finds or creates the user and returns `{"id", "name"}`. The
client then sends `X-User-Id: <id>` with every request that needs a user. One dependency,
`current_user` (`deps.py`), reads it. Real authentication replaces only that function.
- **Anyone can send any id** and act as that user. Only for local development. The app logs a
  warning at startup, and `make api` binds to 127.0.0.1.
- Names: spaces around them are removed; 1–40 characters; any language; no control
  characters or lone surrogates. Names are case-sensitive ("Sara" and "sara" are two users).
- The id goes in the header, not the name, because header values must be ASCII.

## 3. What a client never sees
- **Hidden tests:** problems come only from `problems.student_view`. Results come from a
  grading with `reveal_hidden=False`, so a hidden test shows only its id, status and a short
  error: `revealed: false`, with `input`/`expected`/`actual` null. A student learns *that* a
  hidden test failed, never its input.
- **Internal job details:** a failed job shows one fixed `message` ("Grading failed because
  of a problem on our side, not your code. Please submit again."), never `last_error`. The
  same for a failed hint job (`HINT_FAILED_MESSAGE`).
- **The editor summary:** `editor_stats` goes in with a submit and never comes back out
  (`test_the_editor_summary_never_comes_back`).
- **The hint trace:** a `hints` row keeps every model attempt, including blocked ones that
  can contain solution code, plus the settings and the found note sections. The API selects
  only the 11 columns of `HINT_COLUMNS` (`api/hints.py`) and never the trace.
  `test_the_trace_never_leaves_the_api` makes the fake model write a solution line first
  (blocked) and checks that no answer contains it.
- **Allow-list:** every endpoint has a pydantic response model, so a field that isn't listed
  is dropped even if a query loaded it. `test_no_internal_field_is_part_of_the_api` checks
  the published OpenAPI schema for `last_error`, `attempts`, `hints`, `solution_code`,
  `buggy`, … And `test_the_api_code_never_names_the_table_with_hidden_tests` checks that no
  file in `src/codetutor/api/` names the sealed-copy table. That is a cheap guard until the API
  gets its own database role (ideas.md).
- **Other users' submissions:** 404, the same as a missing one, so nobody can probe which ids
  exist (403 would say "it exists, but it's not yours").

## 4. Rate limits
Counted in Postgres from the `submissions` and `hints` tables themselves
(`find_limit_hit` in `api/submissions.py`), not in memory.
So they survive restarts and hold across several API processes. Limits (`RateLimits`, tests pass
smaller ones):
- at most **3 waiting** (queued or running) submissions per user → 429, `Retry-After: 2`.
  This is the fairness rule: one user holds at most 3 places in the queue.
- at most **10 submissions per 60 s** per user (a sliding window) → 429, and `Retry-After` is
  the time until the oldest one leaves the window (live: `Retry-After: 51`).
- hints (Week 4): at most **1 waiting** hint request per user (`Retry-After: 2`; a warm hint
  takes 1–5 s of GPU time) and at most **10 per 10 minutes**. The same user-row lock;
  `test_requests_at_the_same_moment_never_pass_the_limit` (hints) lets exactly 5 of 12 in.

**The race and the lock.** "Count, then insert" is a *check-then-act race*: two submits at the
same moment can both count 9 and both insert. So `create_submission` first locks the user's
row (`SELECT … FOR UPDATE`), then counts, then inserts, all in one transaction. A second submit
of the same user waits for the first one's commit and then sees its row. Other users never
wait. `test_submits_at_the_same_moment_never_pass_the_limit` starts 12 threads at once with a
limit of 5. With the lock, exactly 5 got in (10/10 runs). With the lock removed, **12 of 12**
got in (3/3 runs).

Index: `ix_submissions_user_id_created_at` (migration 0003). EXPLAIN ANALYZE with 50 000 rows
(500 users, rolled back afterwards): the window count is an index-only scan (0.6 ms), "my
submissions" reads the index backwards (0.1 ms), and the waiting count uses the worker's partial
index (1.3 ms).

## 5. Commands
```bash
make worker   # terminal 1: db-sync, then grade in Docker
make tutor    # terminal 2: db-sync + notes-sync, then answer hint requests (needs Ollama)
make api      # terminal 3 (after the workers have started): db-sync, then http://127.0.0.1:8000
make web      # terminal 4: the web UI on http://localhost:3100 (web/README.md)
```
Start them one after the other: they all run `db-sync`, and two syncs at once are not guarded
(database.md §6).

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s -X POST http://127.0.0.1:8000/api/login -H 'content-type: application/json' \
  -d '{"name": "sara"}'
# {"id":1,"name":"sara"}   <- your id may differ; use it below
curl -s http://127.0.0.1:8000/api/problems/cs1.loops.fizzbuzz
curl -s -i -X POST http://127.0.0.1:8000/api/submissions -H 'X-User-Id: 1' \
  -H 'content-type: application/json' \
  -d '{"problem_id": "cs1.loops.fizzbuzz", "problem_version": 1, "code": "def fizzbuzz(n):\n    return []\n"}'
# HTTP/1.1 202 Accepted ... location: /api/submissions/<id>
curl -s http://127.0.0.1:8000/api/submissions/<id> -H 'X-User-Id: 1'
curl -s 'http://127.0.0.1:8000/api/submissions?limit=5' -H 'X-User-Id: 1'
# A hint about that (graded) submission, then its text, then 👍:
curl -s -i -X POST http://127.0.0.1:8000/api/hints -H 'X-User-Id: 1' \
  -H 'content-type: application/json' \
  -d '{"problem_id": "cs1.loops.fizzbuzz", "problem_version": 1, "level": 1, "submission_id": <id>}'
# HTTP/1.1 202 Accepted ... location: /api/hints/<hint id>
curl -s http://127.0.0.1:8000/api/hints/<hint id> -H 'X-User-Id: 1'
curl -s -X PUT http://127.0.0.1:8000/api/hints/<hint id>/rating -H 'X-User-Id: 1' \
  -H 'content-type: application/json' -d '{"rating": 1}'
```

## 6. Design notes
- **Plain `def` endpoints, synchronous SQLAlchemy**, like the rest of the project. FastAPI
  runs them in its thread pool (40 threads); the engine pool has 5 + 10 connections, so extra
  requests wait for a free connection.
- One `Session` per request (`get_session`). Writes commit in the endpoint. An error before
  the commit rolls back when the session closes, which also releases the rate-limit lock.
- `create_app(engine=None, limits=None)` is an app factory: uvicorn calls it with no
  arguments (`--factory`), and tests pass the test database's engine.
- **Telemetry:** this FastAPI version depends on `opentelemetry-api`, which does nothing
  without an SDK. `telemetry={"auto_configure": False}` also stops `OTEL_*` environment
  variables from adding exporters. No data leaves the machine; tracing is a Week 4 decision.
- No CORS: in Step 4, Next.js forwards `/api/*` to port 8000, so the browser sees one origin.

## 7. Limitations
- The dev login is spoofable, and anyone can create many names, which gets around the
  per-user limits. Real authentication and a per-IP limit are needed before hosting.
- No request-size limit: uvicorn reads the whole body before the 50 000-character check. When
  hosted, the reverse proxy must limit it (ideas.md).
- Polling costs one small query per second per waiting student (submissions and hints).
  Server push is in ideas.md.
- The 422 `detail` is a list for request-format errors and a string for our own checks.
- Connecting to a stopped local database takes the 5 s connect timeout before the 503 (WSL
  mirrored networking drops instead of refusing; measured 5.0 s).

## 8. The instructor routes (Week 8 Step 1; dev token, NOT real authentication)

For the dashboard (Step 2). Read-only. A teacher sends `X-Instructor-Token`, a shared secret from
the `INSTRUCTOR_TOKEN` environment variable (16+ characters; a shorter or missing value switches
the routes **off**: 503). Wrong token: 403. No token (a student's `X-User-Id` is not enough): 401.
The token is compared in constant time. One token for all teachers, sent in a header, with no
limit on wrong guesses: fine on `127.0.0.1`, to be replaced by real accounts before hosting.

| Method + path | What it returns |
|---|---|
| `GET /api/instructor/overview` | students, problems, submissions, accepted share, first-try solve share, how many students/submissions need review, when the integrity job last wrote flags, `risk_available` (is any risk score shown) |
| `GET /api/instructor/students` | per student: submissions, problems tried/solved, first-try share, last active, Rasch skill, `risk` (0..1 or null), submissions to review. Most to review first (not ordered by risk) |
| `GET /api/instructor/students/{id}` | the same, plus every problem they tried and every flag with its sentence for the teacher (404 if they have not submitted) |
| `GET /api/instructor/problems` | per problem: declared difficulty, students who tried it, first-try share, Rasch difficulty |

- **No code leaves these routes.** A test searches every answer for the solution's text.
- Skill and difficulty are computed on every request from the first tries (the Week 5 rule,
  `skill/load.py`), not stored: a class of tens of students takes 0.2-0.3 s per call (measured over HTTP on the
  simulated class of 60 students and 3,145 submissions). "Higher skill = more skilled; higher
  difficulty = harder"; the numbers say who may need help and are never a grade.
- Flags are written by the batch job (`make integrity`, on the database you point the API at).
  Before it has run, the lists are empty and `flags_computed_at` is null. `needs_review` follows
  the frozen rule (one entry signal + one content signal on the same submission).
- **Try it on the simulated class:**
  ```bash
  INSTRUCTOR_TOKEN=$(openssl rand -hex 16) make api-sim   # API on codetutor_sim (SIM_SEED=1: the held-out class)
  curl -s http://127.0.0.1:8000/api/instructor/overview -H "X-Instructor-Token: <your token>"
  ```
  (`make sim` and `make integrity` must have run before, ~13 min.)
- **The dashboard (Week 8 Step 2)** is `/instructor` in the web UI. The teacher types the token
  into a box; it is kept in `sessionStorage` (gone when the tab closes) and sent as
  `X-Instructor-Token`. A wrong token (401/403) is forgotten and the box comes back. The pages are
  client components, because the token exists only in the browser. To see it on the simulated
  class: `INSTRUCTOR_TOKEN=... API_PORT=8010 make api-sim`, then
  `CODETUTOR_API_URL=http://127.0.0.1:8010 make web`.
- **Risk (Week 8 Step 3b).** `risk` is the early-warning model's probability that a student will
  solve fewer than 40% of later problems on the first try, from weeks 1-3 only
  (docs/early-warning.md). Computed on every request, nothing stored. It is null until the class has
  a submission in week 3 or later (`risk_available` false), and for a student with no submission in
  weeks 1-3. The model is not fitted per request: it is the committed file
  `src/codetutor/early/model_week3.json` (version "1", fitted on simulated class seed 0), loaded by
  `early/served.py`. `make early-export` rewrites it; `make early` refuses to run if the file
  differs from a fresh fit.
- Only `api/instructor.py` reads `integrity_flags`; `test_no_api_code_reads_the_flags` pins that.
