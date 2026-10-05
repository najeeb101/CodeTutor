# CLAUDE.md: project memory for CodeTutor

Read this at the start of every session. The full original brief is `docs/KICKOFF.md` (never edit it).

## Project in one paragraph
CodeTutor is a **portfolio project** by Najeeb (4th-year CS student, Qatar University, AI/ML) aimed at
getting hired at **Scale AI** (first interview expected by ~Feb 2027). It is a CS1 Python practice
platform: instant auto-grading, an AI tutor that gives **hints, not answers**, integrity flags for
suspicious submissions, and an instructor dashboard. Its hidden second purpose is an **AI lab**: because
every problem has automatic tests, the same grader evaluates LLMs (pass@k) and acts as the **reward
function** for GRPO training of a small model. Understanding beats speed: Najeeb must be able to explain
every line in an interview.

## Working protocol (strict)
- **Explain in very simple English**, with short sentences. Give check questions as multiple choice (A/B/C/D) in plain text.
- **Use real-life scenarios for hard ideas** (e.g. "teacher room / exam room", "checking a grocery bag against the order"). Always also give the real technical term, and say briefly where the analogy stops being true.
- **Every step starts in plan mode.** Present the plan for the step and get approval before writing
  code. (Najeeb's request, 2026-09-28.)
- Work in small numbered steps (Section 9 of the brief). Never do more than one step without stopping.
- At every STOP: (1) plain-English summary (Najeeb is not a native speaker; avoid or explain jargon),
  (2) files created/changed, one line each, (3) exact commands to run/verify, (4) key design decisions
  and trade-offs, (5) 2–3 short check questions (don't give answers until he replies), (6) wait for "OK"/"go".
- Teach: explain a non-trivial file in 3–5 sentences before writing it; afterwards point out the 2–3
  most important lines. Give "📌 Interview note" boxes for Scale-relevant concepts and append each one
  to `docs/notes/interview-notes.md`.
- Leave about one `# TODO(najeeb): ...` per step (with a hint), stop, and review his code honestly
  without rewriting unless asked.
- Ask before: new dependencies, architecture changes, schema changes after agreement, deleting or
  renaming files/modules, anything irreversible. Don't ask about small implementation details.
- If the brief is wrong or unclear: stop and ask, never guess silently. Disagree openly when needed.
- Scope: current week only. Ideas for later go to `docs/ideas.md`.
- Honesty: never claim tests pass without running them; show real output; mark limitations in code/docs.
- Git: work on `main`; commit at the end of every step; message format `<area>: <what changed>`;
  never force-push or rewrite history; never commit secrets.
  Before every commit, `uv run python scripts/check_secrets.py` must exit 0 (it looks for the
  real values from `.env` in the staged changes); the commit must not run if it doesn't.

## Architecture summary
- **One grader for everything.** `grade(problem, code) -> GradeResult` is used by student submissions,
  model evals and the RL reward. Never create a second grading path.
- Product half: Next.js + Monaco (Wk 3) → FastAPI (Wk 3) → grader queue (**Postgres as the queue**:
  the submission row is the job, workers claim with `FOR UPDATE SKIP LOCKED` + a lease; no Redis,
  decided 2026-10-02) + DockerSandbox, AI tutor (Wk 4: own model client, RAG on pgvector,
  traces as Postgres rows; Langfuse optional, decided 2026-10-02), Postgres
  (local Docker in dev, Supabase when hosted) + pgvector (Wk 3).
- Week 3 steps: 0 dev environment → 1 schema + migrations + problem sync → 2 worker (queue) →
  3 API → 4 web UI → 5 end-to-end + docs. The worker grades once with `reveal_hidden=False` and
  stores only that (hidden details never reach DB rows the API reads); problem files stay the
  source of truth (synced into Postgres with version + content_hash).
- Week 4 steps: 0 guardrail → 1 course notes + RAG → 2 tutor pipeline + `hints` table (the
  trace) → 3 API + UI (hints, 👍/👎) → 4 offline tutor eval (buggy files as students, a model
  fixes, `grade()` scores) → 5 wrap-up. The tutor model never sees `solution.py`; every hint
  passes the guardrail (`tutor/guardrail.py`) or is replaced by a reference hint.
- Lab half: eval harness (Wk 2), simulated students + integrity + quality estimates (Wk 5),
  dataset builder + GRPO with TRL on Qwen 0.5–1.5B (Wk 6–7).
- Sandbox: behind a `Sandbox` protocol so backends swap. `SubprocessSandbox` = subprocess + rlimits
  (NOT secure; default, used by validator and `make all`). `DockerSandbox` (Step 5) = same runner in a
  container (no network, no host files, read-only, non-root, pids limit); required before strangers
  submit code. Containers share the kernel: gVisor/Firecracker at real scale.
- Principles: hidden tests protect the reward; everything is data (structured, versioned);
  problem IDs are stable forever and `version` is bumped when tests change; deterministic grading;
  flags inform humans and never auto-punish; swappable parts behind small interfaces.
- Runner (child) receives only test **inputs**, never expected outputs; the parent compares.

## Repository layout
- `problems/cs1/<NN_module>/<slug>/`: `problem.yaml`, `starter.py`, `solution.py`, `tests.yaml`, `buggy/*.py`
- `src/codetutor/problems/`: schema (pydantic) + loader
- `src/codetutor/grader/`: `runner.py` (child, stdlib only), `compare.py`, `sandbox.py`, `grader.py`, `models.py`
- `src/codetutor/bank/`: fill_expected, validator, dataset build (the logic behind `scripts/`)
- `src/codetutor/evals/`: `prompt.py`, `extract.py`, `passk.py`, `records.py`, `score.py`, `fake_models.py`, `clients.py`, `run.py`, `metrics.py`, `report.py`
- `src/codetutor/settings.py`: settings from the environment (`database_url()`, `database_url_for_tests()`, `DB_CONNECT_TIMEOUT_S`)
- `src/codetutor/db/`: `engine.py`, `models.py` (7 tables as `…Row` classes), `vector.py` (pgvector column type), `sync.py`, `users.py`, `migrations/` (Alembic; `alembic.ini` at the repo root)
- `src/codetutor/worker/`: `jobs.py` (the queue in SQL: enqueue, claim, save, release, load result), `loop.py` (`process_job`, `run_worker`)
- `src/codetutor/api/`: `app.py` (`create_app`, error handlers), `routes.py` (11 endpoints), `submissions.py` (submit + rate limits, `find_limit_hit`, `lock_user`), `hints.py` (hint requests, levels, rating), `schemas.py`, `deps.py` (session, `current_user`)
- `src/codetutor/tutor/`: `guardrail.py` (`check_hint`, `solution_lines`: does a hint leak code or the solution?), `notes.py` (`load_notes`, `sync_notes`), `rag.py` (`search`: keyword / vector / hybrid), `retrieval_eval.py`, `context.py` (`HintRequest`, what the model sees), `prompt.py` (pinned, `TUTOR_PROMPT_VERSION`), `service.py` (`give_hint`, `save_hint`), `safety.py` (the safety run), `jobs.py` (the hint queue: the `hints` row is the job), `loop.py` (`process_hint_job`, `run_tutor_worker`)
- `course/notes/`: 8 course notes (one per module, `##` sections = search chunks), the tutor's RAG source
- `src/codetutor/e2e.py`: end-to-end checks of a running stack over HTTP (`run_checks`); used by `scripts/e2e_check.py` and `tests/test_e2e.py`
- `compose.yaml`: local dev services (Postgres 17 + pgvector on 127.0.0.1:5432)
- `scripts/`: `validate_problems.py`, `fill_expected.py`, `grade_cli.py`, `build_dataset.py`, `bench_sandbox.py`, `try_model.py`, `check_secrets.py`, `run_eval.py`, `eval_report.py`, `sync_problems.py`, `worker.py`, `submit.py` (dev tool), `e2e_check.py`, `sync_notes.py`, `eval_retrieval.py`, `ask_tutor.py`, `tutor_safety.py`, `tutor_worker.py`
- `tests/`: pytest suite; `tests/submissions/` holds adversarial submissions; `tests/hints/` labelled hints for the guardrail
- `docs/`: `KICKOFF.md`, `ideas.md`, `problem-format.md`, `grader.md`, `evals.md`, `database.md`, `worker.md`, `api.md`, `tutor.md`, `notes/`
- `lab/tutor/`: `retrieval_questions.yaml` (40 labelled questions), `results/` (committed safety-run JSONL), `reports/` (generated `retrieval.md`, `tutor_safety.md`), `scratch/` (gitignored)
- `lab/evals/`: `configs/` (one YAML per official run), `results/` (committed JSONL + meta),
  `reports/` (generated `week2.md`), `scratch/` (gitignored)
- `web/`: Next.js 16 app (Week 3 Step 4; `app/` pages, `components/`, `components/HintPanel.tsx` (Week 4), `lib/` incl. `api.ts`, `poll.ts` (shared polling) + hand-written `types.ts`, `scripts/copy-monaco.mjs`, `scripts/e2e.mjs`; see web/README.md)
- `api/`, `tutor/`: READMEs pointing to `src/codetutor/api/` + docs/api.md and `src/codetutor/tutor/` + docs/tutor.md
- `dist/`: generated output (gitignored)

## Conventions
- Linux via **WSL2 (Ubuntu 24.04)**, Python 3.12 (project requires >=3.11), **uv** (`uv sync`, `uv run`).
- Week 1 dependencies are pre-approved: `pydantic` v2, `pyyaml`; dev: `pytest`, `pytest-timeout`, `ruff`.
  Week 3 approved (2026-10-02, added in the step that needs them): `psycopg[binary]` (Step 0, done),
  `sqlalchemy` 2 + `alembic` (Step 1, done), `fastapi` + `uvicorn`, dev `httpx` (Step 3); npm in `web/`
  only: `next`, `react`, `@monaco-editor/react`, `typescript` (Step 4; installed with their
  required companions `react-dom`, `monaco-editor`, `@types/react`, `@types/react-dom`,
  `@types/node` 24, approved in the Step 4 plan; exact versions, `package-lock.json`). Report the real package
  count when installing. Anything else: ask first.
- Type hints and short docstrings on all public functions/classes. ruff (line length 100).
- Small functions, clear names, no clever one-liners. `pathlib.Path`. Specific exceptions with helpful
  messages; no bare `except:` (the runner catching `BaseException` from student code is the one
  commented exception).
- No global mutable state unless unavoidable (comment why). Limits/timeouts live in one place and are overridable.
- Tests: real subprocess runs (no mocking the sandbox); whole suite < 60 s; `pytest-timeout` enabled.
- Make targets: `install`, `lint`, `format`, `test`, `validate`, `build`, `all` (= lint + test + validate),
  `db-up` / `db-down` / `db-reset` (local Postgres; `db-reset` deletes the data), `db-migrate`
  (`alembic upgrade head`), `db-sync` (migrate + copy the problems in), `notes-sync` (migrate +
  embed the course notes; needs Ollama with `nomic-embed-text`), `worker` (db-sync, then
  grade queued submissions in Docker until Ctrl+C), `tutor` (db-sync + notes-sync, then answer
  queued hint requests with the local 7B until Ctrl+C; needs Ollama) and `api` (db-sync, then the HTTP API on
  127.0.0.1:8000; start it after the workers, two syncs at once are not guarded),
  `web-install` (`npm ci` in web/), `web` (Next.js dev server on 127.0.0.1:3100; `WEB_PORT`
  overrides; port 3000 is taken by another dev server on this laptop) and `web-check` (type
  check + production build), `e2e` (end-to-end checks over HTTP against the running stack) and
  `web-e2e` (headless Chrome via the DevTools protocol; both need worker + tutor + api + web running,
  neither is in `make all`). `make all` stays Python-only. `test` and `test-docker` depend
  on `db-up`, so `make test` / `make all` need Docker running (since Week 3 Step 0).
  `test-docker` runs the hostile tests and the worker's Docker test (opt-in, marker `docker`,
  ~1 min; run it after any sandbox or worker change). Docker works without `sg` since the WSL restart on 2026-10-01.
  Marker `slow` (also deselected by default): the whole-bank validation test, because
  `make validate` in `make all` runs the same check (`uv run pytest -m slow` runs it).
- WSL uses **mirrored networking** (`C:\Users\ACER\.wslconfig`), so `localhost` reaches the
  Windows Ollama. Model calls need `uv run --env-file .env ...`. Bind local services to
  `127.0.0.1` (a plain port mapping could be reachable from the network).
- Database: `DATABASE_URL`, else the dev URL in `settings.py` (fixed dev credentials, local only,
  not a secret). Tests use their own DB `codetutor_test` (`TEST_DATABASE_URL`), dropped and
  re-created every run by the real migrations; they never read `DATABASE_URL`. Schema changes:
  `docs/database.md` §4 (autogenerate with `--rev-id 000N`, then review by hand). Node 24 LTS via nvm in `~/.nvm` (WSL; never the Windows `npm` under `/mnt/c`).

## 8-week plan
| Week | Deliverable |
|---|---|
| 1 | Problem bank (~33 CS1 problems) + grader + validator |
| 2 | Eval harness: 2–3 LLMs through the grader; pass@1, pass@k by module/difficulty; report |
| 3 | FastAPI + Postgres + queue + minimal Next.js UI |
| 4 | AI tutor: LiteLLM, RAG, hint-not-answer guardrail, Langfuse, hint ratings |
| 5 | Simulated students + integrity checks + difficulty/skill estimates |
| 6–7 | Dataset builder + GRPO on Qwen with grader reward + re-eval; optional DPO on hint ratings |
| 8 | Instructor dashboard, light early-warning model, README, diagram, demo video |
Safe cuts: dashboard polish, early warning, DPO. Never cut: grader, evals, GRPO.

Week 1 steps: 0 skeleton → 1 problem format (schema + loader + 3 examples) → 2 grader →
3 validator / fill_expected / CLI / dataset build → 4 full problem bank (one module per batch) →
5 optional Docker sandbox.

## Session rituals
- **Start:** read this file; run `git status`, `git log --oneline -10`, `make all`; report in 3 lines
  (where we are, what's next, blockers); wait for "go".
- **End:** everything committed; update Status / Decisions log / Open questions / Known limitations;
  commit `docs: update CLAUDE.md status`; give the 5-line summary
  (`Session YYYY-MM-DD: / Done: / Decisions: / Next: / Blockers/questions:`).

---

## Status
- **Done:** Step 0 (skeleton, tooling). Step 1 (schema, loader, 3 example problems with inputs only).
  Step 2 (grader: models, compare, runner, sandbox, grade/grade_many; 26 adversarial submissions;
  157 tests in ~11 s; docs/grader.md). Step 3 (`src/codetutor/bank/`: fill_expected, validator,
  dataset build with content_hash; scripts for each + grade CLI; 175 tests in ~11 s; 3/3 valid).
- **Done (2026-09-30):** Step 4. All 8 modules, **33 problems**, all valid, every problem has a
  hidden-only bug. Grader 0.2.0 adds the optional `check_input_unchanged` check (used by 4
  problems). Suite: 179 tests in ~27–29 s; `make all` ~42 s. Three problems have a timeout bug
  (is_prime, two_sum, fibonacci, ~2.2 s each per validate run).
- **Done (2026-10-01):** Week 1 wrap-up: README rewritten; `docs/notes/week1.md` skeleton (facts in
  HTML comments, Najeeb writes the text later, then says "review"); stale TODO comments removed.
  **Step 5 (optional) done:** `DockerSandbox` behind the `Sandbox` protocol, `make test-docker`
  (32 tests, 3/3 runs green, 53–66 s), `scripts/bench_sandbox.py` (Docker adds ~1 s per
  submission, ~12×). Default suite: 179 passed, 2 skipped, 1 xfailed, 32 deselected.
- **Done (2026-10-01): Week 2 Step 0 (Q13).** A CPU-limit kill (SIGXCPU) is `timeout` in both
  sandboxes; grader 0.2.1. Default suite: 187 passed, 2 skipped, 1 xfailed, 32 deselected
  (~25 s); `make test-docker` 32 passed (46–89 s).
- **Done (2026-10-01): Week 2 Step 1** (offline eval core, `src/codetutor/evals/`): prompt
  (PROMPT_VERSION 1, student view only, pinned by a test), code extraction, unbiased pass@k,
  EvalRecord + JSONL, `score_reply` (reply → extract → `grade()` → record), fake models (oracle,
  starter, buggy, chatty). 46 new tests; suite 233 passed, 2 skipped, 1 xfailed (~31 s).
- **Done (2026-10-01): Week 2 Step 2, code part** (`evals/clients.py`: one stdlib client for
  Ollama + Gemini via the OpenAI chat-completions format; retry/fail-fast/stop error classes;
  throttle; `make_client`; `scripts/try_model.py`; `docs/evals.md`; 21 tests against a local fake
  server, 1.5 s). **Live check:** Gemini done (`gemini-2.5-flash` solved fizzbuzz, accepted in
  Docker); Qwen fp16 on the GPU accepted fizzbuzz, compress and valid_parentheses after the
  NVIDIA driver update (546.18 → 617.14). Results table in `docs/evals.md` §5. Also added
  `scripts/check_secrets.py` (6 tests) and `ModelReply.total_tokens`. **Step 2 done.**
- **Done (2026-10-01): Week 2 Step 3** (run harness `evals/run.py` + `scripts/run_eval.py`, 10
  tests; suite 270 passed). **Official Qwen run complete**: 330/330 answers, Docker grading, no
  failed calls; pass@1 0.867, pass@5 0.983, pass@10 1.000 (accepted 286, wrong_answer 36,
  runtime_error 6, compile_error 2). Weakest: group_anagrams 2/10, word_frequency 2/10,
  letter_grade 3/10, max_of_three 4/10. Reproducibility check: 4/4 re-run seeded answers
  byte-identical with the same grades. **Gemini (n = 1) still to run**: quota resets 10:00 Qatar
  time; 20 answers on day 1, 13 on day 2.
- **Done (2026-10-01): Week 2 Step 4** (`evals/metrics.py`, `evals/report.py`,
  `scripts/eval_report.py`, 17 tests): `lab/evals/reports/week2.md` (deterministic). Qwen:
  pass@1 0.867 [0.779, 0.942], pass@5 0.983, pass@10 1.000, mean reward 0.953, 15 of 44 wrong
  answers hidden-only; Conditions 0.63 and Dictionaries 0.58 weakest (0.62 before the Q15
  rounding fix).
- **Done (2026-10-01): Week 2 Step 4b** (official comparison run, Najeeb chose the local 7B):
  `qwen2.5-coder-7b-q4.yaml` (same settings as the 1.5B; only the model changes). 330/330 in
  ~15 min, 0 failed calls: pass@1 0.945 [0.867, 1.000], pass@5 0.978, pass@10 1.000, mean
  reward 0.989, 9 of 18 wrong answers hidden-only. Weak: word_frequency 1/10, group_anagrams
  2/10 (all 8 failures sort in the wrong order, on the *visible* example). Re-asked 3 seeded
  answers: byte-identical. Report regenerated with both models; the official-numbers test pins both.
- **Done (2026-10-02): finish_reason fix.** An HTTP 200 reply with `finish_reason: "error"` is
  now retried like a 503 and ends as `ModelError` (never graded). Test first: 2 new client
  tests failed before the fix. Suite 290 passed, 2 skipped, 1 xfailed (~41 s); `make all` ~61 s.
- **Done (2026-10-02): Q11 part 1, fast YAML parser.** The loader uses libyaml (`CSafeLoader`,
  pure-Python fallback): `load_all()` 0.59 s → 0.10 s; a differential test checks both parsers
  read every bank file the same. Suite 291 passed, 2 skipped, 1 xfailed (28.6 s); `make all`
  45 s (most of the drop from 61–65 s is run-to-run noise; the measured gain is ~2 s).
- **Done (2026-10-02): Q15 report rounding.** One helper `_fixed` in `report.py` (cut float
  noise at 12 decimals, then round half up with `decimal`) formats every computed number.
  week2.md regenerated: only 7 tie cells changed, no headline number. Suite 301 passed,
  2 skipped, 1 xfailed (28.9 s); `make all` 42 s.
- **Done (2026-10-02): Week 2 Step 5 (wrap-up).** `docs/notes/week2.md` skeleton (7 sections,
  checked facts in comment boxes, numbers table filled; Najeeb writes the text, then "review").
  README: status Weeks 1–2 done, test numbers, new "Evaluate a model" section (results table +
  commands, all run as written today, incl. a live Qwen call), layout, roadmap. `lab/README.md`
  was already current. `make all`: 301 passed (30.7 s), 33 valid, 48 s.
- **Done (2026-10-02): Week 3 Step 0** (dev environment). `compose.yaml`: `pgvector/pgvector:pg17`
  (Postgres 17.11, pinned by digest ac08538c…) on 127.0.0.1:5432, healthy in ~3 s;
  `settings.database_url()`; Make `db-up`/`db-down`/`db-reset`, `test` depends on `db-up`;
  `psycopg[binary]` 3.3.6 (2 packages, 14 → 16); `tests/test_db_smoke.py` (2 tests). nvm v0.40.8
  + Node v24.21.0 / npm 11.19.0 in WSL. Suite 303 passed, 2 skipped, 1 xfailed (34 s);
  `make all` 53 s (incl. starting the DB).
- **Done (2026-10-02): Week 3 Step 1** (schema + migrations + problem sync). `sqlalchemy` 2.1.2 +
  `alembic` 1.20.0 (+ Mako, MarkupSafe: 4 packages, 16 → 20). `src/codetutor/db/`: 5 tables
  (`users`, `problem_versions` = sealed full copies, `problems` = current student view,
  `submissions` = job + result, `test_results`), migration `0001_initial_schema` (autogenerated,
  reviewed by hand), `sync.py` + `scripts/sync_problems.py`, `make db-migrate` / `db-sync`
  (dev DB: 33 added, then 33 unchanged), `docs/database.md`, 2 interview notes. 45 new tests
  (`test_db_schema.py` 36, `test_db_sync.py` 9; ~4 s): migration round trip, drift check,
  every CHECK, every status, json vs jsonb, whole-bank round trip. Suite 348 passed, 2 skipped,
  1 xfailed (41.2 s); `make all` 62 s.
- **Done (2026-10-02): Week 3 Step 2** (worker). `src/codetutor/worker/`: `jobs.py` (claim SQL
  with `FOR UPDATE SKIP LOCKED`, 5 min lease, `attempts` as fencing token, 3 attempts, NUL
  cleanup, `enqueue_submission`, `load_grade_result`) and `loop.py` (`process_job`,
  `run_worker`: poll 1 s, 2 s pause after an error, stop after 5 errors in a row, graceful
  stop); migration `0002_claim_index` (partial index on queued/running); `scripts/worker.py`
  (always Docker), `scripts/submit.py`; `make worker`; `docs/worker.md`; interview note. 20 new
  tests + 1 docker test. Live: fizzbuzz solution accepted 10/10, buggy wrong_answer 6/10 (~1.0 s
  per job in Docker); SIGINT during an is_prime grading → job saved, then the worker exited.
  EXPLAIN with 50 008 rows: index scan on `ix_submissions_claimable` (16 kB vs 1 112 kB pk).
  Suite 368 passed, 2 skipped, 1 xfailed (43.5 s); `make all` 64 s; `make test-docker` 33
  passed (56 s).
- **Done (2026-10-02): Week 3 Step 3** (API). `fastapi` 0.142.2 + `uvicorn` 0.54.0, dev `httpx`
  0.28.1 (12 packages, 20 → 32). `src/codetutor/api/`: 7 endpoints, dev login via `X-User-Id`,
  rate limits (3 waiting + 10 per 60 s, counted in Postgres under a user-row lock), 409 when the
  problem version changed, own 422 handler; migration `0003` (index on `submissions (user_id,
  created_at)`); `db/users.py`; `make api`; `docs/api.md`; 2 interview notes. 40 new tests
  (~6.5 s). Race test: 10/10 green with the lock; without it 12 of 12 got in (limit 5, 3/3 runs).
  Found by a test: FastAPI's default 422 echoed a lone surrogate and crashed (500). Live (worker
  in Docker + uvicorn + curl): submit 0.05 s, result 1.1 s later; buggy fizzbuzz 6/10 with the
  4 hidden failures unrevealed; 404 for another user; 409; 429 with Retry-After 2 (waiting) and
  51 (window); DB stopped → 503 after 5.0 s, back → 200. EXPLAIN on 50 000 rolled-back rows:
  index-only scan, 0.6 ms. Suite 408 passed, 2 skipped, 1 xfailed (55.5–58.7 s; the machine was
  ~25% slower than in the morning: the same 368 tests took 49.6 s vs 39.5 s, see Q11);
  `make all` 72–75 s; `make test-docker` 33 passed (57 s).
- **Done (2026-10-02): Week 3 Step 4** (web UI). `web/`: Next.js 16.3.8, React 19.3, Monaco
  (`@monaco-editor/react` 4.7.0 + `monaco-editor` 0.57.0), TypeScript 7.0.2; 36 npm packages
  (node_modules 475 MB; Monaco copy 25 MB, gitignored). Problem list + problem page (server
  components), login box, editor, submit + 1 s polling, result table, my submissions, drafts
  (client). API change: Python `repr` display text (`args_repr`/`expected_repr`/`actual_repr`)
  because `JSON.parse("32.0")` is 32; 3 new tests. `make web-install`/`web`/`web-check`.
  Checked: curl on server-rendered pages (33 problems, celsius shows `32.0`, no hints/solution/
  hidden ids in the HTML), the API flow through the `/api` rewrite, screenshots, and a scripted
  headless-Chrome run over the DevTools protocol (login, Accepted 10/10, buggy 6/10 with 4
  hidden failures without details, the "3 waiting" 429, draft kept after reload, logout, no
  console errors; 2.3 s click → result). Suite 411 passed, 2 skipped, 1 xfailed (47.9 s);
  `make all` 63 s; `make web-check` 4 s. **Najeeb's own click-through is still to do.**
- **Done (2026-10-02): Week 3 Step 5 = Week 3 done** (end-to-end + docs). `src/codetutor/e2e.py`
  (9 checks over HTTP, stops at the first failure with a hint), `tests/test_e2e.py` (real uvicorn
  + real worker loop in threads; a no-worker run must fail with "is `make worker` running?"),
  `make e2e` (live: 9/9, 7.9 s; with the worker stopped: fails after 5 s with that message),
  `make web-e2e` (8 browser checks, 17.4 s after two WSL fixes, was 47.5 s; the failure path
  saves a screenshot and cleans up). README (Run the app, architecture as built, numbers; every
  command run as written; the `ollama pull` line was wrong for WSL since Week 2, fixed),
  `docs/notes/week3.md` skeleton, 1 interview note. Suite 414 passed, 2 skipped, 1 xfailed:
  **57–65 s on 2026-10-02 evening (over the 60 s limit on one run; see Q11)**; `make web-check` 6 s.
- **Done (2026-10-02): Q11 resolved (option C).** `test_every_problem_in_the_bank_is_valid` is
  marker `slow` (deselected by default; `make validate` in `make all` runs the same check). Suite
  413 passed, 2 skipped, 1 xfailed, 34 deselected: **35.8–38.0 s** on three runs (was
  47.9–64.8 s); `make all` 47.8–50.4 s, 33 valid. The slow test alone: 10.35 s, passes.
- **Done (2026-10-03): Week 4 Step 0** (hint guardrail). `src/codetutor/tutor/guardrail.py`:
  `check_hint` (rules `solution_line`, `code_block`, `code_statement`; text in the starter,
  description or the student's own code is allowed) and `solution_lines` (now also used by
  `e2e.forbidden_texts`). `tests/test_guardrail.py` (53 tests, 0.45 s) +
  `tests/hints/guardrail_cases.yaml` (24 labelled hints). Measured: 0 of 66 bank hints 1–2
  blocked; 9 of 33 hint 3s blocked (pinned); 298/298 generated leaks and 10/10 hand-written leaks
  blocked; 1 accepted false alarm; 3 known misses written down. `docs/tutor.md` §1, 1 interview
  note, 2 ideas. Suite 466 passed, 2 skipped, 1 xfailed, 34 deselected: **57.1 and 69.9 s on
  battery power** (the same 413 old tests: 53.3 s on battery vs 35.8–38.0 s on mains the evening
  before); `make e2e` live 9/9 (9.1 s).
- **Done (2026-10-03): Week 4 Step 1** (course notes + search). 8 notes in `course/notes/`
  (41 sections, checked: one per module, 40-350 words per section, examples parse, no bank
  solution line). Migration 0004 (`CREATE EXTENSION vector`, pgvector 0.8.7; `note_chunks` with
  `embedding vector(768)`), own `Vector` type (`db/vector.py`, no new package). `EmbeddingClient`
  + `make_embedder` in `evals/clients.py` (shares ChatClient's HTTP/retry code; its 21 tests
  unchanged). `nomic-embed-text` v1.5 pulled (274 MB). `make notes-sync`: 41 sections in 3.0 s,
  second run 41 unchanged. `rag.py` (keyword ~20 ms, vector ~120-155 ms, hybrid ~160-175 ms per
  question). Retrieval eval on 40 labelled questions (`lab/tutor/reports/retrieval.md`,
  byte-identical across runs): recall@3 keyword 34/40, vector 39/40, **hybrid 40/40** (chosen
  for Step 2); recall@1 vector 35/40 > hybrid 33/40. 35 new tests (~4 s). Suite 501 passed,
  2 skipped, 1 xfailed, 34 deselected (50.7 s on battery); `make all` 68.3 s. **Najeeb: review
  the notes** (optionally add questions of his own).
- **Done (2026-10-03, committed 2026-10-05): Week 4 Step 2** (tutor pipeline). `context.py`
  (`HintRequest`: student side only, hidden tests as counts, refuses a revealing result),
  `prompt.py` (`TUTOR_PROMPT_VERSION = "1"`, pinned), `service.py` (`give_hint`: hybrid top 3 →
  model → guardrail + empty/80-word checks → 1 retry → reference hint; level 3 = reference, no
  model; `save_hint`), migration 0005 (`hints` = the trace, every attempt kept),
  `scripts/ask_tutor.py`, safety run (`safety.py`, `scripts/tutor_safety.py`,
  `lab/tutor/reports/tutor_safety.md`): 97 buggy-code situations per level + 10 injections;
  first try blocked 7B 3% / 10% (L1 / L2), 1.5B 49% / 29%; reference shown 7B 3% / 1%;
  injections 7B 0/10 blocked. **Default model: 7B.** Live 2026-10-05: fizzbuzz L1 good hint but
  109 s (cold model after reboot), L2 warm 5.0 s (retry shown; says "the student's code", not
  "you"). Suite 536 passed, 2 skipped, 1 xfailed (34.9 s); `make all` 55 s.
- **Done (2026-10-05): Week 4 Step 3a** (hint backend). Migration 0006 (`hints` row = the
  tutor's job: `job_status`, `claims` fencing token, lease; result columns nullable until done;
  4 CHECKs; claim index), `tutor/jobs.py` + `tutor/loop.py` (`make tutor`: loads the 7B and
  the embedder at start, refreshes them every 4 min with keep_alive 10m), `api/hints.py` + 4
  endpoints (POST 202, GET one, GET list, PUT rating), levels in order (409), 1 waiting hint +
  10 per 10 min per user (429), only 12 safe fields leave the API. Live (real 7B, buggy
  fizzbuzz): L1 3.8 s, L2 5.7 s (retry shown), L3 0.8 s, 429/409/404 as planned, ratings
  stored, heartbeat moved both expiries +10 min, Ctrl+C clean. Model reload after Ollama's
  unload: 12.0 / 13.3 s. Suite 589 passed, 2 skipped, 1 xfailed (42.3 s); `make all` 56 s;
  `make test-docker` 33 passed (41 s).
- **Done (2026-10-05): Week 4 Step 3b = Step 3 done** (web UI + e2e + docs).
  `web/components/HintPanel.tsx` (question, level 1 → 2 → last hint with a confirm, 👍/👎,
  "from the AI tutor" / "from your teacher", waiting text + 10 s "can take up to 2 minutes",
  follows a waiting request after reload), `lib/poll.ts` (`pollUntilFinished`, now also used by
  `Workspace.tsx`), `components/InlineCode.tsx`. `e2e.py` + 2 steps (hint about the buggy
  submission: 12 fields, no solution line; rate it), `test_e2e.py` runs the tutor loop with a
  fake model (+1 test: no tutor → "is `make tutor` running?"), `e2e.mjs` + 1 step (ask + 👍;
  reload keeps the rated hint; logout hides hints). Live: `make e2e` 11/11 (19 s, hint 5.5 s),
  `make web-e2e` 9/9 (27 s, hint + 👍 2.8 s); screenshots light + dark checked. Docs: api.md,
  tutor.md §4, database.md, README (Run the app: 4 terminals; diagram), web/README.md; 1
  interview note. Once, `make web` failed with EADDRINUSE on 3100 though nothing listened
  (not a Windows-reserved range); the retry worked.
  Suite: 590 passed, 2 skipped, 1 xfailed, **70.4 and 83.9 s on battery** (status 1, 87%,
  Epic Games launcher running); the same suite minus 1 test was 42.3 s on mains an hour before.
  Re-measure on mains. `make web-check` OK.
- **Open:** Najeeb's TODO `fizzbuzz/buggy/stops_before_n.py`; `docs/notes/week3.md`, `week2.md` text;
  `docs/notes/week1.md` text (its
  numbers table is from grader 0.2.0 / 179 tests: re-check at review); Q14 (rare memory-bomb
  flake, recommendation A: leave it).
- **Check questions waiting for Najeeb** (he answers them at the end; answers are not written here):
  Module 3: Q1 why `while n != 0: n //= 10` never stops for -5; Q2 why factorial's big test is
  n = 1100, not 900; Q3 what a student sees when fizzbuzz checks % 3 before % 15.
  Module 4: Q1 what `"a  b".split(" ")` returns; Q2 why compress appends after the loop;
  Q3 what a student sees when count_vowels forgets `.lower()`.
  Module 5: Q1 why `mutates_input` passes `[1, 2, 3]` but fails `[3, 1, 3, 2, 1]`; Q2 why the
  input check is off by default; Q3 what rotate_right without `% len(nums)` gives for ([1,2,3], 4).
  Module 6: Q1 why is_prime can stop at `divisor * divisor <= n`; Q2 which input shows the
  `divisor * divisor < n` bug; Q3 what reward 0.93 for the slow is_prime means for RL.
  Module 7: Q1 why the anagram key is `"".join(sorted(word))`, not `sorted(word)`; Q2 why
  `if seen.get(need):` fails for ([2, 7, 11, 15], 9); Q3 why two_sum checks `need in seen`
  before adding the current number.
  Module 8: Q1 what goes wrong in `def flatten(nested, result=[])`; Q2 why naive fibonacci
  passes n = 25 but times out at n = 40; Q3 why counting brackets can't decide "([)]".
  Q12 fix: Q1 why not accept `timeout` as a pass in the memory-bomb test; Q2 what happens if the
  memory limit stops working. README: Q1 why the CLI example grades a buggy file; Q2 why no
  timing numbers; Q3 what protects your files when grading downloaded code. week1.md: Q1 why every
  decision needs a cost; Q2 why the 60-second section has no facts. Stale comments: Q1 why a stale
  comment is worse than none; Q2 why the Makefile fallback was left. Step 5: Q1 why `docker kill`
  and not only killing the client; Q2 why `--init`; Q3 what a strict xfail does if it passes.
  Week 2 Step 0: Q1 why `cpu_threads.py` uses hashlib; Q2 why bump the grader version when no
  reward changed; Q3 why not raise the memory-bomb timer to 10 s. Week 2 Step 1: Q1 the
  extractor's pick for a reply with a solution block then a `print(...)` block; Q2 pass@2 for
  n = 4, c = 1; Q3 why `build_messages` takes a StudentProblem. Week 2 Step 2: Q1 what the
  client does on a 401; Q2 why jitter; Q3 why a failed API call is never graded. Week 2 Step 3:
  Q1 why model calls go one at a time; Q2 what a rerun after a quota stop does; Q3 what
  pass@10 = 1.0 vs pass@1 = 0.867 means for GRPO. Week 2 Step 4: Q1 mean reward 0.953 vs
  pass@1 0.867; Q2 what a hidden-only failure is; Q3 a new prompt at 0.89 vs the interval
  0.78–0.94. Week 2 Step 4b: Q1 why the 7B's pass@5 is below the 1.5B's; Q2 the honest
  sentence about 7B (4-bit) vs 1.5B (fp16); Q3 Dictionaries 0.58 vs 0.57. finish_reason fix:
  Q1 what the client does with a 200 + `finish_reason: "length"` half answer; Q2 why the fix
  raises `_Transient`, not `ModelError`; Q3 measured pass@1 if 10% of calls failed this way.
  YAML parser: Q1 why the differential test compares `repr`, not `==`; Q2 why fill_expected's
  round-trip check uses `parse_yaml`; Q3 why 0.59 s → 0.10 s saves only ~2 s per suite.
  Q15 rounding: Q1 what `f"{0.625:.2f}"` prints; Q2 why cut at 12 decimals before rounding
  half up; Q3 why 7 cells changed but no headline number. Week 2 wrap-up: Q1 why the README
  names "4-bit" next to the 7B; Q2 why week2.md gives raw facts, not finished text; Q3 what
  happens to hidden-only wrong answers in a bank without hidden tests. Week 3 Step 0: Q1 why
  the port is `127.0.0.1:5432:5432`; Q2 why the dev password may be in compose.yaml but the
  Gemini key never; Q3 why pin the image by digest. Week 3 Step 1: Q1 why `problems` holds only
  the student view and hidden tests live in `problem_versions`; Q2 why `json`, not `jsonb`;
  Q3 what `make db-sync` does after a hint typo fix without a version bump. Week 3 Step 2: Q1 what
  `SKIP LOCKED` adds to `FOR UPDATE`; Q2 what happens to a late save after a lost lease; Q3 why
  the worker stops after 5 errors in a row. Week 3 Step 3: Q1 why submit answers 202 and the
  UI polls; Q2 what the user-row lock does to two submits at 9 of 10; Q3 why another user's
  submission is a 404, not a 403. Week 3 Step 4: Q1 why the API sends `expected_repr: "32.0"`;
  Q2 why Monaco is copied into `public/` instead of loaded from the CDN; Q3 what goes wrong
  with `setInterval` polling when the API is slow. Week 3 Step 5: Q1 why test_e2e.py starts a
  real uvicorn server instead of using TestClient; Q2 why a test that expects the check to
  fail is useful; Q3 the two causes of `make web-e2e` taking 47 s. Q11 slow marker: Q1 which
  command still catches a bank problem whose solution fails its own tests; Q2 what
  `uv run pytest -m docker` runs when addopts says `-m 'not docker and not slow'`. Week 4
  Step 0: Q1 why `number % 15 == 0` is allowed but `count += 1` in backticks is blocked; Q2 why
  hints are checked against solution.py although the model never sees it; Q3 why "anything that
  parses as Python is code" was rejected. Week 4 Step 1: Q1 why keyword search missed "how do
  I add up numbers in a loop"; Q2 why vector search refuses notes embedded by another model;
  Q3 the honest reading of hybrid 40/40 vs vector 39/40. Week 4 Step 2: Q1 why prompts stay
  under 2,048 tokens; Q2 why the retry says only "it contains code"; Q3 why the API may return
  only `text` from a hints row. Week 4 Step 3a: Q1 why the tutor worker makes the hint, not the
  API; Q2 what `JSON(none_as_null=True)` fixed; Q3 what is in GPU memory 15 min after the
  tutor worker stops.
  Week 4 Step 3b: Q1 why the panel sends `submission_id` only when the editor code equals the
  shown submission's; Q2 why test_e2e.py uses a fake model; Q3 what a reload does while the
  tutor is thinking.
  (95 in total; answer key in Claude's memory.)
- **Next action:** Week 4 Step 4 (offline tutor eval: buggy files as students, a model fixes
  them after the hint, `grade()` scores) in plan mode. Najeeb: review the 8 notes in `course/notes/`. Also
  for Najeeb: the UI click-through (README "Run the app") and his text in `docs/notes/week3.md`
  ("review" when ready). Still open for Najeeb: his text in `docs/notes/week2.md` and
  `docs/notes/week1.md` ("review" when ready); Gemini n = 1 keep or drop (after 10:00 Qatar
  time, `uv run --env-file .env python scripts/run_eval.py lab/evals/configs/gemini-2.5-flash.yaml`,
  2 days; then add a README row).

## Decisions log
- 2026-09-28: Develop on WSL2 (Ubuntu 24.04) with Python 3.12, because the Week 1 sandbox needs POSIX features (setrlimit, setsid, killpg).
- 2026-09-28: Use uv with a committed `uv.lock` file, because it gives fast, reproducible installs (everyone gets the exact same package versions).
- 2026-09-28: Store problems as one folder per problem (not one JSON file), because code inside JSON strings is hard to read, review and diff.
- 2026-09-28: Use hatchling as the build backend (a build-time tool only, not a runtime dependency), because it is uv's default and supports the src layout.
- 2026-09-28: Added a one-line smoke test so `make test` really passes (pytest exits with code 5 when it collects no tests).
- 2026-09-28: Every step starts in plan mode, at Najeeb's request.
- 2026-09-28: Test `hidden` and `compare` fields are required (no defaults), so forgetting one can never silently make a hidden test visible.
- 2026-09-28: All schema models use `extra="forbid"` (typos are errors) and `frozen=True` (loaded problems can't be changed by accident; note frozen is shallow).
- 2026-09-28: "Expected missing" is tracked with pydantic's `model_fields_set`, not with None, because None/null is a real expected value for some problems.
- 2026-09-28: The student view excludes hints as well as the solution, buggy code and hidden tests. The tutor gives hints one at a time, and evals give models the student view.
- 2026-09-28: The problem id must match the folder path (`cs1/03_loops/x` ↔ `cs1.loops.x`, module 3). Resolves Q10.
- 2026-09-28: Example problems keep inputs only in tests.yaml until fill_expected.py (Step 3); tests load them with `require_expected=False`.
- 2026-09-28: The default problems root is found from the package location, not the current directory. This only works for source/editable installs, which is fine for this project.
- 2026-09-28: Najeeb chose to have Claude write the Step 1 TODO (`_check_id_matches_folder`) and study it instead. Keep offering TODOs in later steps.
- 2026-09-28: Q3 resolved. The total time limit is automatic (n_tests × per_test + 3 s), so per-test timeouts can't add up to a total timeout; a total timeout or crash still gives reward 0 (brief's rule). Chosen over streaming per-test results because it is simpler.
- 2026-09-28: Q6 resolved. No RLIMIT_NPROC (it is per-user: 25 processes already running). Rely on killing the process group; Docker `--pids-limit` later.
- 2026-09-28: The child runs with `python -S -s -P` and env `{PYTHONHASHSEED: 0}`, not `-I`. Checked by running it: `-I` ignores PYTHONHASHSEED, so set order changes between runs.
- 2026-09-28: The runner sets its own rlimits instead of `preexec_fn` (preexec_fn is unsafe when the parent uses threads, and grade_many uses threads).
- 2026-09-28: Exact mode treats int and float as different (30.0 ≠ 30), as well as bool and int. Float answers use float mode.
- 2026-09-28: Bad return types (set, NaN, objects) become wrong_answer with an explanation, never a repr string (a repr could equal an expected string).
- 2026-09-28: Print output is captured per test. With reveal_hidden=False, hidden-test output is dropped and hidden-test errors are shortened to the exception type (side-channel leaks of hidden inputs).
- 2026-09-28: The parent reads child output with size caps (32 MB stdout); student code can bypass print capture with os.write(1, ...).
- 2026-09-28: compile_error / crashed / total timeout return `tests=[]`. The added `GradeResult.error` field gives the reason for crashed/timeout; `TestResult.revealed` says whether details are present.
- 2026-09-28: `execute()` is public in grader.py, so fill_expected.py (Step 3) uses the same execution path as grade().
- 2026-09-28: Najeeb asked Claude to write the Step 2 TODO (`_unordered_equal`) too. Keep offering TODOs, but make them small, and explain the idea simply first.
- 2026-09-28: Najeeb asked for simpler explanations and multiple-choice check questions. Use short sentences, everyday analogies (e.g. "teacher room / exam room" for parent/child), and give check questions as A/B/C/D options in text.
- 2026-09-28: Najeeb asked for real-life scenarios for hard ideas. Each analogy comes with the real term and where it breaks down, so it works in interviews and doesn't teach anything wrong.
- 2026-09-28: Exclude `docs/` and `tests/submissions/` from ruff. Ruff 0.16 formats code blocks inside Markdown (which would change KICKOFF.md), and the submissions folder holds deliberately broken code.
- 2026-09-29: Step 3 logic lives in `src/codetutor/bank/` (expected, validate, build); `scripts/` are thin wrappers, so tests call the logic directly.
- 2026-09-29: Q9 resolved. `fill_expected.py` fully regenerates `tests.yaml` (one flow-style line per test, all strings quoted); no `#` comments, explanations go in `note`. No ruamel.yaml. The new text is parsed and checked before the file is written.
- 2026-09-29: `content_hash` = sha256 over a fixed file list (problem.yaml, tests.yaml, starter.py, solution.py, buggy/*.py), each as name + length + bytes. It is in both jsonl files. dist output is deterministic (`sort_keys=True`).
- 2026-09-29: Najeeb asked Claude to write the Step 3 TODO (`content_hash`) too.
- 2026-09-29: Q8 resolved. fibonacci hidden n = 40, not 35: naive fib(35) takes 0.87 s here (it would pass); fib(40) is about 10 s, so it always times out. Other fib tests use n <= 25.
- 2026-09-29: Q7 resolved. merge_sorted has no timing test: `sorted(a+b)` (C) beats a correct Python merge, and `pop(0)`-style O(n²) is fast C memmove. The spec asks for no sort() and honestly says it is not checked. AST check idea is in docs/ideas.md.
- 2026-09-29: two_sum's large hidden test is `[1]*19998 + [2, 3]`, target 5: the only answer is at the end, naive takes ~7 s, and the file stays ~60 KB (no generated-input feature needed).
- 2026-09-29: average_of_three tests avoid averages ending exactly in .xx5 (float round() can go either way there).
- 2026-09-29: Najeeb skipped the Module 2 check questions and the `one_direction_inequality` TODO; triangle_type keeps 3 buggy files.
- 2026-09-29: No buggy file that times out, except in problems where speed is the lesson (is_prime, two_sum, fibonacci). A timeout costs 2 s per test on every validate run, and `make all` validates twice.
- 2026-09-29: factorial allows n <= 1100 and tests 1100 (hidden). Measured: recursion fails above Python's limit of 1000; 1100! has 2870 digits, safely under Python's 4300-digit int↔str limit (JSON and YAML both hit it). It tests a stated constraint, not a hidden trick.
- 2026-09-29: count_digits hides 999999999999999 (15 nines): `int(math.log10(n)) + 1` returns 16 there (measured), because the float log10 rounds up to 15.0.
- 2026-09-29: fizzbuzz has no multiple of 15 in the visible tests, so the classic "check % 3 first" bug is hidden-only. The rule for 15 is stated in the description, and hint 1 points at it.
- 2026-09-29: Najeeb answers check questions at the end, not at each STOP. Keep collecting them (Status lists the open ones). Only one open TODO at a time, so Module 4 added no new TODO.
- 2026-09-29: String problems use ASCII-only test data, and the descriptions say so: `isalnum()`/`lower()` also accept letters like "é" or Arabic digits, and the spec should not have hidden surprises.
- 2026-09-29: Q10 resolved (B, Najeeb's choice). New optional problem field `check_input_unchanged` (default false; also in the student view). The runner reports `input_changed` (args vs the job's untouched copy, compared with `==`; any error while comparing counts as changed); the parent turns it into `wrong_answer` "your function changed its input; build and return a new list instead" only when the problem sets the flag. The message contains no input, so hidden tests show it too. GRADER_VERSION 0.1.0 → 0.2.0.
- 2026-09-29: The input check is on for remove_duplicates and second_largest only (their specs state the rule). second_largest bumped to version 2 because its grading changed. merge_sorted and rotate_right don't state the rule, so it stays off there.
- 2026-09-29: rotate_right allows k up to 10^9 and hides k = 10^9 (a one-step-at-a-time loop times out; no buggy file for it, so no suite cost). Found while testing: without `k % len(nums)` the code is still right while k < 2 × len, because negative slice indexes count from the end; t09 (k = 10, len 4) catches it.

- 2026-09-30: is_prime has the first buggy file that times out (`naive_linear`, only on hidden 1000000007). Measured: the √n solution takes 4.6 ms there, the naive loop ~40 s. Only one test is slow, so validating is_prime costs ~2.2 s per run.
- 2026-09-30: gcd inputs are capped at 10^6 on purpose, so a brute-force gcd still passes (33 ms measured): the brief doesn't ask gcd to test speed.
- 2026-09-30: running_total turns on `check_input_unchanged` (its spec says "return a new list"): side effects are a core "functions" idea. `sums_in_place` returns the right numbers but changes nums.
- 2026-09-30: Slow-but-correct is_prime scores 0.93 (13/14) under partial credit. Recorded in docs/ideas.md for Week 6 (weight efficiency tests or reward only full passes; measure first).

- 2026-09-30: The grader compares dicts by keys as a set (`actual.keys() == expected.keys()`), so word_frequency's key order doesn't matter, and the spec says so.
- 2026-09-30: two_sum's visible answers never use index 0, so the `if seen.get(need):` truthiness bug is hidden-only; 4 hidden tests have index 0 in the answer. The big test line (~60 KB) was generated by a script, not typed.
- 2026-09-30: group_anagrams uses a plain `result.sort()`: lists compare by first item, and two groups never start with the same word. It uses exact compare because the spec fixes the order.

- 2026-09-30: fibonacci allows 0 <= n <= 40 and tests 40 once (hidden). Measured again: naive fib(25) 11 ms (passes), naive fib(40) 10–18 s (always times out), loop fib(40) 8 µs.
- 2026-09-30: recursive_sum turns on `check_input_unchanged` (`nums.pop()` recursion gives the right sum but empties the list); lists have at most 500 numbers so recursion depth stays far below 1000.
- 2026-09-30: flatten's `mutable_default_list` is caught only because the runner runs all tests in one process (test 2 sees test 1's numbers). If grading ever moves to one process per test, this bug would pass. Interview note added.
- 2026-09-30: valid_parentheses keeps "([)]" hidden on purpose: the ordering rule is stated in words, so `counts_only` is a hidden-only bug. Its 3 buggy files are all hidden-only.
- 2026-09-30: binary_search says "a simple scan also passes (not checked)": at these sizes timing can't tell binary search from a scan (same honesty rule as Q7).
- 2026-09-30: Q12 resolved (Najeeb: "fix q12"). The growing memory bomb raced the 0.5 s per-test timer: filling 256 MB took median 186 ms but up to 503 ms (4/320 tests ≥ 450 ms, 4 gradings in parallel). The memory-bomb tests now use `MEMORY_TEST` (2 s per test; max seen 303 ms). The assertion is unchanged, so a broken memory limit would still fail the test (timeout). Rejected: accepting `timeout` (hides a broken limit) and a smaller memory limit (too close to Python's startup memory). After the fix: 25/25 runs alone and 2/2 `make all` green.

- 2026-10-01: Step 5 started on Najeeb's "start with the next step". `DockerSandbox` lives in `sandbox.py`, behind the same `Sandbox` protocol; both backends share one helper (`_run_captured`) for pipes, timeouts and kills. `grade()` is unchanged; `grade_many()` and `grade_cli.py` gained an optional `sandbox`.
- 2026-10-01: Docker is called through the `docker` CLI with `subprocess`, not the Docker SDK (no new Python dependency). Image `python:3.12-slim` pinned by digest (sha256:f77ac9e4…), so every run grades with the same Python (3.12.14; host 3.12.3).
- 2026-10-01: Measured container start-up: median 0.73 s, max 1.2 s with 4 in parallel. The wall-clock limit gets +5 s (`DOCKER_START_MARGIN_S`) so students never pay for start-up.
- 2026-10-01: `--init` is required. Measured without it: the runner is PID 1, Linux ignores its SIGXCPU (no handler), and the same endless loop ended as `timeout` in one run and `crashed` (SIGKILL) in the next. With `--init`, CPU-busy code is stopped by `RLIMIT_CPU` (~4.3 s for a 2 s total) and `DockerSandbox` reports SIGXCPU as a timeout. (Q13, same day: now in both sandboxes, grader 0.2.1.)
- 2026-10-01: Docker exit codes 128+N are translated to -N (same messages as subprocess), only for real signal numbers: `signal.Signals(32)` raises ValueError, so a student's `os._exit(160)` would otherwise crash the grader.
- 2026-10-01: `SandboxUnavailableError` (in sandbox.py, not `GraderError`, which would be a circular import). `DockerSandbox()` checks the image once, so a stopped daemon is a clear error, never "crashed, reward 0".
- 2026-10-01: Docker tests are opt-in: marker `docker`, `addopts = "-m 'not docker'"`, `make test-docker` (32 tests, ~55–61 s; about 1.9 s per test with start-up, kill and the leftover check). `make all` stays Docker-free and < 60 s.
- 2026-10-01: Three threat-model submissions prove what only Docker blocks: `reads_host_file` (subprocess: strict xfail, "STOLEN=top secret"; Docker: FileNotFoundError), `network_access` (Docker: OSError; skipped on subprocess so the suite never really connects), `many_processes` (Docker: stops at 62 of 200; skipped on subprocess, decision Q6). After every docker test a fixture checks that no labelled container is left.
- 2026-10-01: Fixed a pre-existing race in the test helper `_process_is_gone`: a zombie can be reaped between `exists()` and `read_text()` of `/proc/<pid>/status` (ProcessLookupError; seen once in ~18 full runs). A second failure in that same run could not be identified.
- 2026-10-01: Week 2 decisions (Najeeb): models = local Qwen (Qwen2.5-Coder ~1.5B via Ollama on the RTX 4060; same family as the Week 6–7 RL model, so it is the "before" number) + Gemini Flash free tier; budget $0; Q13 first. Eval code goes in `src/codetutor/evals/` (tested), run configs/results/reports in `lab/evals/`.
- 2026-10-01: Q13 resolved (Najeeb: yes). A kill by the CPU limit (SIGXCPU) is `timeout` in both sandboxes (one helper, `_cpu_limit_as_timeout`); GRADER_VERSION 0.2.1. Test first: `cpu_threads.py` (4 hashlib threads; hashlib releases the GIL, so CPU time grows faster than wall time) was `crashed` on 0.2.0, `timeout` now. Correction: plain Python threads can't trigger it (GIL); only C code that releases the GIL, or Docker's start-up margin.

- 2026-10-01: One unexplained failure in ~25 full runs since the Q12 fix: a `sum_of_evens` grading ended `timeout` with passed 0, first test timed out, last test 246 ms, total 4.9 s, in `make all` (the test name was lost because the output was filtered with grep; full output is now saved). Measured per-test times: growing memory bomb median 104 ms, max 261 ms; big_file 44 / 92 ms; deep_recursion and sys_exit ~0 ms. Only the growing memory bomb (2 s timer) fits a 4.9 s total, so it is most likely that test with one very slow first allocation (WSL2 VM, 7.8 GB). 200 targeted reruns, 40 timed gradings, and 2 `make all` + 1 `make test-docker` afterwards: all green. Recorded as Q14, not fixed.

- 2026-10-01: Week 2 Step 1. `build_messages` takes a `StudentProblem`, so the type itself keeps the solution, hints and hidden tests out of prompts. The prompt text is pinned by a test (`PINNED_PROMPT`): changing it fails the test until PROMPT_VERSION is bumped.
- 2026-10-01: Code extraction picks the last block that *defines the function*, then the last ```python block, then the last block, then the raw reply (changed from the plan's "last python block": small models often add a `print(...)` usage block after the solution). `<think>` sections are dropped; the method (`python_block` / `other_block` / `raw` / `empty`) is stored, so format failures can be counted apart from wrong code.
- 2026-10-01: Plan correction: the starter code is not always reward 0 (second_largest's starter returns None, the right answer for some tests; max 0.3). Tests check "never accepted" instead.
- 2026-10-01: Two hidden test inputs are written in their problem's description on purpose (`gcd(0, 0)`, `two_sum([3, 3], 6)`); the prompt leak test allows calls that the description shows.
- 2026-10-01: New small file `evals/score.py` (not in the plan): reply → extract → `grade()` → EvalRecord, kept apart from the model call so old replies can be re-scored. Stored GradeResults don't reveal hidden details (per-test statuses are kept), so records stay small.

- 2026-10-01: Week 2 Step 2 decisions (Najeeb): (1) **own client, no LiteLLM** (deviation from the brief): Ollama and Gemini both speak the OpenAI chat-completions format, so one stdlib client (~150 lines) covers both; LiteLLM would add ~50 packages (measured: 58 in total vs ~15 now) and its PyPI releases 1.82.7–1.82.8 were compromised in March 2026. Week 4 can revisit it behind the same `ChatModel` protocol. (2) **Mirrored WSL networking** to reach the Windows Ollama (not `OLLAMA_HOST=0.0.0.0`, which opens it to the network). (3) **Qwen2.5-Coder-1.5B-Instruct fp16** (`qwen2.5-coder:1.5b-instruct-fp16`), closest to the weights GRPO trains in Weeks 6–7.
- 2026-10-01: No separate response cache (changed from the Week 2 overview): in Step 3 the results JSONL is the cache (a run skips samples already saved; re-grading uses stored replies). Step 3 also follows the brief's `reveal_hidden=True` (Step 1's `score_reply` hides hidden details; only two_sum's ~60 KB input makes records big).
- 2026-10-01: Client error classes: transient (429 per minute, 5xx, timeout, dropped connection) → backoff 2·2^attempt s with 50–100% jitter, or the server's `Retry-After` / Gemini `retryDelay`, max 4 retries, max wait 60 s; per-day 429 → `QuotaExhaustedError`; 400/401/403/404 → `ModelConfigError`; refused/unknown host → `ModelUnavailableError`. The key is blanked out of every error message. Tests run against a stdlib fake server on 127.0.0.1 (real HTTP, no mocks); its `serve_forever` poll interval is 0.01 s, because the default 0.5 s made every teardown wait (8.5 s → 1.5 s).
- 2026-10-01: `scripts/try_model.py` grades with the Docker sandbox by default (model code is untrusted). `.env.example` now documents `GEMINI_API_KEY` and `OLLAMA_BASE_URL` (it replaced the Week 1 placeholder with commented OpenAI/Anthropic keys).

- 2026-10-01: Live check facts (docs/evals.md §5): Gemini's OpenAI-compatible endpoint **rejects `seed`** (HTTP 400 "Unknown name seed"), so Step 3 never sends one to Gemini. Gemini 2.5 Flash **thinks by default** (~1300–2200 hidden tokens on compress, 7–11 s per call); the hidden tokens show only in `usage.total_tokens`, so `ModelReply` now keeps `total_tokens`. Najeeb's key uses Google's newer format (not `AIza…`), so the `AIza` grep rule was replaced by `scripts/check_secrets.py`, which looks for the real `.env` values in the staged diff and never prints them.
- 2026-10-01: Setup done partly by Claude with Najeeb's approval of the plan: Claude created `C:\Users\ACER\.wslconfig` (mirrored networking; the file didn't exist) and pulled `qwen2.5-coder:1.5b-instruct-fp16` into the Windows Ollama. A temporary second Ollama on the WSL-internal address was blocked by the safety classifier ("expose local services") and not pursued. Qwen then failed on the GPU: Ollama 0.35.0's CUDA build crashes with driver 546.18; fix = update the NVIDIA driver (also needed for PyTorch/GRPO in Weeks 6–7).

- 2026-10-01: Qwen live check (after Najeeb updated the NVIDIA driver 546.18 → 617.14): 3/3 problems accepted in Docker, first call 11.7 s (model load, 3.3 GB GPU memory), then 2–3 s. Ollama `seed` is repeatable (same seed → same reply, tested on this machine and Ollama 0.35.0), so Step 3 can give sample i the seed i for Qwen; Gemini can't (rejects seed).

- 2026-10-01: Week 2 Step 3 decisions (Najeeb): Qwen n = 10, temperature 0.8, seed i for sample i, max_tokens 1024; Gemini 2.5 Flash n = 5 (quota 100–250/day), temperature 0.8, no seed, thinking on (default), max_tokens 8192, rpm 8; official results committed in `lab/evals/results/`, scratch runs gitignored.
- 2026-10-01: Run harness design (`evals/run.py`): one config = one append-only results file + meta (config, prompt/grader/problem versions, git commit + dirty flag, Ollama digest/precision); resume skips saved (problem, sample) pairs; a resume with different settings raises `RunMismatchError`. Model calls are sequential in a fixed order (keeps Ollama seeds repeatable; parallel requests may be batched), grading runs in a 2-worker background pool, each record is appended under a lock as soon as it is graded. Quota → stop (exit 2); config/unavailable errors → stop and raise; other ModelErrors → skipped, not graded, 5 in a row stop. `EvalRecord` gained `run_id`, `seed`, `max_tokens` (defaults keep one-off checks working); `score_reply` gained `reveal_hidden` (the harness uses True, per the brief). Overrides in `run_eval.py` always write to scratch, so official files only come from unchanged configs.

- 2026-10-01: Gemini's real free limit on Najeeb's key is **20 requests/day** for gemini-2.5-flash (not 100–250): the first official run (n = 5) stopped cleanly on the daily quota after 17 answers (+ 3 test calls earlier that day = 20; Google's 429 says "limit: 20"). Najeeb chose **n = 1** for Gemini (33 calls, 2 days; pass@1 only, enough for a strong reference). The partial n = 5 run (17 answers, all accepted) moved to `lab/evals/scratch/`. The daily quota resets at midnight Pacific = 10:00 Qatar time (UTC+3, while the US is on daylight time).

- 2026-10-01: Week 2 Step 4 report design: pure metric functions (`metrics.py`) + Markdown rendering (`report.py`), no new dependency. Every problem counts equally (per-problem numbers first, then the mean). pass@k is "–" when a problem has fewer than k answers. 95% interval = bootstrap over problems (2000 resamples, seed 0; ignores within-problem noise, stated in the report). "Hidden-only failure" = a wrong answer that passes every visible test. The hardest-problems table shows the most failed test with its tests.yaml note. Output is byte-identical for the same inputs (checked with `cmp`). Answers for problems no longer in the bank, or graded on an older problem version, are warned about, never silently mixed. The interpretation is left to Najeeb's week2.md.
- 2026-10-01: Najeeb asked for a more reliable alternative to the Gemini key (20 requests/day). Recommendation given: a larger local model in the same family, `qwen2.5-coder:7b` (4-bit, ~4.7 GB, fits the 8 GB GPU; laptop has 16 GB RAM, i9-13900H): free, unlimited, seedable, and it gives a 1.5B-vs-7B size comparison plus a goal for GRPO. Other free APIs (Groq, Cerebras, GitHub Models, OpenRouter) work with the same client but have changing free limits. Waiting for his choice.

- 2026-10-01: Comparison model test (scratch runs, Najeeb asked to try both): local `qwen2.5-coder:7b` (Q4_K_M, 4.7 GB, digest dae161e2) n = 5: pass@1 0.958 [0.89, 1.00], mean reward 0.988, 1.9 s median, 0 failed calls; only word_frequency 0/5 (both models split "don't" with `\w+` although the spec says inner characters stay: they do the familiar task, not the asked one). OpenRouter free tier (50 requests/day) `qwen/qwen3.8-27b:free`: 16 answers in ~13 min (median 13.6 s, max 226 s), 14 accepted; the 2 others were **provider errors** (finish_reason "error", empty content), plus skipped failed calls; stopped early by Claude (too slow, used his quota). Recommendation: 7B as the comparison model. Najeeb pasted the OpenRouter key in chat: stored in `.env`, he should rotate it.
- 2026-10-01: **Bug found** by the OpenRouter run: an HTTP 200 reply with `finish_reason == "error"` (provider failed mid-answer) was treated as a normal reply and graded as compile_error. It must count as a failed call (retry, never graded). Not fixed yet (needs a small plan); the 2 affected scratch answers are excluded from conclusions.
- 2026-10-01: Suite time is up to 45–52 s (limit 60 s; Q11). Measured: `load_all()` ~1 s, 97% pure-Python YAML parsing; PyYAML's C parser (`CSafeLoader`, libyaml available) parses all 66 problem YAML files to identical data 7× faster (0.69 s → 0.10 s). Test-only fix done: the harness tests load the bank once (setup 5.2 s → 0.66 s). Loader switch not done (Week 1 code; ask Najeeb).

- 2026-10-01: Najeeb chose the local **Qwen2.5-Coder 7B** (Ollama `qwen2.5-coder:7b`, Q4_K_M,
  digest dae161e2) as the official comparison model. Its config equals the 1.5B's except
  `run_id` and `model` (checked by loading both). The config was committed before the run
  (4f3d8c0), so the meta has `git_dirty: false`. Named confounder: 4-bit vs fp16 (the fp16 7B,
  ~15 GB, does not fit the 8 GB GPU); 4-bit usually costs a little, so the size effect is
  probably not smaller than measured. The scratch 7B run (no seeds, max_tokens 8192) stays in
  scratch and is not quoted as official.
- 2026-10-01: Checked odd numbers in the 7B report against the raw answers: pass@5 0.978 < the
  1.5B's 0.983 comes only from word_frequency (1/10 vs 2/10 → pass@5 0.5 vs 0.78). Dictionaries
  "0.58 vs 0.57" is the same true value (23/40 = 0.575 for both): `pass_at_k(10, 1, 1)` is
  0.09999999999999998, so the means fall on different sides of 0.575 before `:.2f` (Q15,
  fixed 2026-10-02).

- 2026-10-02: finish_reason bug fixed (Najeeb: "go" on recommendation 1). `_parse_reply` raises
  `_Transient` when `finish_reason` is in `FAILED_FINISH_REASONS` (only `"error"`), so the
  existing retry loop handles it like a 503 and ends in `ModelError`; the run harness already
  never grades a `ModelError` (no change in `run.py`). Partial text from such a reply is thrown
  away. `"length"` and `"content_filter"` stay normal replies (decisions about the answer, not
  server failures). Retrying a long failed answer costs tokens on a paid API (fine at $0 budget).
  No live check: OpenRouter isn't a `make_client` provider; the fake server sends the reply shape
  seen live. The 2 old scratch answers stay as they are, excluded.
- 2026-10-02: Q11 part 1 (Najeeb: "go" on the next item). Profiled the suite first: the real
  bank was loaded 5 times (~0.6 s each, almost all pure-Python YAML), while the biggest cost is
  grading (`test_every_problem_in_the_bank_is_valid` 10.2 s). The loader now parses with
  `yaml.CSafeLoader` when `yaml.__with_libyaml__` (true with PyYAML 6.0.3, no new dependency),
  else `yaml.SafeLoader`; public `parse_yaml()`. `fill_expected`'s round-trip check uses the
  same `parse_yaml`, because the check must use the parser that reads the file later. A
  differential test compares `repr` of both parsers on every bank YAML (0.66 s; `repr` because
  1 == 1.0 == True). Measured: `load_all()` 0.59 → 0.10 s; the four bank-loading tests/setups
  0.58–0.63 s → 0.11–0.12 s; net gain ~2 s per suite. Trade-off: libyaml's error message for
  broken YAML has line and column but no `^` snippet. `evals/run.py` (one config file) and
  `tests/test_bank.py` keep `yaml.safe_load` (the latter stays an independent check).
- 2026-10-02: Week 2 wrap-up. The README's Ollama commands leave out `--env-file .env`
  (measured: `uv run --env-file` fails when the file doesn't exist; only Gemini needs it). The
  README offers no offline fake-model run: fake models need a config file, and a fake config in
  `lab/evals/configs/` would look like an official run. Checked before writing week2.md:
  group_anagrams fails because both models sort the groups before sorting the words inside
  each group; 5 of the 7B's 9 word_frequency failures use a letters-only regex (\w+ / [a-z]+).
  The README's scratch-run example replaced an older gitignored scratch file with the same
  run_id (a Step 3 smoke run, quoted nowhere); scratch runs always start fresh by design.
- 2026-10-02: Week 3 decisions (Najeeb, all four recommendations): (1) **Postgres as the queue**,
  no Redis (deviation from the brief's "Redis + RQ/Arq"): the submission row is the job, saved in
  the same transaction, so no dual-write problem; we write the claim/lease/retry logic (~100
  lines). RQ was rejected for the extra service and the DB-row-vs-Redis-job dual write; Arq for
  being async while `grade()` blocks. (2) **Local Postgres in Docker** for development (Supabase
  only when hosting; same Postgres 17). (3) **Name-only dev login** (no password, marked not
  secure; real auth before hosting). (4) **nvm** for Node in WSL. Node **24** LTS instead of the
  22 offered in the question (22 is in maintenance since Oct 2025).
- 2026-10-02: Week 3 Step 0. Image `pgvector/pgvector:pg17` (637 MB unpacked), not the
  `supabase/postgres` image already on the machine (it expects the Supabase stack's roles and
  setup). Dev credentials are fixed in `compose.yaml` and `settings.py` (local throw-away DB on
  127.0.0.1 only; real hosting sets `DATABASE_URL` from a secret), so `make test` needs no
  `.env`. `make test` now depends on `db-up`, so tests need Docker (the DB is core from Week 3).
  The smoke test only checks that pgvector is *available*; `CREATE EXTENSION` comes with Week 4.
  With the DB stopped, connecting to 127.0.0.1:5432 timed out (3 s) instead of being refused
  (WSL mirrored networking); the smoke test's message says "Run `make db-up`" either way.
  nvm v0.40.8's install script was downloaded and read before running; it added 3 lines to
  `~/.bashrc`.
- 2026-10-02: Q15 resolved (Najeeb: "go"; option A, changed to round **half up**). Checked
  every group value with exact fractions first: the problem was wider than Dictionaries.
  Python's `:.2f` rounds the stored binary value with ties to even, so exact ties went both
  ways (5/8 → 0.62, 7/8 → 0.88, 39/40 → 0.97, 37/40 → 0.93; 7B median tokens 92.5 → 92).
  Plain "round to 9 decimals, then `:.2f`" would make equal values print the same, but would
  still print 23/40 as 0.57 (0.575 is stored below .575). So `_fixed` in `report.py` cuts at
  12 decimals with `Decimal(value).quantize(Decimal("1e-12"))` (float noise here ~1e-14;
  non-tie values are > 4e-12 from a tie, so no double-rounding error), then rounds half up.
  Every computed number in the report uses it (temperature `:g` stays: config value).
  week2.md regenerated: 7 tie cells changed, no headline number; output byte-identical across
  two runs. The test imports the private `_fixed` directly (pure function).
- 2026-10-02: Week 3 Step 1 (Najeeb approved the plan). **Two problem tables:** `problem_versions`
  (sealed copy of every synced version, full `Problem.model_dump(mode="json")`, never updated;
  only the worker reads it) and `problems` (current version, `to_student_view()` only; the API
  reads it). The worker grades from the DB copy, so a submission is graded on the version the
  student saw; FKs from `problems` and `submissions` to `problem_versions` enforce it. Rejected:
  worker reads the files (old versions lost, worker needs the repo).
- 2026-10-02: **Postgres `json`, not `jsonb`**, for every value the grader compares or shows
  (measured: `jsonb` turned the float `1e300` into an int and `1E2` into `100`; `json` kept
  floats, `-0.0` and `\u0000`). Pinned by tests, incl. all 33 problems round-tripped by `repr`.
- 2026-10-02: Statuses are `text` + CHECK built from the Python enums (not Postgres ENUMs: hard
  to change); migration 0001 keeps a frozen copy, and `test_every_*_status_is_allowed` fails if
  a new status has no migration (Alembic doesn't compare CHECKs). Constraint naming convention
  in `models.py`. Two `test_results` CHECKs keep hidden details out (`NOT (hidden AND
  revealed)`; unrevealed rows have SQL NULL input/expected/actual). Measured trap: Python `None`
  in a json column is JSON `null`, which that CHECK rejects, so Step 2 must leave those columns
  unset. Extra CHECKs beyond the plan: `result_complete` (a set result has every summary
  column), `version >= 1`, difficulty and job status lists.
- 2026-10-02: Sync rules: new (id, version) → sealed copy + `problems` row; changed hash without
  a bump → refused (also for hint typos and new buggy files; idea for a grading-only hash in
  ideas.md); versions only go up; missing folder → `active = false` (never deleted), back →
  "restored"; an empty bank is refused (a wrong `--root` would retire everything). All rules
  are checked before writing, all violations are listed in one `SyncError`, the caller commits.
  `load_all()` runs first for the bank-wide checks, then each folder is read again for its hash
  (~0.1 s; keeps one loader).
- 2026-10-02: Tests own `codetutor_test` (`database_url_for_tests()`; the name avoids pytest
  collecting a `test_*` function), dropped `WITH (FORCE)` and re-created per run, built with the
  real migrations (not `create_all`); tables truncated after each test; `recreate_database`
  refuses names without "test". The migration round trip uses its own `codetutor_test_migrations`.
- 2026-10-02: Found while testing: with the DB stopped, SQLAlchemy connections hung > 2 min
  (killed by `timeout 120`; WSL mirrored networking drops instead of refusing). Every engine now
  has `connect_timeout = DB_CONNECT_TIMEOUT_S` (5 s, `settings.py`); the sync script and Alembic
  fail after ~6 s with "Run `make db-up`".
- 2026-10-02: `alembic.ini` has no URL (env.py uses `settings`, or `config.attributes["url"]`
  from tests); readable revision files (`--rev-id 0001` → `0001_initial_schema.py`); post-write
  hooks run `ruff check --select I --fix` and `ruff format` on new migrations. No new
  `TODO(najeeb)` (the fizzbuzz one is still open).
- 2026-10-02: Week 3 Step 2 (Najeeb approved the plan). Claim = one plain-SQL `UPDATE … WHERE id =
  (SELECT … ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING …`, committed at once; grading
  runs with no transaction open; save = result + test rows in one transaction. Fixed lease
  `LEASE_S = 300` (bank worst case 38 s; a test keeps every problem under half); `attempts` is
  the fencing token (save/release `WHERE attempts = ours AND job_status = 'running'`; 0 rows =
  lost, nothing written). `MAX_ATTEMPTS = 3`; jobs whose lease expired on attempt 3 are failed at
  the next claim (`FAIL_ABANDONED_SQL`). Errors on our side → requeue with `last_error`; the
  worker pauses 2 s and stops after 5 errors in a row (exit 2), like the eval harness.
- 2026-10-02: NUL (measured: in stdout, test errors and returned values) → `clean_text` replaces it
  with U+FFFD in text columns; json values keep it (`\u0000`). `enqueue_submission` refuses code
  with NUL, lone surrogates, or > 50 000 characters (`InvalidSubmissionError`), and unknown or
  retired problems (`UnknownProblemError`), so the API inherits the checks. Found: a returned
  lone surrogate is graded `crashed` by the Week 1 grader (ideas.md; needs its own plan).
- 2026-10-02: Worker functions take a Session and never commit (loop.py owns the 3 transactions);
  problem copies cached per run (sealed copies never change). The worker script always uses
  `DockerSandbox` (no flag); tests use `SubprocessSandbox` + 1 `docker` test. `make worker` depends
  on `db-sync` (deviation from the plan's `db-migrate`: the worker needs synced problems, and a
  changed problem without a version bump then stops it with sync's message). `make test-docker`
  now depends on `db-up`. `submit.py` imports `format_result` from `grade_cli.py` (same folder).
  Graceful stop checked live: `uv run` forwards SIGINT; the grading child (own session) is not
  hit; the job finished, then the worker exited. Worker tests ~7 s alone (1.9 s is the shared
  test-DB setup); suite +2.3 s measured.
- 2026-10-02: Week 3 Step 3 (Najeeb approved the plan, all 9 decisions). Dev login = `POST
  /api/login {name}` → `{id, name}`, then the `X-User-Id` header; one dependency `current_user`
  (real auth replaces only it); names trimmed, 1–40 characters, no Cc/Cs characters,
  case-sensitive. Rate limits counted from `submissions` in Postgres (not in memory): 3 waiting
  (Retry-After 2) and 10 per 60 s sliding window (Retry-After = until the oldest leaves);
  `create_submission` locks the user row (`FOR UPDATE`) before counting (check-then-act race).
  Submit body carries `problem_version`; `enqueue_submission(..., expected_version=)` raises
  `ProblemChangedError` (409) in the same read that picks the version. Plain `def` endpoints +
  sync SQLAlchemy. Response models are the allow-list; failed jobs show `FAILED_MESSAGE`, never
  `last_error`; another user's submission is 404 (not 403). Migration 0003 = index
  `submissions (user_id, created_at)`. App factory `create_app(engine=None, limits=None)`;
  `make api` = uvicorn `--factory` on 127.0.0.1:8000. No CORS (Step 4 uses Next.js rewrites).
- 2026-10-02: Own `RequestValidationError` handler (not in the plan): FastAPI's default 422
  copies each bad value back, and Starlette's UTF-8 encoding crashed on a lone surrogate (500);
  an unknown JSON key with a surrogate does the same through `loc`. The handler keeps only
  `type`/`loc`/`msg` and writes ASCII-escaped JSON. `problem_id` in the submit body uses
  `PROBLEM_ID_PATTERN`, so a malformed id never reaches Postgres.
- 2026-10-02: FastAPI 0.142 depends on `opentelemetry-api` (inert without an SDK) and would add
  OTLP exporters from `OTEL_*` environment variables (it would fail anyway: no exporter
  packages). `create_app` passes `telemetry={"auto_configure": False}`: no data leaves the
  machine; tracing is a Week 4 decision (Langfuse).
- 2026-10-02: `get_or_create_user` moved from `scripts/submit.py` to `db/users.py` (one function
  for the API and the script; submit.py checked live). "My submissions" selects only summary
  columns (no `code`/`stdout`). A test greps `src/codetutor/api/` for the sealed-copy table's
  name (a cheap guard until the separate DB role), and another pins the 7 routes.
- 2026-10-02: Measured: `test_api.py` 7.5 s, incl. ~1 s of test-DB creation that moved to it
  (it now sorts first), so ~6.5 s net (the plan estimated 4 s). The EXPLAIN experiment inserted
  500 users + 50 000 submissions and rolled back; Postgres sequences are not rolled back, so dev
  ids now start near 100 010 (submissions) and 505 (users). Harmless. Starlette 1.7 warns that
  its TestClient wants `httpx2` instead of `httpx` (Q16).
- 2026-10-02: Week 3 Step 4 (Najeeb approved the plan, 11 decisions). Server components for
  the problem list and text (`force-dynamic`: asked per request, never at build time), client
  components for login/editor/submit/results. Next.js rewrite `/api/*` → the API (one origin, no
  CORS); server components call `CODETUTOR_API_URL` directly. Login `{id, name}` in
  localStorage through a React context; 401 → log out. Polling: a loop that waits for each
  answer, then 1 s; stops on done/failed, after 120 s, or via a "generation" counter (new
  submit, user change, unmount). Monaco copied by a postinstall script into `public/monaco`
  (no jsdelivr CDN). Plain CSS with light/dark variables. `NEXT_TELEMETRY_DISABLED=1` in the
  npm scripts. Hand-written `lib/types.ts`. Drafts per problem in localStorage.
- 2026-10-02: API display text (Step 3 change in the Step 4 plan): `ProblemOut`/`ExampleOut`
  and `ResultOut`/`TestOut` extend the existing models with `args_repr`/`expected_repr`/
  `actual_repr` (Python `repr`, cut at `MAX_REPR_CHARS = 500`; `actual_repr` null when the test
  has an error; hidden tests none). Measured: 2 problems have whole-number floats in visible
  tests (celsius_to_fahrenheit, average_of_three).
- 2026-10-02: Found while running: (1) port 3000 is held by a Windows `node.exe` (another dev
  server, listening on 0.0.0.0, i.e. all interfaces); `next dev` failed loudly with EADDRINUSE,
  so CodeTutor uses 3100 (`WEB_PORT`). (2) `next dev` 16.3 wrote `web/AGENTS.md` + `web/CLAUDE.md`
  (agent instructions); `agentRules: false` in next.config.ts, files deleted (looked at first).
  (3) Next 16.2+ error boundaries get `retry()` (fetches again); `reset()` only re-renders, so
  `error.tsx` uses `retry` (from Next's bundled docs). (4) The hard-wrapped descriptions looked
  broken with `pre-wrap`: `lib/description.ts` turns them into paragraphs, lists and code
  (checked on all 33: no word lost). (5) The page's "Examples" heading was renamed "Visible
  tests" (the description has its own "Examples:"). (6) Dark-mode Submit button got dark text
  (white on light blue was hard to read).
- 2026-10-02: UI verification. Headless Chrome with `--virtual-time-budget` did not hydrate the
  *dev* server's page (server HTML only); the production build did (Monaco + login present). A
  scratch Node script (built-in `WebSocket` → Chrome DevTools protocol, throw-away profile,
  localhost) then ran the real flow on the dev server; all temp profiles/screenshots deleted.
  `npm audit`: 2 low (DOMPurify 3.4.15 bundled in monaco-editor 0.57; needs `IN_PLACE`, which
  Monaco never sets: 0 uses in the bundle). Kept 0.57 (Q17).
- 2026-10-02: Week 3 Step 5 (Najeeb approved; chose the DevTools script over Playwright or no
  browser test; click-through not done yet). Three layers of end-to-end checks share one checker
  (`codetutor.e2e.run_checks`, stdlib `urllib`, new user `e2e-<ms>` per run). The "secrets"
  for leak checks are the hints and the solution's own lines (>= 12 characters, not in the
  starter code or the description). The API health probe has a 3 s timeout (WSL: a closed
  port times out instead of refusing).
- 2026-10-02: `make web-e2e` starts its own Chrome (WSL: the Windows Chrome; `CHROME`,
  `WEB_URL`, `E2E_DEBUG_PORT` override), refuses to run if the debugging port already answers,
  uses a throw-away profile in the Windows temp folder and deletes it with Windows' `rmdir`.
  Measured: 47.5 s → 17.4 s (port probes had no timeout; deleting the profile through WSL's
  file bridge took ~12 s). It waits for the old result to clear instead of removing a
  React-managed DOM node.
- 2026-10-02: README commands re-run as written: install/check block, grade CLI, the Python
  example, eval_report (byte-identical), try_model (accepted 10/10), the 2×2 scratch run, the
  three servers + `make e2e` + `make web-e2e`, `submit.py --wait`. Found: `ollama pull` does not
  exist in WSL (Ollama runs on Windows); the README now says `ollama.exe pull` from WSL.
- 2026-10-02: Q11 resolved (Najeeb: "go" on recommendation C). The whole-bank validation test is
  marker `slow`, deselected by default (`addopts = "-m 'not docker and not slow'"`; a
  command-line `-m` still replaces it, so `make test-docker` is unchanged). It called the same
  `validate_bank()` that `make validate` runs right after pytest, so `make all` graded the bank
  twice. **Deviation from brief §3.5** ("runs the validator over all problems inside pytest"):
  the test stays and runs with `uv run pytest -m slow`; the validator's logic keeps its 7 unit
  tests in the default suite. Trade-off: a bare `uv run pytest` no longer checks the real bank;
  a future CI must run `make all`. Measured the same evening: pytest 35.8–38.0 s (3 runs), the
  slow test alone 10.35 s; the rest of the drop from 47.9–64.8 s is machine load. Option B
  (parallel bank validation) dropped.
- 2026-10-02: Week 4 decisions (Najeeb, all four recommendations): (1) traces are **rows in
  Postgres** (needed anyway for ratings and Week 6–7 preference data); Langfuse Cloud only as an
  optional last step (measured alternatives: Langfuse Cloud Hobby = 50k units/month, 30 days of
  data, no card, data leaves the machine; self-hosting = 6 parts: web, worker, Postgres, Redis,
  ClickHouse, S3). (2) The tutor model **never sees `solution.py`** (problem text, 3 reference
  hints, student code, visible results, hidden pass/fail counts only). (3) RAG with
  `nomic-embed-text` in Ollama + pgvector, measured against a keyword baseline. (4) Claude drafts
  the 8 course notes, Najeeb reviews. Own model client kept (2026-10-01).
- 2026-10-02: **Hint 3 = "bottom-out" hint** (Najeeb, recommendation A). Found while planning: our
  own hint 3s contain solution lines inside sentences (9 problems with the final rule, e.g.
  recursive_sum `return nums[0] + recursive_sum(nums[1:])`); the Week 1 check (fences, lines
  starting with a keyword) missed them. Kept unchanged (rewriting = 9 version bumps and 9
  "graded on an older version" warnings in the Week 2 report, though hints never affect
  grading). The UI shows hint 3 only on request; the AI tutor is held to the strict rule.
  **Deviation from brief §9** ("near-pseudocode but NOT code").
- 2026-10-03: Week 4 Step 0 guardrail design, measured on the bank before choosing:
  "anything that parses as Python" blocked 9 of 33 hint 1s ("first: 2024" is an annotation,
  "return the" a return), so rejected. Final rules: a non-trivial solution line anywhere
  (whitespace removed, `'` → `"`), fenced blocks (also inline ```` ```x``` ````), whole lines or
  backtick spans that are statements (expressions allowed; an annotation without a value counts
  as prose). Trivial solution lines (return + name/constant, `name = simple value`, `+=`/`-=`
  of one, `else:`, headers of plain words) are not secrets, matched on the single-spaced line
  (squashing first made `if need in seen:` look like one word). Trailing comments cut with
  `tokenize` (found by a test: `high = len(nums) - 1  # ...` never matched). Text from the
  starter, description or the student's own code is allowed. The generated-leak test is caught
  by construction (it tests the details); the hand-written cases and Step 2's real hints are
  the real test. `e2e.forbidden_texts` now uses `solution_lines` (was: stripped lines >= 12
  characters, comments kept), checked live.
- 2026-10-03: Measured: on battery power the suite is ~45% slower (the same 413 tests 53.3 s vs
  35.8–38.0 s on mains); with Step 0's tests, 57.1 and 69.9 s on battery. Measure suite time on
  mains power.
- 2026-10-03: Week 4 Step 1 (Najeeb approved the plan). Notes in `course/notes/NN_<module>.md`
  (named like the bank's module folders); one `##` section = one chunk, id
  `"<file>#<heading slug>"`; embedded as `"search_document: <title> > <heading>\n\n<body>"`
  (nomic's required task prefixes, checked on its model card; `search_query: ` for questions).
  `make notes-sync` is separate from `db-sync` (the worker and the API must not need Ollama);
  it embeds only new/changed sections (other hash or other model) and deletes removed ones.
  `note_chunks` rows are replaced in place (unlike problem versions); Step 2's trace keeps chunk
  ids + hashes. No vector index (41 rows: exact scan). Own `Vector` type instead of the
  `pgvector` package (needs numpy), registered in the dialect's `ischema_names` so the drift test
  reads the column back as `Vector(768)` (checked with `-W error`); migration 0004 keeps a frozen
  `_Vector768` type. `make_embedder` only accepts models in `KNOWN_EMBEDDERS` (a wrong size or a
  missing prefix fails silently). Keyword search builds the tsquery from `[a-z0-9]+` words
  joined by `|` (no user operators). The notes are ruff-formatted (ruff formats Python blocks in
  Markdown; `course/` is not excluded). Questions written before the notes (from the buggy
  files); 4 of 40 have two relevant sections, labelled after the notes existed.
- 2026-10-03: Week 4 Step 2. Measured: Ollama's default window is 4,096 tokens and our
  OpenAI-style calls can't change it; prompts of ~5,400 and ~18,000 tokens were cut to ~2,050
  tokens keeping the END (system message lost, the model made up the code word), and reported
  fewer tokens than the window. Rule: estimate `ceil(chars / 3)` < 2,048 before sending;
  reported `prompt_tokens` >= 2,048 = "maybe cut", never shown (lowest seen: 3.42 chars/token).
  The retry names only the kind of problem ("it contains code"), never the blocked line. The
  model gets reference hints up to the current level, never hint 3. Student code and question
  sit in fences longer than any backtick run inside them. `give_hint` never raises for model or
  search failures (failed search = no notes, error kept; failed call = reference hint, no retry
  here: the client retries transient errors). Settings: 7B, temperature 0.2, seed 0,
  max_tokens 300, 80 words. The safety run strips the buggy files' comments
  (`without_comments`), since they explain the bug.
- 2026-10-05: Step 2 committed in a new session (the earlier session ended before its STOP).
  Docker Desktop was not running after a WSL restart; Claude started it with Najeeb's OK
  (`powershell.exe Start-Process`, daemon ready in ~9 s). The Step 2 interview note was missing
  and was added before the commit.
- 2026-10-05: Week 4 Step 3 (Najeeb approved the plan, D1-D10). **A separate tutor worker**
  makes hints (the hint needs the sealed problem copy; the API never reads it); **one table**:
  the `hints` row is the job (`claims` is the fencing counter, since `attempts` already holds
  the model replies); every level goes through the worker (level 3 too); levels in order
  (level L needs a done hint of level >= L-1 for this problem); a request is about either my
  graded submission (same problem and version, else 404/409) or `code`; hint limits in
  `RateLimits` (1 waiting, 10 per 10 min); `HintOut` has 12 fields, never the trace; rating
  is changeable (last wins); split into 3a (backend) and 3b (UI + e2e + docs).
- 2026-10-05: Measured for D9: Ollama reload of the 7B after its idle unload 13.3 s / 12.0 s
  (109 s only right after a reboot); 7B 4.42 GiB + nomic 0.3 GiB fit together (5.1 of 8 GB
  used). `/api/generate` with no prompt loads a chat model (`done_reason: "load"`); embedding
  models refuse `/api/generate`, `/api/embed` with `input: []` loads them. An OpenAI-style
  chat call kept the earlier 10m keep-alive (expiry = call + 10 min). So the worker loads both
  at start and refreshes every 4 min (`KEEP_LOADED_EVERY_S`); a failed refresh only logs.
- 2026-10-05: Found by a test: in a `json` column, Python `None` is stored as JSON `null`,
  which SQL sees as NOT NULL, so `ck_hints_result_complete` missed a missing `attempts`. The
  three nullable trace columns use `JSON(none_as_null=True)` (Python side only, no DDL change).
  The tutor worker's note search uses an AUTOCOMMIT engine copy, so no transaction stays open
  during a model call.

## Open questions
- Q14: the memory-bomb flake (Decisions log, 2026-10-01). Options: (A) leave it and save full test output on every run, so a repeat names the test; (B) raise `MEMORY_TEST` from 2 s to 3 s. Trade-off of B: nothing is slower while the memory limit works, but if it ever broke, the bomb (~2.5 GB/s) would get more time to fill the 7.8 GB WSL machine before the timer stops it. Recommendation: A, until it happens again.
- Q17: monaco-editor 0.57 bundles DOMPurify 3.4.15 (npm audit: 2 low, DOM XSS in `IN_PLACE` mode). Monaco never enables that mode, and the served files are prebuilt, so an npm override would change nothing. Options: (A) keep 0.57 and re-check when Monaco ships DOMPurify >= 3.4.16 (ideas.md); (B) pin monaco-editor 0.56.0 (DOMPurify 3.4.8, not in the advisory, but older). Recommendation: A.
- Q16: Starlette 1.7 warns "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (one warning per test run). Options: (A) keep `httpx` (pinned in uv.lock, so nothing changes by itself) until a release really drops it; (B) switch the dev dependency to `httpx2` (a new dependency: needs Najeeb's OK). Recommendation: A.

## Known limitations
- The Week 1 "no code in hints" check is a heuristic (``` fences and lines starting with a Python keyword). Code written inside a sentence is not caught: 9 hint 3s contain solution lines (kept as bottom-out hints, docs/tutor.md §1.4).
- The tutor guardrail compares text and parses code; it does not understand meaning. Known misses: code inside a sentence that is not a solution line, solution lines with renamed variables, a whole algorithm in words (docs/tutor.md §1.3).
- Tests import helpers from `tests/conftest.py` directly (`from conftest import ...`). This works with pytest's default rootdir import mode; move them to a helpers module if that ever breaks.
- The subprocess sandbox is NOT secure: student code can read the user's files and use the network; fork bombs and setsid() escapes are not stopped. Use `DockerSandbox` for untrusted code (docs/grader.md, sections 5–6).
- The Docker sandbox shares the host kernel (a kernel bug can let code out), and the Docker daemon is root-equivalent, so the Week 3 worker must never expose it. In Docker, code that sleeps at the top level runs up to 5 s past the total limit (start-up margin); a daemon that fails mid-run shows up as `crashed`.
- Student code can catch the per-test timeout with a bare `except:` in a loop; only the total limit stops it (was Q4).
- The result token is in the child's memory and can be found; the real protection is that expected values never enter the child (was Q5).
- Timeouts depend on machine load, so grading is deterministic except for timeouts under heavy load. This also affects failure *labels*: a memory bomb can end as `timeout` or `runtime_error` depending on load (same reward, different label). Keep it in mind for Week 2 failure-type statistics.
- The validator's "solution < 25% of the time limit" check is measured while 4 gradings run in parallel, so it can be flaky on a busy machine.
- The input check compares with `==`: `[1]` and `[True]` count as equal, and a change undone before the function returns is not seen. It catches honest mistakes, not attackers.
- Postgres `text` can't hold NUL (`\x00`, DataError): the worker replaces it with U+FFFD in text columns, and `enqueue_submission` refuses code containing it.
- The worker can't tell a Docker daemon failure mid-run from a student crash: both are saved as `crashed` (idea in ideas.md). A dead worker's job waits up to the 5 min lease. FIFO across users (no fairness yet).
- The hidden tests are in the database (`problem_versions`); only a source-scan test keeps the API away from that table until a separate DB role exists (ideas.md). Two syncs at once are not guarded.
- The retrieval eval is small and optimistic: 40 questions (one = 2.5 points), and the same author (Claude) wrote the notes and the questions. `embed_model` stores the embedder's name, not the model digest, so a re-pulled model doesn't trigger re-embedding (docs/tutor.md §2.5).
- The tutor's first hint after a model load can take ~110 s (measured 109 s after a reboot);
  warm hints take ~1–5 s. Hint quality (does it help? does it follow "talk as you"?) is not
  measured yet (Step 4). The `hints` table keeps blocked attempts, which may contain solution
  code: only `text` may ever leave the server.
- A bare `uv run pytest` does not check the real problem bank (marker `slow`); `make all` does,
  through `make validate`. The browser check (`make web-e2e`) is hand-written and opt-in; `web/lib/types.ts` is written by hand and can drift from the pydantic models; no "solved" marks in the problem list.
- The API's dev login is spoofable (any `X-User-Id`) and new names are free, so the per-user rate limits can be bypassed. uvicorn has no request-size limit (the whole body is read before the 50 000-character check). All of this must be fixed before hosting (docs/api.md §7, ideas.md).
