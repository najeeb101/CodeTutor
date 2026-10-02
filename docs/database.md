# Database (Week 3)

Postgres 17 (local: `compose.yaml`; hosted later: Supabase). The tables are SQLAlchemy 2 ORM
classes in `src/codetutor/db/models.py`. Alembic migrations in
`src/codetutor/db/migrations/versions/` create and change them. The problem folders stay the
source of truth: `make db-sync` copies them in.

## 1. Tables

```
users ──────────────< submissions >──────────── problem_versions ◄──── problems
 id, name              id, user_id,              (problem_id, version)   id, version,
                       problem_id + version,     content_hash,           module, position,
                       code,                     problem (json: the       title, difficulty,
                       job columns,              FULL problem, hidden     active,
                       result columns            tests + solution)        student_view (json)
                            │
                            └──< test_results
                                 (submission_id, test_id), position, hidden, revealed,
                                 status, error, input / expected / actual (json), duration_ms
```

| Table | What it holds | Who reads it |
|---|---|---|
| `users` | one row per person (Week 3: name-only dev login, not secure) | API |
| `problem_versions` | a sealed copy of **every** problem version ever synced, hidden tests and solution included; rows are never updated | the worker (Step 2) only |
| `problems` | each problem's **current** version, student view only; `active = false` when its folder was removed | API |
| `submissions` | one row per submission. The row is also the **grading job** (Postgres is the queue): job columns (`job_status`, `attempts`, `lease_expires_at`, `started_at`, `finished_at`, `last_error`) + result columns (the `GradeResult` summary, NULL until done) | API, worker |
| `test_results` | one row per test of a graded submission (a `TestResult`) | API, Week 5 analytics |

`problem_versions` / `problems` is the same split as `dist/problems.jsonl` /
`problems_student.jsonl`: the internal view for grading, and the student view for everyone else.

## 2. Rules the database enforces

- **Hidden tests never reach the database rows the API reads.** `problems` holds only
  `to_student_view()`. The worker grades with `reveal_hidden=False` and stores only that. Two
  CHECKs on `test_results` back this up, so even a worker bug can't store hidden details:
  `NOT (hidden AND revealed)`, and an unrevealed row has SQL NULL `input`, `expected` and
  `actual`.
- **JSON null is not SQL NULL.** Setting a json column to Python `None` stores JSON `null`
  (a value). For a revealed test, that is right (`None` can be a real expected value). On an
  unrevealed row, the CHECK rejects it, so the worker must leave those columns **unset**.
  The tests pin both cases.
- **Submissions:** `job_status` is one of queued/running/done/failed. `done` ⇔ `result_status`
  is set, and a set result has every summary column. `reward` is between 0 and 1.
- **Foreign keys:** `problems (id, version)` and `submissions (problem_id, problem_version)`
  point at `problem_versions`, so a submission is always graded on the exact version the
  student saw.
- **Statuses are `text` + CHECK**, not Postgres ENUM types. They are easy to change in a
  migration, and the model builds the list from the Python enums. Migration 0001 keeps its own
  copy of the list (a migration is a snapshot). A new grader status needs a new migration, and
  `test_every_*_status_is_allowed` fails until it exists.
- Every constraint has a predictable name (naming convention in `models.py`), e.g.
  `ck_test_results_hidden_never_revealed`, so later migrations can find it.

### json, not jsonb (measured 2026-10-02)
`jsonb` stores numbers as Postgres `numeric` and prints them back in its own way: the float
`1e300` came back as an **int** with 301 digits, and `1E2` came back as `100`. The grader treats
`30` and `30.0` as different answers, so `jsonb` could change what a student sees, or an
expected value. `json` keeps the exact text: floats stay floats, and `-0.0` and `\u0000`
survive. We don't search inside these values with SQL, so we lose nothing.
Tests: `test_json_columns_keep_a_float_a_float`, `test_jsonb_would_turn_the_float_into_an_int`,
and the whole bank's round trip in `test_db_sync.py`.

## 3. Commands

```bash
make db-migrate   # create/upgrade the tables (alembic upgrade head); starts the DB if needed
make db-sync      # db-migrate + copy the problem folders in (safe to run again)
uv run alembic current            # which migration the database is at
uv run alembic check              # do the models and the migrations agree?
uv run alembic upgrade head --sql # print the SQL without running it
```
Without `DATABASE_URL`, everything uses the local dev database. The tests use their own
database, `codetutor_test` (or `TEST_DATABASE_URL`), which they drop and re-create on every
run. They never read `DATABASE_URL`.

## 4. How to change the schema
1. Change the classes in `src/codetutor/db/models.py`.
2. `uv run alembic revision --autogenerate -m "what changed" --rev-id 0002` (next number).
3. **Read and edit the new file by hand.** Autogenerate misses some things: it does not
   compare CHECK constraints, and a column rename looks like drop + add (which loses data).
   Write a `downgrade()` that really undoes the `upgrade()`.
4. `make db-migrate`, then `make test`. `test_models_and_migrations_agree` fails if a model
   change has no migration, and `test_migrations_go_down_and_up_again` checks the downgrade.
5. Never edit a migration that is already committed. Write a new one.

## 5. Problem sync (`make db-sync`, `src/codetutor/db/sync.py`)
1. A new (id, version): store a sealed copy in `problem_versions`, and point `problems` at it.
2. A stored (id, version) whose files changed (different `content_hash`, Week 1's hash over
   every file of the folder): **refused**. Bump `version` in problem.yaml. This also applies
   to a hint typo or a new buggy file, because a sealed copy never changes.
3. Versions only go up.
4. A problem whose folder is gone gets `active = false`. It is never deleted, because old
   submissions point to it. If the folder comes back, the problem is "restored".
5. A sync that finds no problems at all is refused (a wrong `--root` would retire everything).

Every rule is checked before anything is written, every broken rule is listed in one error,
and the script commits only at the end, so a sync is all or nothing.

## 6. Limitations (handed to later steps)
- Postgres `text` can't contain the NUL character (`\x00`); it raises a `DataError`. Step 2's
  worker must clean NUL out of `stdout` / error text before saving, and Step 3's API must
  reject code that contains NUL.
- The index for claiming jobs comes in Step 2, together with the claim query.
- Two syncs at the same moment are not guarded (sync is run by hand). A fix would be
  `pg_advisory_xact_lock` (docs/ideas.md).
- The hidden tests are in the database (`problem_versions`). The API never queries that
  table, but nothing stops it yet. When hosting: a separate database role for the API without
  access to `problem_versions` (docs/ideas.md).
- Connecting to a stopped local database hangs instead of failing (WSL mirrored networking),
  so every engine has `DB_CONNECT_TIMEOUT_S = 5` (`settings.py`).
