# CodeTutor

A CS1 (intro to programming) Python practice platform with instant auto-grading, and an AI lab
built on top of it. Every problem has automatic visible and hidden tests. The same grader scores
student submissions, evaluates AI models (pass rates), and serves as the reward function for
reinforcement-learning training of a small code model.

**Status:** Weeks 1–3 of 8 are done: the problem bank, the auto-grader, an eval harness that runs
language models through the grader, and the app around them (Postgres, a grading queue, an HTTP
API and a web UI with a code editor). Next: Week 4 (an AI tutor that gives hints, not answers).

## What is in it

| | |
|---|---|
| Problems | 33, in 8 CS1 modules (variables → recursion): 17 easy, 15 medium, 1 hard |
| Tests | 374, of which 242 are hidden |
| Buggy solutions | 97 known-wrong solutions; every problem has at least one bug that only hidden tests catch |
| Test suite | 417 pytest tests, plus 33 that run in Docker; 31 test submissions, most of them hostile (infinite loops, memory bombs, `os._exit`, fake results, output floods, reading host files) |
| Model evals | 2 official runs (Qwen2.5-Coder 1.5B and 7B), 330 graded answers each |
| App | Postgres (5 tables), a grading queue in Postgres, a FastAPI service (7 endpoints), a Next.js UI with the Monaco editor; checked end to end over HTTP and in a headless browser |

A validator checks every problem: the reference solution passes all tests, the starter code does
not, and every buggy solution fails at least one test (a simple form of mutation testing).

## How grading works

- **One function for everything:** `grade(problem, code) -> GradeResult`. Student submissions,
  model evals and the RL reward all use it, so they can never disagree.
- **The student's code never sees the answers.** It runs in a child process that gets the test
  *inputs* only. The parent process compares the results with the expected values.
- **Visible and hidden tests.** Students see the visible ones. Hidden tests catch solutions that
  only fit the examples. The reward is partial credit: passed tests / all tests.
- **Limits:** time per test, total time and memory. The possible statuses are `accepted`, `wrong_answer`,
  `runtime_error`, `timeout`, `compile_error` and `crashed`.
- **Reproducible:** grading is deterministic (apart from timeouts on a very busy machine), and
  every result records the grader version and the problem version.

Details: [docs/grader.md](docs/grader.md). Problem format: [docs/problem-format.md](docs/problem-format.md).

