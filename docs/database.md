# Database (Weeks 3-4)

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
| `submissions` | one row per submission. The row is also the **grading job** (Postgres is the queue, [worker.md](worker.md)): job columns (`job_status`, `attempts`, `lease_expires_at`, `started_at`, `finished_at`, `last_error`) + result columns (the `GradeResult` summary, NULL until done) + `editor_stats` (Week 5, migration 0007: the web editor's times and typed/pasted counts, NULL for scripts, [api.md](api.md) §1) | API, worker; Week 5 integrity checks |
| `test_results` | one row per test of a graded submission (a `TestResult`) | API, Week 5 analytics |
| `note_chunks` (Week 4) | one row per `##` section of a course note (`course/notes/`): text, `content_hash`, `embed_model`, and `embedding vector(768)` (pgvector). Replaced in place when a note changes; `make notes-sync` fills it | the tutor's search ([tutor.md](tutor.md) §2) |
| `hints` (Week 4) | one row per hint request. The row is also the **tutor worker's job** (migration 0006, like `submissions`): `job_status`, `claims` (the fencing token), `lease_expires_at`, `started_at`, `finished_at`, `last_error`. When done: the shown `text`, `source` (model / fallback / reference) and the **trace**: the found note sections, every model attempt (incl. blocked ones, which may contain solution code: never return them to a student), settings, time. Also level, question, the student's code, `submission_id`; `rating` / `rated_at` for 👍/👎. Offline runs insert finished rows without a user | the tutor worker; the API (11 safe columns only, [api.md](api.md) §3), the Week 6–7 dataset |

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
  The tests pin both cases. The hint trace columns (`settings`, `retrieved`, `attempts`) use
  `JSON(none_as_null=True)` instead: there `None` means "no trace yet", and without it
  `ck_hints_result_complete` could not see a missing value (found by a test, 2026-10-05).
- **Submissions:** `job_status` is one of queued/running/done/failed. `done` ⇔ `result_status`
  is set, and a set result has every summary column. `reward` is between 0 and 1.
  `editor_stats` is SQL NULL or one JSON object (`ck_submissions_editor_stats_is_object`; its
  keys are checked by the API). It uses `JSON(none_as_null=True)`, so Python `None` is SQL NULL,
  not JSON `null` (which the CHECK refuses).
- **Hints:** the same job statuses; `done` ⇔ `text` is set, a set `text` has `source`,
  `settings`, `retrieved`, `attempts` and `latency_ms`; a rating only on a done hint, always
  with `rated_at`; level 1–3.
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
make notes-sync   # db-migrate + embed the course notes (needs Ollama; Week 4, tutor.md §2)
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
- Postgres `text` can't contain the NUL character (`\x00`); it raises a `DataError`. The worker
  replaces NUL in text columns, and `enqueue_submission` refuses code that contains it
  ([worker.md](worker.md) §5).
- The queue and the claim index (migration 0002): see [worker.md](worker.md).
- The API's per-user index `ix_submissions_user_id_created_at` (migration 0003, for the
  rate limits and "my submissions"): see [api.md](api.md) §4.
- Two syncs at the same moment are not guarded (sync is run by hand). A fix would be
  `pg_advisory_xact_lock` (docs/ideas.md).
- The hidden tests are in the database (`problem_versions`). The API never queries that
  table, but only a test stops it yet (`test_the_api_code_never_names_the_table_with_hidden_tests`
  checks that no API file names it). When hosting: a separate database role for the API
  without access to `problem_versions` (docs/ideas.md).
- Connecting to a stopped local database hangs instead of failing (WSL mirrored networking),
  so every engine has `DB_CONNECT_TIMEOUT_S = 5` (`settings.py`).
