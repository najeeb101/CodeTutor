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
- **Done:** Step 0 (environment check, skeleton, tooling, CLAUDE.md, README).
- **In progress:** nothing.
- **Next action:** Step 1 (problem format: schema + loader + 3 example problems). Start in plan mode.

## Decisions log
- 2026-09-28: Develop on WSL2 (Ubuntu 24.04) with Python 3.12, because the Week 1 sandbox needs POSIX features (setrlimit, setsid, killpg).
- 2026-09-28: Use uv with a committed `uv.lock` file, because it gives fast, reproducible installs (everyone gets the exact same package versions).
- 2026-09-28: Store problems as one folder per problem (not one JSON file), because code inside JSON strings is hard to read, review and diff.
- 2026-09-28: Use hatchling as the build backend (a build-time tool only, not a runtime dependency), because it is uv's default and supports the src layout.
- 2026-09-28: Added a one-line smoke test so `make test` really passes (pytest exits with code 5 when it collects no tests).
- 2026-09-28: Every step starts in plan mode, at Najeeb's request.
- 2026-09-28: Exclude `docs/` and `tests/submissions/` from ruff. Ruff 0.16 formats code blocks inside Markdown (which would change KICKOFF.md), and the submissions folder holds deliberately broken code.

## Open questions
- Q3 (Step 2): A total timeout loses partial credit, because the runner writes its result only at the end. Options: (a) total limit ≈ n_tests × per_test + margin; (b) runner streams one result line per test. Leaning toward (b).
- Q4 (Step 2): Student code can catch the per-test alarm exception or replace the SIGALRM handler, and then only the total timeout stops it. Plan: document it as a limitation. The parent must never trust pass/fail flags from the child; it always compares values itself.
- Q5 (Step 2): The token can be read from memory by student code, so it is not a real secret. The real defense is that the child never sees expected outputs. Say this honestly in `docs/grader.md`.
- Q6 (Step 2): RLIMIT_NPROC counts all processes of the Linux user (the VS Code WSL server alone uses many), so a low limit can break every run. Recommendation: don't set it in the subprocess sandbox; rely on killpg now and Docker `--pids-limit` later.
- Q7 (Step 4): `merge_sorted` timing tests cannot detect use of `sort()`, because `sorted(a + b)` runs in C and beats a Python merge. They can only catch O(n²) solutions. Proposed: change the spec text so we don't claim this.
- Q8 (Step 4): Naive `fibonacci(35)` takes ~1.5–3 s, which is too close to the 2 s limit and would be flaky. Proposed: hidden n = 40. Measure on this machine first.
- Q9 (Step 3): `fill_expected.py` rewrites `tests.yaml`, and PyYAML deletes comments. Proposed: no comments in `tests.yaml`, all explanations in the `note` field (no ruamel.yaml dependency).
- Q10 (Step 1): The loader should check that a problem's `id` matches its folder (`03_loops/sum_of_evens` ↔ `cs1.loops.sum_of_evens`).

## Known limitations
- The sandbox is not implemented yet. When it is (Step 2), the subprocess sandbox will NOT be secure: no filesystem or network isolation. Docker is required before untrusted strangers submit code.
