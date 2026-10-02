# HTTP API (Week 3)

FastAPI service for the web UI (Step 4): list problems, show one problem (student view), log
in by name, submit code, read the result, list my submissions. The API **never grades**. It
saves the submission row (that row is the job, [worker.md](worker.md)), and a worker grades it.

Code: `src/codetutor/api/` (`app.py` builds the app, `routes.py` has the endpoints,
`submissions.py` the submit logic and rate limits, `schemas.py` the request/response models,
`deps.py` the session and the logged-in user). Tests: `tests/test_api.py`.

## 1. Endpoints (all under `/api`)

| Method + path | Login | What it does | Answers |
|---|---|---|---|
| `GET /api/health` | no | `SELECT 1` on the database | 200 `{"status":"ok"}`; 503 if the DB is down |
| `POST /api/login` `{"name"}` | no | find or create the user (dev login, §2) | 200 `{"id","name"}`; 422 bad name |
| `GET /api/problems` | no | active problems, by module, then order | 200 `[{id,title,module,module_name,order,difficulty}]` |
| `GET /api/problems/{id}` | no | the student view (`StudentProblem`) | 200; 404 unknown or retired |
| `POST /api/submissions` `{"problem_id","problem_version","code"}` | yes | rate limits (§4), then queue it | **202** `{"id","job_status":"queued"}` + `Location`; 404 / 409 / 422 / 429 |
| `GET /api/submissions/{id}` | yes | status, code, and the result once done | 200; 404 missing **or someone else's** |
| `GET /api/submissions?problem_id=&limit=20` | yes | my submissions, newest first (limit 1–100) | 200 list of summaries (no code) |

FastAPI also serves its automatic documentation at `http://127.0.0.1:8000/docs`.
`test_the_api_has_exactly_the_planned_endpoints` pins this list: a new endpoint needs a
deliberate test change.

### Submit, then poll
Grading takes 1–38 s, so a submit answers at once with **202 Accepted** and the submission's
URL in `Location`. The UI then asks `GET /api/submissions/{id}` about once a second until
`job_status` is `done` (the `result` is filled) or `failed`. Measured live: the submit request
took 0.05 s, and a fizzbuzz result was ready 1.1 s later (worker in Docker).

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
| 404 | unknown or retired problem; a submission that is missing or not yours | text |
| 409 | `problem_version` is not the current version (a sync ran after the student loaded it): reload the problem | text |
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
  of a problem on our side, not your code. Please submit again."), never `last_error`.
- **Allow-list:** every endpoint has a pydantic response model, so a field that isn't listed
  is dropped even if a query loaded it. `test_no_internal_field_is_part_of_the_api` checks
  the published OpenAPI schema for `last_error`, `attempts`, `hints`, `solution_code`,
  `buggy`, … And `test_the_api_code_never_names_the_table_with_hidden_tests` checks that no
  file in `src/codetutor/api/` names the sealed-copy table. That is a cheap guard until the API
  gets its own database role (ideas.md).
- **Other users' submissions:** 404, the same as a missing one, so nobody can probe which ids
  exist (403 would say "it exists, but it's not yours").

## 4. Rate limits
Counted in Postgres from the `submissions` table itself (`api/submissions.py`), not in memory.
So they survive restarts and hold across several API processes. Limits (`RateLimits`, tests pass
smaller ones):
- at most **3 waiting** (queued or running) submissions per user → 429, `Retry-After: 2`.
  This is the fairness rule: one user holds at most 3 places in the queue.
- at most **10 submissions per 60 s** per user (a sliding window) → 429, and `Retry-After` is
  the time until the oldest one leaves the window (live: `Retry-After: 51`).

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
make api      # terminal 2 (after the worker has started): db-sync, then http://127.0.0.1:8000
make web      # terminal 3: the web UI on http://localhost:3100 (web/README.md)
```
Start them one after the other: both run `db-sync`, and two syncs at once are not guarded
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
- Polling costs one small query per second per waiting student. Server push is in ideas.md.
- The 422 `detail` is a list for request-format errors and a string for our own checks.
- Connecting to a stopped local database takes the 5 s connect timeout before the 503 (WSL
  mirrored networking drops instead of refusing; measured 5.0 s).
