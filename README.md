# CodeTutor

A CS1 (intro to programming) Python practice platform with instant auto-grading, and an AI lab
built on top of it. Every problem has automatic visible and hidden tests. The same grader scores
student submissions, evaluates AI models (pass rates), and serves as the reward function for
reinforcement-learning training of a small code model.

**Status:** Week 1 of 8 is done (problem bank + auto-grader). Next: Week 2, an eval harness that
runs LLMs through the grader.

## What is in it

| | |
|---|---|
| Problems | 33, in 8 CS1 modules (variables → recursion): 17 easy, 15 medium, 1 hard |
| Tests | 374, of which 242 are hidden |
| Buggy solutions | 97 known-wrong solutions; every problem has at least one bug that only hidden tests catch |
| Test suite | 179 pytest tests, including 27 hostile submissions (infinite loops, memory bombs, `os._exit`, fake results, output floods) |

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

> **⚠️ Security:** the default sandbox is a subprocess with resource limits. It is **not secure**:
> graded code can read your files and use the network. For code you don't trust, use the Docker
> sandbox (`--sandbox docker`, or `DockerSandbox()` in Python): no network, no host files,
> non-root, a process limit. It is much safer, but not a perfect wall (containers share the
> host's kernel). See [docs/grader.md](docs/grader.md#5-threat-model), sections 5 and 6.

## Install and check
```bash
make install    # install dependencies and the package (editable)
make all        # lint + tests + validate every problem
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
- `scripts/`: command-line wrappers for the above, plus the grading CLI
- `tests/`: test suite; `tests/submissions/` holds the hostile submissions
- `docs/`: design docs; `docs/notes/` holds interview notes

## Roadmap
| Week | Deliverable | |
|---|---|---|
| 1 | Problem bank + grader + validator (+ optional Docker sandbox) | ✅ done |
| 2 | Eval harness: LLMs through the grader, pass@1 / pass@k by module and difficulty | next |
| 3 | FastAPI + Postgres + job queue + minimal Next.js UI | |
| 4 | AI tutor that gives hints, not answers | |
| 5 | Simulated students, integrity checks, difficulty estimates | |
| 6–7 | GRPO training of a small Qwen model with the grader as reward | |
| 8 | Instructor dashboard, final write-up, demo | |
