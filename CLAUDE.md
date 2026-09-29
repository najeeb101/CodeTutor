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

## Architecture summary
- **One grader for everything.** `grade(problem, code) -> GradeResult` is used by student submissions,
  model evals and the RL reward. Never create a second grading path.
- Product half: Next.js + Monaco (Wk 3) → FastAPI (Wk 3) → grader queue (Redis + RQ/Arq) + sandbox,
  AI tutor (LiteLLM + RAG + Langfuse, Wk 4), Postgres/Supabase + pgvector (Wk 3).
- Lab half: eval harness (Wk 2), simulated students + integrity + quality estimates (Wk 5),
  dataset builder + GRPO with TRL on Qwen 0.5–1.5B (Wk 6–7).
- Sandbox: Week 1 = subprocess + rlimits (NOT secure). Docker (no network, read-only, non-root,
  limits) required before strangers submit code. Behind a `Sandbox` protocol so backends swap.
- Principles: hidden tests protect the reward; everything is data (structured, versioned);
  problem IDs are stable forever and `version` is bumped when tests change; deterministic grading;
  flags inform humans and never auto-punish; swappable parts behind small interfaces.
- Runner (child) receives only test **inputs**, never expected outputs; the parent compares.

## Repository layout
- `problems/cs1/<NN_module>/<slug>/`: `problem.yaml`, `starter.py`, `solution.py`, `tests.yaml`, `buggy/*.py`
- `src/codetutor/problems/`: schema (pydantic) + loader
- `src/codetutor/grader/`: `runner.py` (child, stdlib only), `compare.py`, `sandbox.py`, `grader.py`, `models.py`
- `scripts/`: `validate_problems.py`, `fill_expected.py`, `grade_cli.py`, `build_dataset.py`
- `tests/`: pytest suite; `tests/submissions/` holds adversarial submissions
- `docs/`: `KICKOFF.md`, `ideas.md`, `problem-format.md`, `grader.md`, `notes/`
- `api/`, `web/`, `tutor/`, `lab/`: placeholders for later weeks
- `dist/`: generated output (gitignored)

## Conventions
- Linux via **WSL2 (Ubuntu 24.04)**, Python 3.12 (project requires >=3.11), **uv** (`uv sync`, `uv run`).
- Week 1 dependencies are pre-approved: `pydantic` v2, `pyyaml`; dev: `pytest`, `pytest-timeout`, `ruff`.
  Anything else: ask first.
- Type hints and short docstrings on all public functions/classes. ruff (line length 100).
- Small functions, clear names, no clever one-liners. `pathlib.Path`. Specific exceptions with helpful
  messages; no bare `except:` (the runner catching `BaseException` from student code is the one
  commented exception).
- No global mutable state unless unavoidable (comment why). Limits/timeouts live in one place and are overridable.
- Tests: real subprocess runs (no mocking the sandbox); whole suite < 60 s; `pytest-timeout` enabled.
- Make targets: `install`, `lint`, `format`, `test`, `validate`, `build`, `all` (= lint + test + validate).

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
- **In progress:** Step 4. Modules 1-3 done (12 problems; 13 in the bank with the `second_largest`
  example). Najeeb's TODO: `fizzbuzz/buggy/stops_before_n.py`.
- **Next action:** Step 4, module 4 (strings). Start in plan mode. Explain in very simple English.

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

## Open questions
- Q10 (Step 4, module 5): "don't mutate the input" (remove_duplicates) can't be checked: the runner only compares the return value. Options: (A) say it in the spec with an honest note, or (B) let the runner also report the inputs after the call (grader change, needs OK). Decide at module 5.

## Known limitations
- The "no code in hints" check is a heuristic (``` fences and lines starting with a Python keyword). Code written inside a sentence is not caught.
- Tests import helpers from `tests/conftest.py` directly (`from conftest import ...`). This works with pytest's default rootdir import mode; move them to a helpers module if that ever breaks.
- The subprocess sandbox is NOT secure: student code can read the user's files and use the network; fork bombs and setsid() escapes are not stopped. Docker is required before strangers submit code (docs/grader.md, threat model).
- Student code can catch the per-test timeout with a bare `except:` in a loop; only the total limit stops it (was Q4).
- The result token is in the child's memory and can be found; the real protection is that expected values never enter the child (was Q5).
- Timeouts depend on machine load, so grading is deterministic except for timeouts under heavy load.
- The validator's "solution < 25% of the time limit" check is measured while 4 gradings run in parallel, so it can be flaky on a busy machine.
- `test_memory_bomb[memory_bomb_growing]` is flaky: once (2026-09-29, in a full `make all`) it gave `timeout` instead of a memory error; it passed 6/6 alone and on the next full run. Allocating memory was slower than the 0.5 s per-test limit under load.
