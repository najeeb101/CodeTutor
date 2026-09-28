# KICKOFF: AI Coding Tutor & Auto-Grader (Portfolio Project)

> **Claude Code: read this entire file before doing anything.**
> It is the full brief for this project: who I am, what we're building, why, the architecture,
> the conventions, how I want us to work together, and a step-by-step spec for Week 1.
> When you've read it, reply with (1) a 10-line summary of what you understood,
> (2) any questions or disagreements, and (3) your plan for Step 0. Do not write code until I say "go".

---

## Table of contents

1. About me and why this project exists
2. How we work together (the working protocol)
3. The project: problem, solution, users, scope
4. How this maps to the Scale AI job
5. Architecture (full system, including future weeks)
6. Repository structure
7. Coding conventions and tooling
8. The 8-week plan
9. WEEK 1 SPEC: detailed, step by step
10. Preview of weeks 2–8 (so Week 1 decisions don't block them)
11. Interview-prep habits
12. Session rituals (start and end of every session)
13. Appendix A: the full CS1 problem list
14. Appendix B: example problem, fully written

---

## 1. About me and why this project exists

- I'm **Najeeb**, a senior (4th-year) Computer Science student at Qatar University, specializing in AI/ML. Based in Doha.
- Background: Python, JavaScript, React, Next.js, SQL, TensorFlow, full-stack web, API integration. I built AI automation systems with Python, n8n and the OpenAI API during an internship at Silatha (Amsterdam). I've used Supabase before.
- **Weaker areas I want to grow in:** PyTorch, Hugging Face (transformers, TRL), LLM post-training (SFT, DPO, GRPO, RLHF), evaluation design, sandboxing, data pipelines at scale.
- **Goal:** get hired at **Scale AI** (Global Public Sector team, or similar). My first interview is likely **within 5 months** (from late September 2026).
- The target job includes work like:
  - Build reinforcement learning and post-training data pipelines that power frontier model development
  - Develop evaluation infrastructure that measures model reliability
  - Ship agentic AI applications and the tooling that makes them observable, testable and safe to deploy
  - Ship tools that accelerate the growth of new qualified contributors
  - Build fraud-detection systems that remove bad actors
  - Use models to estimate the quality of tasks and contributors
  - Devise matching algorithms
  - Build efficient UI/UX tooling combined with ML
  - Develop tools to visualize, query and explore data
  - Build a customer service RAG application
  - Integrate a churn prediction model
- **This is a PORTFOLIO project, not a business.** The goal is (a) to learn these skills for real, and (b) to have one strong, well-documented project I can walk through in interviews.
- **Because of that, understanding matters more than speed.** If I can't explain a piece of code in an interview, it's worthless to me. Teach me as we go.

---

## 2. How we work together (the working protocol)

These rules apply to every session. Follow them strictly.

### 2.1 Small steps with checkpoints
- Work in **small, numbered steps**. Each step in Section 9 ends with a **STOP**.
- At every STOP:
  1. Summarize what you did in plain, simple English (I'm not a native speaker; avoid jargon, or explain it when you use it).
  2. List the files you created or changed, one line each on what the file does.
  3. Show me how to run/verify it (exact commands).
  4. Explain the **key design decisions and trade-offs** (what else we could have done, and why we didn't).
  5. Ask me **2–3 short questions** to check I understood the important parts (don't give the answers until I reply).
  6. Wait for my "OK" / "go" before continuing.
- Never do more than one step without stopping, even if the next step seems obvious.

### 2.2 Teach, don't just build
- Before writing a non-trivial file, explain in 3–5 sentences what it will do and why.
- After writing it, point out the 2–3 most important lines/ideas.
- When a concept comes up that matters for the Scale interview (sandboxing, reward functions, reward hacking, evals, pass@k, data quality, etc.), give me a short "📌 Interview note" box explaining it in simple words and how I'd talk about it.
- **Leave me TODOs.** About once per step, leave a small, clearly marked piece for me to implement myself:
  ```python
  # TODO(najeeb): implement the "unordered" comparison mode.
  # Hint: think about how to compare two lists ignoring order when items may not be sortable.
  ```
  Then stop and let me do it. When I say I'm done, review my code honestly (bugs, style, edge cases) and don't rewrite it unless I ask.
- If I ask "why", give me the real reason, including trade-offs and weaknesses. Don't just agree with me. If you think I'm making a bad decision, say so clearly and explain why.

### 2.3 Ask before big decisions
- **Ask before:** adding any dependency not pre-approved (see 7.2), changing the architecture, changing the problem schema after it's agreed, deleting files, renaming modules, or doing anything irreversible.
- **Don't ask about:** small implementation details, variable names, internal helper functions. Use good judgment.
- If something in this document is wrong, unclear, or contradicts itself, **stop and ask**. Don't guess silently.

### 2.4 Scope discipline
- **Only work on the current week's scope.** Week 1 = problem bank + grader. No API, no frontend, no database, no LLM calls, no Docker (unless we reach the optional step), no ML.
- If you have an idea for later weeks, add it to `docs/ideas.md` instead of building it.

### 2.5 Honesty
- If something doesn't work, say so. Never claim tests pass without running them. Show the actual output.
- If you're unsure about something (library behavior, OS differences), say so and verify by running code.
- Mark limitations clearly in code comments and docs (e.g. "this is NOT a secure sandbox").

### 2.6 Git
- `git init` in Step 0. Commit at the end of every completed step.
- Commit message format: `<area>: <what changed>` e.g. `grader: add per-test timeout and token-protected output`.
- Work on `main` for Week 1 (it's a solo project). Never force-push. Never rewrite history.
- Never commit secrets. `.env` goes in `.gitignore` from day one.

### 2.7 Project memory (CLAUDE.md)
- `CLAUDE.md` is the permanent memory for this project. You read it at the start of every session.
- In Step 0, create it from this KICKOFF file (condensed but complete: project, architecture, conventions, working protocol, plan).
- It must contain these living sections, which you update at the end of **every** session:
  - **Status:** what's done, what's in progress, what's next (the very next action).
  - **Decisions log:** dated entries, one per decision: `2026-09-28: Problems stored as one folder per problem (not one JSON file) because code in JSON strings is hard to read and review.`
  - **Open questions:** things we haven't decided yet.
  - **Known limitations:** e.g. sandbox is not secure yet.
- Keep `KICKOFF.md` in the repo unchanged as the original brief (move it to `docs/KICKOFF.md` in Step 0).

---

## 3. The project: problem, solution, users, scope

### 3.1 Problem statement
CS students get stuck on programming problems with no one to help them in the moment, so they either give up or copy full answers from AI tools. Instructors only find out who's struggling when it's too late (midterms).

For students:
- They practice at night/weekends when TAs aren't available and get stuck for hours.
- ChatGPT-style tools write the full solution, so they submit it, learn nothing, and fail exams.
- Homework feedback comes days later.

For instructors:
- In classes of 100+, they can't see who's struggling until grades come out.
- Grading programming assignments by hand takes hours.
- Copied or AI-generated code is hard to detect.

### 3.2 Solution
A practice platform where:
- students solve problems and get **instant auto-grading**,
- an **AI tutor gives hints, not answers**,
- the platform **flags suspicious submissions** (copied, pasted, AI-generated) as signals for a human, never as automatic punishment,
- instructors get a **dashboard with early warnings** about students at risk.

### 3.3 The hidden second purpose (the Scale angle)
Every problem has automatic tests, so any code, from a student or an AI model, can be **graded automatically**. That makes the platform an **AI evaluation and training system**:
- **Evaluation:** run AI models on the problems and measure their pass rates.
- **RL training:** the grader's score is a **reward**. A small model tries each problem several times, the grader scores the attempts, and GRPO trains the model to prefer passing attempts.
- **Preference data:** students rate tutor hints 👍/👎, which gives preference pairs usable for DPO.

### 3.4 Users (personas)
- **Student** (e.g. Sara, 1st-year engineering student taking intro Python): wants to get unstuck fast and pass the course.
- **Instructor** (e.g. Dr. Khalid, teaching 3 sections of 120 students): wants to see who's struggling, save grading time, and trust that work is honest.
- **AI researcher** (me, in the AI lab): wants to evaluate and train models on the problem bank.

### 3.5 First course
**Intro to Programming (CS1) in Python.** 8 modules, ~33 problems (full list in Appendix A). Chosen because intro courses have the biggest classes, the most struggling students, and problems with clear right answers that are easy to auto-grade.

### 3.6 Out of scope (for the whole project)
- Real business concerns (pricing, sales, legal, local data hosting)
- Languages other than Python
- Full course management (like Blackboard/Moodle), exams, mobile apps
- Selling data
- Anything requiring real student data. We use me, a few friends, and **simulated students**.

### 3.7 Competitors (for context and for interview talking points)
Codio (Codio Coach AI assistant), CodeGrade (autograder + AI assistant add-on), zyBooks/zyLabs, Gradescope, Harvard's CS50 Duck, and general AI assistants with study modes. Our project doesn't try to beat them as a product; it's a small version of this kind of system whose real purpose is the eval/training pipeline on top.

---

## 4. How this maps to the Scale AI job

| Job bullet | Where it lives in this project | Depth |
|---|---|---|
| RL / post-training data pipelines | Dataset builder + GRPO training with grader as reward (Wk 6–7) | **Deep** |
| Evaluation infrastructure | Eval harness: models × problems → pass rates by topic/difficulty (Wk 2) | **Deep** |
| Agentic apps, observable/testable/safe | AI tutor with tools, guardrails, Langfuse tracing (Wk 4) | Medium |
| Contributor growth tools | Student onboarding / placement quiz / problem recommendations | Light |
| Fraud detection | Integrity checks: code similarity, paste detection, speed (Wk 5) | **Deep** |
| Quality estimation of tasks & contributors | Problem difficulty + student skill estimates (Wk 5) | Medium |
| Matching algorithms | Recommending the next problem at the right difficulty | Light |
| Efficient UI/UX + ML | Student editor + instructor dashboard | Light |
| Tools to visualize/query data | Instructor dashboard, eval results explorer | Light |
| Customer service RAG | Tutor RAG over course notes | Medium |
| Churn prediction | Early-warning model (at-risk students) | Light |

**Rule:** build three parts deeply (grader + evals, RL pipeline, integrity/quality), the rest lightly. In interviews they'll dig deep into one or two things.

---

## 5. Architecture

### 5.1 The big idea
Two halves sharing one core:
- **The product:** problems, editor, AI tutor, dashboard.
- **The AI lab:** evaluation, dataset building, GRPO training.
- **The shared core is the grader.** `grade(problem, code) -> GradeResult` is used by (1) student submissions, (2) model evaluation, and (3) the RL reward function. Same code, same tests, same scoring. This is the #1 design principle. Never create a second, different grading path.

### 5.2 Diagram
```
                     ┌──────────────────────────────┐
                     │ Frontend (Next.js + Monaco)  │   Week 3+
                     └──────────────┬───────────────┘
                                    │
                     ┌──────────────▼───────────────┐
                     │ API (FastAPI)                │   Week 3+
                     └──┬────────────┬───────────┬──┘
                        │            │           │
          ┌─────────────▼──┐  ┌──────▼─────┐  ┌──▼──────────────┐
          │ GRADER ⭐       │  │ AI Tutor   │  │ Postgres +      │
          │ queue + sandbox│  │ LLM + RAG  │  │ pgvector        │
          │ Week 1         │  │ Week 4     │  │ Week 3+         │
          └──────▲─────────┘  └─────┬──────┘  └──▲──────────────┘
                 │                  │ traces     │ jobs
                 │            ┌─────▼──────┐  ┌──┴──────────────┐
                 │            │ Langfuse   │  │ Integrity,      │
                 │            │ Week 4     │  │ quality, early  │
                 │            └────────────┘  │ warning  Week 5 │
                 │                            └─────────────────┘
   ┌─────────────┴────────────────────────────────────────────────┐
   │ AI LAB: simulated students → eval harness → dataset builder →│
   │ GRPO training → re-evaluate            Weeks 2, 5, 6–7       │
   └──────────────────────────────────────────────────────────────┘
```

### 5.3 Components and technology choices (with reasons)
| Component | Tech | Why |
|---|---|---|
| Frontend | Next.js + React + Monaco editor | I already know React/Next; Monaco is the VS Code editor |
| API | FastAPI | Python everywhere → API, grader and AI lab share code |
| Database | Postgres (Supabase) + pgvector | I know Supabase; pgvector avoids a separate vector DB |
| Grader queue | Redis + a worker (RQ or Arq; decide in Wk 3) | Grading can be slow; don't block API requests |
| Sandbox | Week 1: subprocess + resource limits. Later: Docker (no network, read-only FS, non-root, CPU/mem limits) | Start simple, harden later |
| LLM access | LiteLLM | Swap OpenAI / Claude / Gemini / local models with one setting; comparing models is itself an eval |
| Tracing | Langfuse | Observability for the tutor: prompts, retrieval, cost, latency, guardrail results |
| ML training | PyTorch + Hugging Face transformers + TRL (GRPOTrainer, DPOTrainer) | Industry standard for post-training |
| Small model | Qwen2.5 / Qwen3 0.5B–1.5B (instruct) | Fits free Colab/Kaggle GPUs |
| Experiment tracking | Weights & Biases (free for students) | Track training runs and eval results |
| Hosting (later) | Vercel (frontend), Supabase (DB), small VPS (API + grader worker, since Docker needs a real server) | Cheap |

### 5.4 Main data flows (future weeks, for context)
- **Student submits:** editor → API → queue → sandbox runs tests → results saved → integrity checks → student sees results.
- **Student asks for a hint:** question + code → retrieve relevant course notes → LLM writes hint → guardrail checks it doesn't leak the solution → traced → student sees and rates it.
- **Training loop:** problems → small model generates N attempts each → grader scores each (reward) → GRPO update → eval harness re-tests → report pass rate before vs after.

### 5.5 Key design principles
1. **One grader** for everything (see 5.1).
2. **Hidden tests protect the reward.** Models (and students) can overfit to visible tests ("reward hacking"). Grade on hidden tests too, and never show hidden inputs/outputs to students or to the model being trained.
3. **Everything is data.** Every submission, test result, hint and rating is saved in a structured, versioned format that can later become eval or training data.
4. **Problems are versioned content.** A problem's ID never changes. If tests change, bump the problem's `version`. Eval results must record which problem versions they used.
5. **Deterministic grading.** The same code + same problem version must always produce the same result (except timeouts under heavy load; note this limitation).
6. **Honest signals, human decisions.** Integrity flags and risk scores are shown to humans with reasons; they never trigger automatic penalties.
7. **Swappable parts.** The model provider, the sandbox backend (subprocess vs Docker) and the storage layer should sit behind small interfaces so they can change without rewriting callers.

---

## 6. Repository structure

Create this in Step 0 (empty folders get a `.gitkeep`; future-week folders get a one-line README saying which week they're for).

```
codetutor/
├── CLAUDE.md                     # project memory (living)
├── README.md                     # public-facing project README
├── pyproject.toml
├── .gitignore
├── .env.example                  # empty for now; future API keys go here
├── Makefile                      # shortcuts: make test, make lint, make validate
├── docs/
│   ├── KICKOFF.md                # this file, unchanged
│   ├── ideas.md                  # ideas for later weeks
│   ├── problem-format.md         # how a problem is defined (Step 1)
│   ├── grader.md                 # how the grader works, limits, threat model (Step 2)
│   └── notes/                    # my interview notes per week (see Section 11)
├── problems/
│   └── cs1/
│       ├── 01_variables/
│       │   └── celsius_to_fahrenheit/
│       │       ├── problem.yaml
│       │       ├── starter.py
│       │       ├── solution.py
│       │       ├── tests.yaml
│       │       └── buggy/
│       │           ├── off_by_one.py
│       │           └── ...
│       ├── 02_conditions/
│       └── ... (08_recursion)
├── src/
│   └── codetutor/
│       ├── __init__.py
│       ├── problems/             # schema (pydantic models) + loader
│       │   ├── __init__.py
│       │   ├── schema.py
│       │   └── loader.py
│       └── grader/
│           ├── __init__.py
│           ├── runner.py         # runs INSIDE the sandbox process
│           ├── compare.py        # output comparison modes
│           ├── sandbox.py        # launches the runner with limits (subprocess backend)
│           ├── grader.py         # public API: grade(), grade_many()
│           └── models.py         # GradeResult, TestResult dataclasses/pydantic models
├── scripts/
│   ├── validate_problems.py
│   ├── fill_expected.py
│   ├── grade_cli.py
│   └── build_dataset.py          # exports problems to dist/problems.jsonl
├── tests/
│   ├── conftest.py
│   ├── submissions/              # adversarial & example submissions for grader tests
│   ├── test_compare.py
│   ├── test_runner.py
│   ├── test_grader.py
│   ├── test_loader.py
│   └── test_problem_bank.py      # runs the validator over all problems in CI
├── dist/                         # generated files (gitignored)
├── api/                          # Week 3 (placeholder README only)
├── web/                          # Week 3 (placeholder README only)
├── tutor/                        # Week 4 (placeholder README only)
└── lab/                          # Weeks 2, 5–7: evals, simulated students, training (placeholder README only)
```

**Why one folder per problem instead of one JSON file:** code inside JSON strings (escaped newlines and quotes) is hard to read, review and diff. Real `.py` files can be linted, run, and opened in an editor. The build script (`scripts/build_dataset.py`) compiles everything into a single `dist/problems.jsonl` for the grader/eval/training pipelines. 📌 This mirrors how real data pipelines separate human-editable source from machine-friendly build output.

---

## 7. Coding conventions and tooling

### 7.1 Environment
- **First, check my OS** (run a command, don't assume). The Week 1 sandbox uses POSIX features (`resource.setrlimit`, `os.setsid`, `os.killpg`).
  - macOS / Linux: fine.
  - **Windows: stop and tell me.** Recommend WSL2 (Ubuntu) and help me set it up before continuing. Don't write a Windows-specific sandbox.
- Python **3.11+** (check with `python3 --version`).
- Package manager: **uv** if installed (check with `uv --version`); if not, ask whether I want to install it or use `python -m venv` + pip.
- Install the project in editable mode so `import codetutor` works from scripts and tests.

### 7.2 Pre-approved dependencies (Week 1)
- Runtime: `pydantic` (v2, schema validation), `pyyaml`.
- Dev: `pytest`, `pytest-timeout`, `ruff`.
- **Anything else: ask first.** In particular, do NOT add Docker SDK, FastAPI, Redis, torch, transformers or any LLM SDKs in Week 1.

### 7.3 Style
- Type hints on all public functions. Docstrings on all public functions/classes (short, plain English).
- `ruff` for linting and formatting; configure in `pyproject.toml` (line length 100).
- Small functions, clear names, no clever one-liners. Readability > cleverness. I must be able to explain every line.
- No global mutable state except where unavoidable (e.g. the runner's result token), and comment why.
- Errors: raise specific exceptions with helpful messages. Never use bare `except:` in library code. (The runner is the one exception: it must catch `BaseException` from student code. Comment why.)
- Use `pathlib.Path`, not string paths.
- Constants (timeouts, limits) live in one place (`grader/models.py` or a `config.py`) and are overridable.

### 7.4 Makefile targets
```
make install    # install deps + editable package
make lint       # ruff check + ruff format --check
make format     # ruff format
make test       # pytest
make validate   # python scripts/validate_problems.py
make build      # python scripts/build_dataset.py
make all        # lint + test + validate
```

### 7.5 Testing
- Every module gets tests. Tests must be fast (whole suite < 60s).
- Use `pytest-timeout` so a broken sandbox can't hang the test suite.
- Tests for the grader use real subprocess runs (no mocking the sandbox; the whole point is testing it).

---

## 8. The 8-week plan

| Week | Deliverable | Scale bullets covered |
|---|---|---|
| **1** | **Problem bank (~33 CS1 problems) + grader + validator** | foundation for all |
| 2 | Eval harness: 2–3 LLMs attempt all problems through the grader; pass@1, pass@k by module/difficulty; results report | Evaluation |
| 3 | FastAPI + Postgres + queue + minimal Next.js UI (problem list, editor, submit, results) | UI/UX |
| 4 | AI tutor: LiteLLM, RAG over course notes, hint-not-answer guardrail, Langfuse tracing, hint ratings | Agentic/observable, RAG |
| 5 | Simulated students + integrity checks (similarity, paste, speed) + difficulty/skill estimates | Fraud, quality estimation |
| 6–7 | Dataset builder (JSONL) + GRPO on Qwen 0.5–1.5B with grader reward + re-eval; optional DPO on hint ratings | RL / post-training pipelines |
| 8 | Instructor dashboard, light early-warning model, README, architecture diagram, demo video | Visualization, churn |

If time runs short, the safe cuts are: dashboard polish, early warning, DPO. Never cut: grader, evals, GRPO.

---

## 9. WEEK 1 SPEC

### Week 1 goal
A validated bank of ~33 CS1 Python problems and a robust, tested auto-grader that can grade any Python submission against any problem and return a structured result with a 0–1 reward. No UI, no API, no AI.

---

### STEP 0: Environment, skeleton, project memory

**Tasks**
1. Check OS, Python version, uv availability, git availability. Report results. (Stop if Windows; see 7.1.)
2. `git init`. Create `.gitignore` (Python, venv, `.env`, `dist/`, `.pytest_cache`, `.ruff_cache`, `__pycache__`, `.DS_Store`, `wandb/`, model checkpoints `*.safetensors`, `*.bin`).
3. Create the folder structure from Section 6 (placeholders for future weeks).
4. Move this file to `docs/KICKOFF.md`.
5. Create `pyproject.toml` (project name `codetutor`, src layout, Python >=3.11, pre-approved deps, ruff + pytest config).
6. Create the `Makefile`.
7. Create `CLAUDE.md` (see 2.7). Include: 1-paragraph project summary, the working protocol (condensed), architecture summary, conventions, the 8-week plan, and the living sections (Status, Decisions log, Open questions, Known limitations).
8. Create a first `README.md`: project name, one-paragraph description, "status: Week 1 in progress", how to install and run tests.
9. Install deps; run `make lint` and `make test` (0 tests is fine) to prove the setup works.
10. Commit: `chore: project skeleton, tooling and CLAUDE.md`.

**STOP.** Show me the tree, `CLAUDE.md`, and the command outputs.

---

### STEP 1: Problem format (schema + loader)

**1.1 The files of a problem**
Each problem is a folder: `problems/cs1/<NN_module>/<problem_slug>/`

- `problem.yaml`: metadata and description
- `starter.py`: what the student sees initially (function signature + docstring + `pass`)
- `solution.py`: the reference solution (never shown to students)
- `tests.yaml`: test cases
- `buggy/*.py`: 1–3 plausible **wrong** solutions (typical beginner mistakes). Used to prove the tests are strong enough, and later for simulated students and eval baselines.

**1.2 `problem.yaml` fields**
| Field | Type | Rules |
|---|---|---|
| `id` | str | Globally unique, stable forever. Format `cs1.<module_slug>.<problem_slug>` e.g. `cs1.loops.sum_of_evens` |
| `version` | int | Starts at 1. Bump whenever tests or the expected behavior change |
| `title` | str | Human-readable, e.g. "Sum of Even Numbers" |
| `module` | int | 1–8 |
| `module_name` | str | e.g. "Loops" |
| `order` | int | Position within the module |
| `difficulty` | enum | `easy` \| `medium` \| `hard` |
| `concepts` | list[str] | From a fixed vocabulary (define it in `schema.py`): e.g. `arithmetic`, `conditionals`, `for_loops`, `while_loops`, `strings`, `lists`, `dicts`, `functions`, `recursion`, `sorting`, `searching`, `edge_cases`, `efficiency`. Used later for per-concept skill tracking |
| `function_name` | str | Must match a function defined in `starter.py` and `solution.py` |
| `description_en` | str (multiline) | Clear statement, input/output description, constraints, 1–2 examples |
| `description_ar` | str \| null | null for now (Arabic comes later, optional) |
| `hints` | list[str] | Exactly 3 progressive hints: (1) nudge in the right direction, (2) more specific approach, (3) near-pseudocode but NOT code. Used as fallback hints and as a reference for evaluating the AI tutor later |
| `time_limit_s` | float | Optional per-test override (default 2.0) |
| `author` | str | "najeeb" or "claude" (whoever wrote it) |

**1.3 `tests.yaml` format**
```yaml
tests:
  - id: t01
    input: [10]          # list of positional arguments
    expected: 30
    hidden: false
    compare: exact       # exact | unordered | float
    note: "basic case"   # optional, for humans
  - id: t02
    input: [0]
    expected: 0
    hidden: true
    compare: exact
    note: "edge: zero"
```
Rules:
- `input` is always a **list of arguments**, even for one argument (`[10]`, not `10`).
- Inputs and expected outputs must be **JSON-compatible** (numbers, strings, bools, null, lists, dicts with string keys). No tuples, sets or custom objects. If a function "returns a tuple", the problem must say it returns a **list**.
- Test IDs unique within the problem.
- Minimum per problem: **8 tests**, of which **≥ 3 visible** and **≥ 3 hidden**, and hidden tests must include **edge cases** (empty input, zero, negative numbers, single element, duplicates, very large values as appropriate).
- **Expected outputs are never typed by hand.** You write inputs; `scripts/fill_expected.py` fills `expected` by running `solution.py`. (We still review them by eye.)

**1.4 Comparison modes** (`compare.py`)
- `exact`: equality after normalizing tuples → lists recursively.
- `unordered`: the actual and expected lists contain the same items with the same counts, in any order. Must work even when items aren't sortable (e.g. lists of lists, mixed types). *(Candidate TODO for me.)*
- `float`: `math.isclose(rel_tol=1e-6, abs_tol=1e-9)`, applied **recursively** inside lists (so a list of floats works). Bools are not floats: `True` must not equal `1.0` here.
- Also: in `exact` mode, `True` vs `1` must count as **different** (Python says `True == 1`, but a function that should return a count must not pass by returning `True`). Handle bool vs int explicitly. 📌 This kind of subtle equality bug is exactly how reward functions get fooled.

**1.5 Schema and loader** (`src/codetutor/problems/`)
- `schema.py`: pydantic models `Problem`, `TestCase`, enums, and the concept vocabulary. Validation rules from 1.2–1.3 that can be checked statically (unique IDs, min test counts, `input` is a list, etc.) go here.
- `loader.py`:
  - `load_problem(path: Path) -> Problem`: reads the folder, loads YAML and the `.py` files as strings (starter, solution, buggy solutions as `{name: code}`).
  - `load_all(root: Path = Path("problems")) -> list[Problem]`: sorted by module then order.
  - `get_problem(problem_id: str) -> Problem`
  - Clear error messages that include the file path when something is invalid.
- `Problem` also needs a method or helper to produce the **student view** (no solution, no buggy code, no hidden tests) vs the **internal view** (everything).

**1.6 Deliverables**
- Schema + loader + tests (`test_loader.py`: valid problem loads; each kind of invalid problem gives a clear error).
- `docs/problem-format.md` explaining the format in simple English with the example.
- **3 complete example problems** (one easy, one medium from different modules, plus the one in Appendix B), including buggy solutions.
- Commit.

**STOP.** Show me one problem folder in full, and explain the schema decisions.

---

### STEP 2: The grader

This is the most important step of the week. Take your time. Explain everything.

**2.1 Public API** (`src/codetutor/grader/grader.py`)
```python
def grade(
    problem: Problem,
    code: str,
    *,
    reveal_hidden: bool = False,
    limits: Limits | None = None,
) -> GradeResult: ...

def grade_many(
    jobs: list[tuple[Problem, str]],
    *,
    workers: int = 4,
    reveal_hidden: bool = True,
) -> list[GradeResult]: ...
```
- `grade` is the single entry point used by students (later via API), evals and RL.
- `grade_many` grades many submissions in parallel (process pool or thread pool launching subprocesses) and returns results **in the same order** as the input. Needed from Week 2 onward for evals (hundreds of model outputs).

**2.2 Result models** (`models.py`)
```
Limits:
  per_test_timeout_s: float = 2.0     # per-problem override from problem.yaml
  total_timeout_s: float = 20.0
  memory_mb: int = 512
  max_output_bytes: int = 64_000      # captured student stdout, truncated
  max_file_mb: int = 1

TestResult:
  test_id: str
  hidden: bool
  status: passed | wrong_answer | runtime_error | timeout
  error: str | None                   # short, e.g. "IndexError: list index out of range"
  input / expected / actual: only included when visible OR reveal_hidden=True
  duration_ms: float

GradeResult:
  problem_id: str
  problem_version: int
  status: accepted | wrong_answer | runtime_error | timeout | compile_error | crashed
  passed: int
  total: int
  reward: float                       # passed / total, rounded to 4 decimals; 0.0 for compile_error/crashed/total timeout
  tests: list[TestResult]
  compile_error: str | None
  stdout: str                         # student's print output (truncated)
  duration_ms: float
  grader_version: str                 # e.g. "0.1.0", bump when grading logic changes
```
- Must be **JSON-serializable** (`to_dict()` / `model_dump()`); we'll store these in files and a DB later.
- **Overall status rule:** if all tests pass → `accepted`. Otherwise, the status of the **first failing test in test order** (standard online-judge behavior). `compile_error` = the code failed to load or the function is missing. `crashed` = the sandbox process died without producing a valid result. `timeout` at the top level also covers exceeding the total time limit.

**2.3 The runner** (`runner.py`, runs INSIDE the child process)
- Reads one JSON job from **stdin**: `{token, code, function_name, tests: [{id, input}], per_test_timeout_s}`.
  - Note: the runner receives only **inputs**, never expected outputs. Comparison happens in the parent. This way student code can't read the expected answers from memory. 📌 Interview point.
- Redirects `sys.stdout` and `sys.stderr` to in-memory buffers so student prints don't mix with the result. Truncate captured output.
- `exec`s the student code in a fresh namespace dict (`{"__name__": "__submission__"}`).
  - Any exception while loading → compile_error with a short message (last line of the traceback). Include SyntaxError line numbers.
  - Function missing or not callable → compile_error: `Function 'sum_of_evens' was not defined.`
- For each test:
  - Deep-copy the input (so a student mutating the input list can't affect later tests), e.g. via `json.loads(json.dumps(...))`.
  - Enforce the per-test timeout with `signal.setitimer(signal.ITIMER_REAL, ...)` and a SIGALRM handler raising a private exception. Always cancel the timer afterwards (use try/finally).
  - Catch `RecursionError` separately with a clear message.
  - Catch `BaseException` for everything else (student code may raise `SystemExit` or `KeyboardInterrupt`); record `runtime_error` with a short message. Comment why BaseException is necessary here.
  - Record the **actual output** in a JSON-safe form: if the value isn't JSON-serializable, convert it (tuples → lists; sets → mark as a type error; other objects → `repr` string and it will fail comparison). Also record `duration_ms`.
- At the end, write to the **real** stdout: a newline + the **token** + the JSON result. The parent parses only the text after the **last** occurrence of the token.
- Keep the runner **standard-library only**. It must not import anything from `codetutor` (it runs in isolated mode).

**2.4 The sandbox** (`sandbox.py`, subprocess backend)
- Launch: `[sys.executable, "-I", "-S"?, path/to/runner.py]`. Decide whether `-S` (skip site) is safe; explain the choice. `-I` isolates from user site-packages and env vars.
- `cwd`: a fresh `tempfile.TemporaryDirectory()`, deleted after.
- `env`: empty dict (or minimal, e.g. `{"PYTHONHASHSEED": "0"}` for determinism; explain).
- `preexec_fn` (POSIX) applies:
  - `RLIMIT_AS` (memory), `RLIMIT_CPU` (seconds, slightly above total timeout), `RLIMIT_FSIZE` (max file size), `RLIMIT_NOFILE` (open files, e.g. 64)
  - `os.setsid()` so the child gets its own process group.
  - Consider `RLIMIT_NPROC` carefully: it's per-user, not per-process, so it may break things in some environments. Explain the trade-off and decide with me.
- Wall-clock timeout via `communicate(timeout=total_timeout_s)`. On timeout: kill the **whole process group** (`os.killpg(pgid, SIGKILL)`), then collect. Return a `timeout` result.
- If stdout doesn't contain the token → `crashed` with the last line of stderr (e.g. MemoryError, killed by signal). Detect negative return codes (killed by signal) and report which signal.
- Put the sandbox behind a small interface (`class Sandbox(Protocol): def run(job) -> RawResult`) so a `DockerSandbox` can replace it later without changing `grade()`.
- **Threat model** (write it in `docs/grader.md`): what this sandbox protects against (infinite loops, memory bombs, output spam, crashing the grader, faking results, mutating inputs across tests) and what it does **NOT** protect against (reading files the user can read, network access, forking many processes if NPROC isn't limited, determined attackers). Conclusion: fine for me, friends and AI-model outputs on my machine; **Docker required before strangers submit code.**

**2.5 Adversarial test submissions** (`tests/submissions/` + `tests/test_grader.py`)
Use a simple problem (e.g. `sum_of_evens`) as the target. Each of these must produce the expected result:

| Submission | Expected status | Notes |
|---|---|---|
| correct solution | accepted, reward 1.0 | |
| off-by-one bug | wrong_answer, 0 < reward < 1 | partial credit works |
| returns None (forgot return) | wrong_answer | |
| raises IndexError on some tests | runtime_error on those tests | other tests still graded |
| syntax error | compile_error | message includes line number |
| function misspelled | compile_error | clear message |
| top-level code raises | compile_error | |
| infinite loop in function | timeout on that test | other tests still run if time allows |
| infinite loop at top level | timeout (total) | grader doesn't hang |
| deep recursion | runtime_error "RecursionError..." | |
| memory bomb (`x = [0] * 10**10` or growing list) | runtime_error (MemoryError) or crashed | grader survives |
| prints 10 MB of text | graded normally, stdout truncated | |
| prints a fake result with a fake token | graded normally (fake ignored) | |
| writes to `sys.__stdout__` directly | graded normally | |
| calls `sys.exit(0)` inside the function | runtime_error | |
| calls `os._exit(0)` | crashed | |
| mutates the input list | later tests unaffected | |
| returns `True` where an int is expected | wrong_answer | bool vs int check |
| returns a tuple where a list is expected | passes (normalized) | |
| writes a 100 MB file | runtime_error or crashed (FSIZE) | |
| sleeps 30s at top level | timeout (total) | |
| spawns a subprocess that runs forever | grader kills whole process group, returns | check no zombie left |

Also test: `grade_many` returns results in input order; `reveal_hidden=False` hides hidden test details; results are JSON-serializable; the same submission graded twice gives identical results (except durations).

**2.6 Deliverables**
- `runner.py`, `compare.py`, `sandbox.py`, `grader.py`, `models.py` + tests (all passing).
- `docs/grader.md`: how it works (diagram of parent ↔ child), limits, statuses, threat model, known limitations.
- Commit(s).

**STOP.** Walk me through a full grading run step by step, from `grade()` to the final result. Give me the 📌 interview notes on: sandboxing, why expected outputs never enter the child, why the token, why hidden tests, partial credit as a reward.

---

### STEP 3: Validator, fill-expected, CLI, dataset build

**3.1 `scripts/fill_expected.py`**
- `python scripts/fill_expected.py problems/cs1/03_loops/sum_of_evens` (or `--all`)
- Runs `solution.py` on every test input **through the grader's sandbox** (not a plain import, since the reference solution is code too) and writes `expected` into `tests.yaml`, preserving order, IDs, comments/notes as much as possible.
- `--check` mode: doesn't write; fails if any stored expected value differs from what the solution produces.

**3.2 `scripts/validate_problems.py`**
Checks every problem and prints a clear report. A problem is **valid** only if ALL of these hold:
1. Schema is valid (pydantic).
2. `id` unique across the bank; `function_name` defined in starter and solution.
3. `starter.py` runs without error but **fails** at least one test (it's just `pass`).
4. `solution.py` gets **reward 1.0** (all tests pass).
5. **Every buggy solution fails at least one test** (reward < 1.0). If a buggy solution passes everything, the tests are too weak → error. 📌 This is a simple form of *mutation testing*: it measures whether the tests can catch realistic mistakes.
6. At least one buggy solution fails **only hidden tests** in at least ~half the problems (so visible tests alone don't catch everything). Report as a warning, not an error.
7. Test count rules from 1.3.
8. Reference solution runs each test in < 25% of the time limit (so a reasonable student solution won't time out by accident).
9. `hints` has exactly 3 entries and none contains code blocks.
10. Expected values match `fill_expected --check`.

Output example:
```
cs1.loops.sum_of_evens        ✅ valid   (10 tests: 4 visible, 6 hidden; 3/3 buggy caught)
cs1.strings.is_palindrome     ❌ buggy/ignores_case.py passed all tests → add a test with mixed case
...
Summary: 32 valid, 1 invalid
```
Exit code non-zero if anything is invalid (so it can run in CI later).

**3.3 `scripts/grade_cli.py`**
```
python scripts/grade_cli.py cs1.loops.sum_of_evens path/to/my_solution.py [--reveal-hidden] [--json]
```
Human-readable output: overall status, reward, per-test table (✅/❌, id, visible/hidden, error or expected vs actual for visible tests), student stdout. `--json` prints the raw `GradeResult`.

**3.4 `scripts/build_dataset.py`**
- Builds `dist/problems.jsonl`: one line per problem with all fields (internal view) + `content_hash` (hash of all problem files) so evals can record exactly which content they used.
- Also `dist/problems_student.jsonl` (student view, no solutions/hidden tests).
- 📌 This is the first "data pipeline" artifact; Week 2 evals and Week 6 RL will read from it.

**3.5 `tests/test_problem_bank.py`**: runs the validator logic over all problems inside pytest.

Commit. **STOP.** Show me the validator report on the 3 example problems and a CLI run.

---

### STEP 4: The full problem bank

- Write the problems from **Appendix A**, **one module at a time** (8 batches).
- For each problem: `problem.yaml` (clear description with examples and constraints), `starter.py`, `solution.py` (clean, idiomatic, the way a good TA would write it), `tests.yaml` (inputs only; then run `fill_expected.py`), and **2–3 buggy solutions** representing realistic beginner mistakes (off-by-one, wrong edge case, wrong comparison, forgetting empty input, mutating input, inefficient solution that times out where relevant, etc.). Name buggy files by the mistake: `off_by_one.py`, `ignores_empty.py`, `naive_exponential.py`.
- Descriptions: write for a first-year student. Simple English. State input types, output type, and constraints explicitly. Include 1–2 examples that match visible tests.
- After each batch: `fill_expected`, `validate`, `make test`, commit (`problems: add module 3 (loops)`).
- **STOP after each module** and give me a short table: problem, difficulty, #tests, #buggy, anything notable. Occasionally ask me to write one of the buggy solutions or a hidden edge-case test myself (TODO).

---

### STEP 5 (OPTIONAL, only if Steps 0–4 are done and I say so): Docker sandbox
- `DockerSandbox` implementing the same `Sandbox` interface.
- Container: slim Python image, `--network none`, `--read-only` with a small tmpfs, non-root user, `--memory`, `--cpus`, `--pids-limit`, no capabilities (`--cap-drop ALL`), `--security-opt no-new-privileges`.
- Same adversarial tests must pass with both backends (parametrize the tests).
- Measure and report overhead per submission (subprocess vs Docker). 📌 Interview point: security vs speed trade-off, and why you'd keep warm containers or use something like gVisor/Firecracker at scale.

---

### Week 1 definition of done
- [ ] ~33 problems, all passing the validator, each with ≥ 8 tests and 2–3 buggy solutions
- [ ] Grader passes all adversarial tests in 2.5
- [ ] `make all` passes (lint + tests + validate)
- [ ] `dist/problems.jsonl` builds
- [ ] `docs/problem-format.md` and `docs/grader.md` written
- [ ] README updated (what it is, how to run, how to grade a solution)
- [ ] `CLAUDE.md` Status + Decisions log updated
- [ ] `docs/notes/week1.md` written with me (see Section 11)

---

## 10. Preview of weeks 2–8 (design with these in mind now)

Don't build any of this in Week 1, but make sure Week 1 decisions don't block it.

- **Week 2, eval harness** (`lab/evals/`): for each model (via LiteLLM) and each problem, send the student-view description + starter code, extract the code from the response, grade with `grade_many(reveal_hidden=True)`. Metrics: pass@1, pass@k (unbiased estimator with n samples per problem), mean reward, results by module/difficulty/concept, common failure types (compile_error vs wrong_answer vs timeout). Save every raw response and GradeResult to JSONL with model name, temperature, prompt version, problem version, grader version, timestamp. Output a Markdown/HTML report. → *Needs: stable IDs, versions, JSON-serializable results, fast parallel grading, student view.*
- **Week 3, API/DB/UI:** FastAPI endpoints (list problems, get problem (student view), submit, get result), Postgres tables (users, problems, submissions, test_results, …), queue + worker calling `grade()`. Next.js pages. → *Needs: grader behind a clean function; results serializable.*
- **Week 4, tutor:** LiteLLM; RAG over course notes (write short notes per module); system prompt enforcing hints not answers; guardrail: detect code in hints and similarity to `solution.py`; Langfuse traces; 👍/👎 ratings; offline tutor eval using the 3 reference hints per problem. → *Needs: hints field, solution accessible internally.*
- **Week 5, simulated students + integrity:** persona-based simulated students (strong, average, struggling, copier, quitter) generating submissions over time using buggy solutions, LLM-generated attempts and copies; integrity: AST-normalized similarity (rename-proof), paste/speed signals, flags with reasons; difficulty and skill estimates (start with pass rates, maybe IRT/Elo later). → *Needs: buggy solutions, concepts, timestamps.*
- **Weeks 6–7, RL:** `lab/rl/`: build RL prompts from `problems.jsonl`; reward function = `grade(...).reward` on hidden+visible tests (optionally + format reward for valid code); GRPO with TRL on Qwen 0.5–1.5B on Colab/Kaggle; train/test split of problems (never evaluate on training problems, **or** hold out a module) and report before/after on held-out problems; watch for reward hacking (e.g. hardcoding visible tests) and document examples. Optional DPO on hint ratings. → *Needs: fast, deterministic, crash-proof grader returning partial credit.*
- **Week 8:** instructor dashboard, light early-warning model, final README with architecture diagram and results, demo video.

📌 Note for later: for RL, we'll need a **train/held-out split of problems**. 33 problems is small; in Week 6 we may generate more problems (LLM-drafted, validated by our validator + buggy-solution checks). Keep that in mind: the validator is also our **data quality gate** for generated problems.

---

## 11. Interview-prep habits

- At the end of each week, write `docs/notes/weekN.md` **together with me** (I write, you review and correct). Template:
  - What we built (3–5 bullets)
  - Key design decisions and trade-offs
  - Hardest bug / surprise and how we fixed it
  - Numbers (tests, problems, pass rates, speed)
  - "How I'd explain this in 60 seconds" (I write this myself)
  - "If I had more time / at Scale's scale, I would…"
  - 5 likely interview questions about this week's work, and my answers
- Keep a running list of 📌 interview notes in `docs/notes/interview-notes.md` (append each one you give me).

---

## 12. Session rituals

**At the start of every session:**
1. Read `CLAUDE.md` (Status, Decisions log, Open questions).
2. Run `git status`, `git log --oneline -10`, and `make all`. Report anything broken.
3. Tell me in 3 lines: where we are, what's next, anything blocking.
4. Wait for my "go".

**At the end of every session** (when I say "let's stop" or similar):
1. Make sure everything is committed (or tell me what's uncommitted and why).
2. Update `CLAUDE.md`: Status (done / in progress / exact next action), Decisions log (new entries), Open questions, Known limitations.
3. Commit: `docs: update CLAUDE.md status`.
4. Give me a **5-line summary** of the session (I paste it into my Claude app memory so both stay in sync). Format:
   ```
   Session YYYY-MM-DD:
   Done: ...
   Decisions: ...
   Next: ...
   Blockers/questions: ...
   ```

---

## 13. Appendix A: the full CS1 problem list

All problems are single Python functions. No `input()`, no printing (return values only). Difficulties are targets; adjust with me if needed.

### Module 1: Variables & Arithmetic (`01_variables`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 1.1 | `celsius_to_fahrenheit(c: float) -> float` | F = C × 9/5 + 32. Compare `float` | easy |
| 1.2 | `seconds_to_hms(seconds: int) -> list[int]` | Convert non-negative seconds to `[hours, minutes, seconds]` | easy |
| 1.3 | `rectangle_stats(width: float, height: float) -> list[float]` | Return `[area, perimeter]`. Compare `float` | easy |
| 1.4 | `average_of_three(a: float, b: float, c: float) -> float` | Average rounded to 2 decimals | easy |

### Module 2: Conditions (`02_conditions`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 2.1 | `is_leap_year(year: int) -> bool` | Gregorian rules (÷4, not ÷100 unless ÷400) | easy |
| 2.2 | `letter_grade(score: int) -> str` | A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, else F; outside 0–100 → "Invalid" | easy |
| 2.3 | `max_of_three(a: int, b: int, c: int) -> int` | Largest of three (must handle ties and negatives) | easy |
| 2.4 | `triangle_type(a: float, b: float, c: float) -> str` | "equilateral", "isosceles", "scalene", or "invalid" (non-positive sides or triangle inequality fails) | medium |

### Module 3: Loops (`03_loops`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 3.1 | `sum_of_evens(n: int) -> int` | Sum of even numbers from 1 to n inclusive; n ≤ 0 → 0 | easy |
| 3.2 | `factorial(n: int) -> int` | n ≥ 0, iterative; factorial(0) = 1 | easy |
| 3.3 | `count_digits(n: int) -> int` | Number of digits; handles 0 (→1) and negatives | easy |
| 3.4 | `fizzbuzz(n: int) -> list[str]` | Classic FizzBuzz strings for 1..n; n ≤ 0 → [] | easy |

### Module 4: Strings (`04_strings`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 4.1 | `is_palindrome(s: str) -> bool` | Ignore case and non-alphanumeric characters; "" → True | easy |
| 4.2 | `count_vowels(s: str) -> int` | Count a, e, i, o, u (case-insensitive) | easy |
| 4.3 | `reverse_words(sentence: str) -> str` | Reverse word order; collapse multiple spaces; strip ends | medium |
| 4.4 | `compress(s: str) -> str` | Run-length: "aaabcc" → "a3b1c2"; "" → "" | medium |

### Module 5: Lists (`05_lists`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 5.1 | `second_largest(nums: list[int]) -> int \| None` | Second largest **distinct** value; None if it doesn't exist | medium |
| 5.2 | `remove_duplicates(nums: list[int]) -> list[int]` | Keep first occurrences, preserve order; don't mutate input | easy |
| 5.3 | `rotate_right(nums: list[int], k: int) -> list[int]` | Rotate right by k (k may exceed length; empty list → []) | medium |
| 5.4 | `merge_sorted(a: list[int], b: list[int]) -> list[int]` | Merge two sorted lists into one sorted list (without calling sort, stated in description; can't enforce, but hidden large tests check it's linear-ish) | medium |

### Module 6: Functions (`06_functions`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 6.1 | `is_prime(n: int) -> bool` | n < 2 → False; must be efficient (hidden test with a large prime ~10^9+7 catches O(n) loops) | medium |
| 6.2 | `gcd(a: int, b: int) -> int` | Greatest common divisor for non-negative ints; gcd(0, 0) = 0 | easy |
| 6.3 | `primes_up_to(n: int) -> list[int]` | All primes ≤ n, ascending | medium |
| 6.4 | `running_total(nums: list[int]) -> list[int]` | Prefix sums; [] → [] | easy |

### Module 7: Dictionaries (`07_dicts`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 7.1 | `word_frequency(text: str) -> dict[str, int]` | Lowercase words, strip punctuation `.,!?;:`, count occurrences | medium |
| 7.2 | `first_unique_char(s: str) -> int` | Index of first non-repeating character; -1 if none | medium |
| 7.3 | `group_anagrams(words: list[str]) -> list[list[str]]` | Group anagrams; each group sorted alphabetically; groups sorted by their first word | medium |
| 7.4 | `two_sum(nums: list[int], target: int) -> list[int]` | Indices `[i, j]`, i < j, exactly one valid answer; hidden large test catches O(n²) | medium |

### Module 8: Recursion & Problem Solving (`08_recursion`)
| # | slug / function | Spec | Difficulty |
|---|---|---|---|
| 8.1 | `recursive_sum(nums: list[int]) -> int` | Sum using recursion ([] → 0) | easy |
| 8.2 | `fibonacci(n: int) -> int` | fib(0)=0, fib(1)=1; hidden n ≈ 35 catches naive exponential recursion (include `naive_exponential.py` as a buggy solution that must time out) | medium |
| 8.3 | `flatten(nested: list) -> list` | Flatten arbitrarily nested lists of ints | medium |
| 8.4 | `binary_search(nums: list[int], target: int) -> int` | Index of target in sorted list, -1 if absent | medium |
| 8.5 | `valid_parentheses(s: str) -> bool` | Brackets `()[]{}` properly matched and nested | hard |

Notes:
- "Efficiency" tests (6.1, 7.4, 8.2, 5.4) rely on time limits. Verify the reference solution is fast and the naive one reliably times out on **my** machine; if it's flaky, discuss with me (options: larger inputs, lower per-problem `time_limit_s`).
- Large test inputs must still fit in YAML reasonably (< ~100 KB per test file). If a test needs a huge input, discuss a "generated input" feature with me first (e.g. `input_generator: "list(range(100000))"`). Don't add it without asking.

---

## 14. Appendix B: example problem, fully written

`problems/cs1/03_loops/sum_of_evens/problem.yaml`
```yaml
id: cs1.loops.sum_of_evens
version: 1
title: Sum of Even Numbers
module: 3
module_name: Loops
order: 1
difficulty: easy
concepts: [for_loops, arithmetic, edge_cases]
function_name: sum_of_evens
description_en: |
  Write a function `sum_of_evens(n)` that returns the sum of all even numbers
  from 1 up to and including `n`.

  - `n` is an integer (it can be zero or negative).
  - If there are no even numbers in the range, return 0.

  Examples:
    sum_of_evens(10) -> 30      # 2 + 4 + 6 + 8 + 10
    sum_of_evens(7)  -> 12      # 2 + 4 + 6
description_ar: null
hints:
  - "Think about which numbers between 1 and n you need to add together."
  - "Loop over the numbers from 1 to n and check whether each one is even using the % operator."
  - "Start a total at 0. For each number in range(1, n + 1), if number % 2 == 0, add it to the total. Return the total at the end."
author: claude
```

`starter.py`
```python
def sum_of_evens(n: int) -> int:
    """Return the sum of all even numbers from 1 to n (inclusive)."""
    pass
```

`solution.py`
```python
def sum_of_evens(n: int) -> int:
    """Return the sum of all even numbers from 1 to n (inclusive)."""
    total = 0
    for number in range(2, n + 1, 2):
        total += number
    return total
```

`tests.yaml` (expected values filled by `fill_expected.py`)
```yaml
tests:
  - {id: t01, input: [10], expected: 30, hidden: false, compare: exact, note: "example 1"}
  - {id: t02, input: [7], expected: 12, hidden: false, compare: exact, note: "example 2, odd n"}
  - {id: t03, input: [2], expected: 2, hidden: false, compare: exact, note: "smallest even"}
  - {id: t04, input: [1], expected: 0, hidden: false, compare: exact, note: "no evens"}
  - {id: t05, input: [0], expected: 0, hidden: true, compare: exact, note: "edge: zero"}
  - {id: t06, input: [-5], expected: 0, hidden: true, compare: exact, note: "edge: negative"}
  - {id: t07, input: [100], expected: 2550, hidden: true, compare: exact, note: "larger n"}
  - {id: t08, input: [11], expected: 30, hidden: true, compare: exact, note: "odd n after even"}
  - {id: t09, input: [1000000], expected: 250000500000, hidden: true, compare: exact, note: "big n, still fast"}
```

`buggy/off_by_one.py`
```python
def sum_of_evens(n: int) -> int:
    total = 0
    for number in range(2, n, 2):   # bug: excludes n itself
        total += number
    return total
```

`buggy/sums_odds.py`
```python
def sum_of_evens(n: int) -> int:
    total = 0
    for number in range(1, n + 1):
        if number % 2 == 1:          # bug: wrong condition
            total += number
    return total
```

`buggy/negative_crash.py`
```python
def sum_of_evens(n: int) -> int:
    if n < 0:
        raise ValueError("n must be positive")   # bug: spec says return 0
    return sum(range(2, n + 1, 2))
```
(Note: `negative_crash.py` passes all visible tests and fails only the hidden negative test. This is the kind of mistake hidden tests exist to catch.)

---

**End of kickoff. Claude Code: reply with your 10-line summary, your questions, and your plan for Step 0. Don't write code until I say "go".**