# Grading worker (Week 3)

The worker takes queued submissions from Postgres, grades them with the one grader
(`grade(problem, code, reveal_hidden=False)` in the Docker sandbox), and saves the result.
There is no Redis: the `submissions` row **is** the job (decided 2026-10-02). Saving a
submission and enqueueing it are the same insert, so a job can never get lost between two
systems.

Code: `src/codetutor/worker/jobs.py` (the queue in SQL), `src/codetutor/worker/loop.py` (the
loop), `scripts/worker.py`, `scripts/submit.py`. Tables: [database.md](database.md).

## 1. How a job moves

```
queued ──claim (attempts+1, lease 5 min)──> running ──save result──> done
   ^                                           │
   └──── grading raised an error, attempts < 3 ┘   (last_error kept)
running ──error at attempt 3, or lease expired at attempt 3──> failed
running ──lease expired (worker died), attempts < 3──> claimed again by any worker
```

Each job uses three steps, and no transaction stays open while grading:
1. **claim**: one short transaction, committed at once, so other workers see it;
2. **grade**: no transaction (1–38 s);
3. **save**: the result and its test rows in one short transaction (all or nothing).

A student's broken code is *not* an error here: it is a normal result (`compile_error`,
`runtime_error`, `timeout`, …). Errors are ours: a corrupt problem copy, the database, the sandbox.

## 2. The claim query (`CLAIM_SQL`)

```sql
UPDATE submissions
SET job_status = 'running', attempts = attempts + 1, started_at = now(),
    lease_expires_at = now() + make_interval(secs => :lease_s)
WHERE id = (
    SELECT id FROM submissions
    WHERE (job_status = 'queued' OR (job_status = 'running' AND lease_expires_at < now()))
      AND attempts < :max_attempts
    ORDER BY id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, attempts, problem_id, problem_version, code;
```
- The inner `SELECT` finds the oldest claimable job: queued, or running with an expired lease
  (its worker died). `ORDER BY id` makes it first in, first out.
- `FOR UPDATE` locks that row until the claim commits. **`SKIP LOCKED`**: a row that another
  worker has locked right now is skipped, not waited for. So two workers never get the same
  job, and they never wait for each other. (Tested: 8 threads claim 40 jobs at the same time,
  and every job is claimed exactly once.)
- The outer `UPDATE` marks it running, counts the attempt, and sets the **lease**. `RETURNING`
  hands the job to the worker in the same round trip.
- Before each claim, `FAIL_ABANDONED_SQL` marks jobs `failed` whose lease expired on the last
  allowed attempt.
- The partial index `ix_submissions_claimable` (migration 0002) holds only queued and running
  rows. Measured on the dev DB with 50 008 rows (50 000 done): the plan uses
  `Index Scan using ix_submissions_claimable`, and the index is 16 kB, against 1 112 kB for the
  primary key. Done jobs never slow the claim down.

## 3. Lease and fencing token
- **Lease** (`LEASE_S = 300` s): a claimed job belongs to its worker until `lease_expires_at`.
  If the worker dies, another worker takes the job after that time. The slowest bank problem
  needs at most ~38 s in Docker (valid_parentheses: 15 tests × 2 s + 3 s start-up + 5 s Docker
  margin). `test_the_lease_covers_the_slowest_bank_problem` keeps every problem under half the
  lease.
- **Fencing token** (`attempts`): each claim adds 1. Save and release only touch the row
  `WHERE id = :id AND attempts = :our_attempts AND job_status = 'running'`. A slow worker
  whose lease ran out finds a newer attempts number: its save updates 0 rows and writes
  nothing (outcome `lost`). So a result is never saved twice, even though a job can be
  *graded* twice. This is **at-least-once** processing with an **idempotent save**.

## 4. Errors and retries
- An exception while handling a job: the job goes back to `queued` with `last_error`
  (`ExceptionType: message`, at most 2 000 characters). On attempt 3 (`MAX_ATTEMPTS`) it
  becomes `failed` instead.
- The worker waits 2 s after an error. After **5 errors in a row** it stops (exit code 2),
  because then the setup is broken (Docker, the database), not one job. Otherwise a broken
  setup would burn through the whole queue.
- Postgres down: the worker stops with "cannot reach Postgres" (connect timeout 5 s). A
  process manager would restart it when hosted.

## 5. Saving
- Text columns can't hold NUL (`\x00`), so `clean_text` replaces it with `�` (U+FFFD) in
  `stdout`, `error`, `compile_error` and test errors. Values in `json` columns are stored as
  they are (`\u0000`, see database.md).
- Unrevealed (hidden) tests: `input` / `expected` / `actual` are left **unset** (SQL NULL),
  because `None` would be JSON `null`, which the table's CHECK rejects.
- `load_grade_result` rebuilds the same `GradeResult` (tested by comparing `repr`).
- The sealed problem copies are cached per worker run: a copy never changes, so the cache
  never goes stale.

## 6. Commands
```bash
make worker                      # db-sync, then grade until Ctrl+C (always the Docker sandbox)
uv run python scripts/worker.py --drain   # grade everything queued, then exit
uv run python scripts/submit.py cs1.loops.fizzbuzz path/to/file.py --wait   # dev tool
```
- **Ctrl+C / SIGTERM**: the current job finishes and is saved, then the worker exits. The
  grading child runs in its own session, so Ctrl+C never reaches the student's code. A second
  Ctrl+C stops at once; the job is then retried when its lease ends. (Checked: SIGINT during an
  `is_prime` grading → the job finished 1 s later as `timeout 13/14`, then "worker stopped".)
- **More throughput**: start more worker processes. They share the queue safely
  (`SKIP LOCKED`). One process grades one job at a time.
- Measured: fizzbuzz in Docker takes ~1.0 s per job end to end.

## 7. Limitations
- An idle worker polls once per second (one small indexed query). Postgres `LISTEN/NOTIFY`
  could wake it at once (docs/ideas.md).
- If the Docker daemon dies in the middle of a grading, the student gets `crashed` (Week 1
  limitation, docs/grader.md). Idea: re-check Docker after a `crashed` result, and retry.
- First in, first out across all users. The API limits each user to 3 waiting submissions
  and 10 per minute ([api.md](api.md) §4), so one user holds at most 3 places in the queue;
  the claim itself still takes the oldest job, whoever it belongs to.
- A dead worker's job waits up to 5 minutes (the lease) before it is retried.
- `last_error` can contain internal details (exception text); the API must not show it to
  students as is.