## Requirements
- Linux or macOS (on Windows, use WSL2); the grader's sandbox uses POSIX features
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose (for the local database and the safe sandbox)
- Node 24 (for the web UI only; installed with [nvm](https://github.com/nvm-sh/nvm))

> **⚠️ Security:** the default sandbox is a subprocess with resource limits. It is **not secure**:
> graded code can read your files and use the network. For code you don't trust, use the Docker
> sandbox (`--sandbox docker`, or `DockerSandbox()` in Python): no network, no host files,
> non-root, a process limit. It is much safer, but not a perfect wall (containers share the
> host's kernel). See [docs/grader.md](docs/grader.md#5-threat-model), sections 5 and 6.

## Install and check
```bash
make install    # install dependencies and the package (editable)
make db-up      # start the local Postgres (compose.yaml, 127.0.0.1 only); make db-down stops it
make db-sync    # create the tables (migrations) and copy the problems into Postgres
make all        # lint + tests + validate every problem (starts the database if needed)
make build      # write dist/problems.jsonl and dist/problems_student.jsonl
```
Other targets: `make test`, `make lint`, `make validate`, `make format`, and
`make test-docker` (runs the hostile submissions in the Docker sandbox; needs Docker).

## Grade a solution
From the command line. This file checks `% 3` before `% 15`, a classic fizzbuzz bug:
```bash
uv run python scripts/grade_cli.py cs1.loops.fizzbuzz problems/cs1/03_loops/fizzbuzz/buggy/checks_fizz_first.py
```
```text
Problem: cs1.loops.fizzbuzz (version 1)
Status:  wrong_answer
Reward:  0.6  (6/10 tests passed)

      test  kind     result         details
  ✅  t01   visible  passed
  ✅  t02   visible  passed
  ✅  t03   visible  passed
  ✅  t04   visible  passed
  ❌  t05   hidden   wrong_answer   (hidden test)
  ❌  t06   hidden   wrong_answer   (hidden test)
  ✅  t07   hidden   passed
  ✅  t08   hidden   passed
  ❌  t09   hidden   wrong_answer   (hidden test)
  ❌  t10   hidden   wrong_answer   (hidden test)
```
Every visible test passes; only the hidden tests (multiples of 15) find the bug. Add
`--reveal-hidden` to see their inputs, `--json` for the full `GradeResult`, or `--sandbox docker`
to run the code in a container.

From Python:
```python
from pathlib import Path

from codetutor.grader import grade
from codetutor.problems import get_problem

problem = get_problem("cs1.loops.fizzbuzz")
code = Path("problems/cs1/03_loops/fizzbuzz/solution.py").read_text()
result = grade(problem, code)
print(result.status, result.reward, f"{result.passed}/{result.total}")
```
```text
accepted 1.0 10/10
```

## Evaluate a model
The eval harness gives a model the same view a student gets (description, starter code, visible
tests), takes the code out of its reply, and grades it with the same `grade()`. Official results
(10 answers per problem, temperature 0.8, seeds 0–9, graded in the Docker sandbox, on a laptop
GPU):

| Model | pass@1 [95% interval] | pass@10 | Mean reward | Wrong answers that pass every visible test |
|---|---|---|---|---|
| Qwen2.5-Coder 1.5B (fp16) | 0.867 [0.779, 0.942] | 1.000 | 0.953 | 15 of 44 |
| Qwen2.5-Coder 7B (4-bit) | 0.945 [0.867, 1.000] | 1.000 | 0.989 | 9 of 18 |

Both models solve every problem at least once in 10 tries, but not every time. A third (1.5B)
and a half (7B) of their wrong answers pass every visible test: only the hidden tests catch
them. Note that the two runs differ in size *and* precision (the 7B is 4-bit). Full report, by
module, difficulty and concept: [lab/evals/reports/week2.md](lab/evals/reports/week2.md).

```bash
# Rebuild the report from the committed results (no model needed)
uv run python scripts/eval_report.py lab/evals/results/*.jsonl --out lab/evals/reports/week2.md

# Ask a local model to solve one problem (needs Ollama; grading uses Docker)
ollama pull qwen2.5-coder:1.5b-instruct-fp16   # from WSL, with Ollama on Windows: ollama.exe pull ...
uv run python scripts/try_model.py ollama/qwen2.5-coder:1.5b-instruct-fp16 cs1.loops.fizzbuzz

# A small test run: 2 problems x 2 answers, written to lab/evals/scratch/ (gitignored)
uv run python scripts/run_eval.py lab/evals/configs/qwen2.5-coder-1.5b-fp16.yaml \
    --problems cs1.loops.fizzbuzz,cs1.strings.compress --samples 2
```
A full run (33 problems × 10 answers) takes about 15 minutes on an RTX 4060 laptop GPU. Runs are
resumable, and a failed API call is retried, never graded as a wrong answer. Gemini needs an API
key in `.env` (run with `uv run --env-file .env ...`). Setup, the model client and the report:
[docs/evals.md](docs/evals.md).

## Run the app
Three terminals, started one after the other (each one syncs the problems into Postgres first):
```bash
make worker   # grades queued submissions in the Docker sandbox
make api      # the HTTP API on http://127.0.0.1:8000 (interactive docs at /docs)
make web      # the web UI on http://localhost:3100 (installs its npm packages the first time)
```
Open http://localhost:3100, log in with any name (a development login: **not secure**), pick a
problem, write code, submit. Then check the whole chain:
```bash
make e2e      # 9 checks over HTTP: API, worker, web pages, hidden tests stay hidden (~8 s)
make web-e2e  # 8 checks in headless Chrome: log in, submit, results, limits, drafts (~17 s)
```
`make web-e2e` starts its own Chrome (in WSL, the Windows Chrome; `CHROME=/path` picks
another one). Without the UI, `scripts/submit.py` sends a file to the queue:
`uv run python scripts/submit.py cs1.loops.fizzbuzz problems/cs1/03_loops/fizzbuzz/solution.py --wait`.
How it works: [docs/worker.md](docs/worker.md) (queue), [docs/api.md](docs/api.md) (API),
[web/README.md](web/README.md) (UI).

### Architecture (as built)
```
Browser ── http://localhost:3100 ──► Next.js (web/)
                                       │  pages: problem list + problem text (rendered on the server)
                                       │  /api/* is forwarded ──► FastAPI (src/codetutor/api/, :8000)
                                                                   │ submit = one INSERT (the row is the job)
                                                                   ▼
                       Postgres: problems (student view), problem_versions (sealed, hidden tests),
                                 submissions (job + result), test_results, users
                                                                   ▲ claim: FOR UPDATE SKIP LOCKED + lease
                                                                   │ save: result + tests, fenced by attempts
                                         Worker (make worker) ── grade(problem, code) ──► Docker sandbox
```
The browser polls `GET /api/submissions/{id}` once per second until the job is done. There is
no Redis: Postgres is the queue, so saving a submission and queueing it can never disagree.

## Add a problem
1. Create `problems/cs1/<NN>_<module>/<slug>/` with `problem.yaml`, `starter.py`, `solution.py`,
   `tests.yaml` (inputs only) and 1–3 files in `buggy/`.
2. `uv run python scripts/fill_expected.py <folder>` runs the solution to fill in the expected values.
3. `make validate`. A buggy solution that passes every test means a test is missing.
4. When you change the tests of an existing problem, bump its `version`.

Full checklist: [docs/problem-format.md](docs/problem-format.md#6-how-to-add-a-problem).

## Project layout
- `problems/`: the problem bank (one folder per problem)
- `src/codetutor/problems/`: problem schema and loader
- `src/codetutor/grader/`: runner (child process), sandboxes (subprocess, Docker), comparison, `grade()`
- `src/codetutor/bank/`: expected-value filler, validator, dataset builder
- `src/codetutor/evals/`: prompt, code extraction, pass@k, model client, run harness, metrics, report
- `src/codetutor/db/`: database tables (SQLAlchemy), Alembic migrations, problem sync
- `src/codetutor/worker/`: the grading queue in Postgres (claim, lease, retries) and the worker loop
- `src/codetutor/api/`: the HTTP API (FastAPI): endpoints, dev login, rate limits
- `src/codetutor/e2e.py`: end-to-end checks of a running stack (`make e2e`)
- `web/`: the web UI (Next.js + Monaco), with its own README
- `scripts/`: command-line wrappers for the above, plus the grading and eval CLIs
- `lab/evals/`: run configs, committed results (one graded answer per line) and the report
- `tests/`: test suite; `tests/submissions/` holds the hostile submissions
- `docs/`: design docs (`grader.md`, `problem-format.md`, `evals.md`, `database.md`, `worker.md`, `api.md`); `docs/notes/` holds weekly notes and interview notes

## Roadmap
| Week | Deliverable | |
|---|---|---|
| 1 | Problem bank + grader + validator (+ optional Docker sandbox) | ✅ done |
| 2 | Eval harness: LLMs through the grader, pass@1 / pass@k by module and difficulty | ✅ done |
| 3 | FastAPI + Postgres + job queue + minimal Next.js UI | ✅ done |
| 4 | AI tutor that gives hints, not answers | |
| 5 | Simulated students, integrity checks, difficulty estimates | |
| 6–7 | GRPO training of a small Qwen model with the grader as reward | |
| 8 | Instructor dashboard, final write-up, demo | |
