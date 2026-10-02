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
- Product half: Next.js + Monaco (Wk 3) → FastAPI (Wk 3) → grader queue (Redis + RQ/Arq) + sandbox,
  AI tutor (LiteLLM + RAG + Langfuse, Wk 4), Postgres/Supabase + pgvector (Wk 3).
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
- `scripts/`: `validate_problems.py`, `fill_expected.py`, `grade_cli.py`, `build_dataset.py`, `bench_sandbox.py`, `try_model.py`, `check_secrets.py`, `run_eval.py`, `eval_report.py`
- `tests/`: pytest suite; `tests/submissions/` holds adversarial submissions
- `docs/`: `KICKOFF.md`, `ideas.md`, `problem-format.md`, `grader.md`, `evals.md`, `notes/`
- `lab/evals/`: `configs/` (one YAML per official run), `results/` (committed JSONL + meta),
  `reports/` (generated `week2.md`), `scratch/` (gitignored)
- `api/`, `web/`, `tutor/`: placeholders for later weeks
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
  `test-docker` runs the hostile tests in Docker (opt-in, marker `docker`, ~1 min; run it after any
  sandbox change). Docker works without `sg` since the WSL restart on 2026-10-01.
- WSL uses **mirrored networking** (`C:\Users\ACER\.wslconfig`), so `localhost` reaches the
  Windows Ollama. Model calls need `uv run --env-file .env ...`.

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
- **Open:** Najeeb's TODO `fizzbuzz/buggy/stops_before_n.py`; `docs/notes/week1.md` text (its
  numbers table is from grader 0.2.0 / 179 tests: re-check at review); Q11 option B (parallel
  bank validation, recommendation: leave it); Q14 (rare memory-bomb flake, recommendation A:
  leave it).
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
  half up; Q3 why 7 cells changed but no headline number.
  (57 in total; answer key in Claude's memory.)
- **Next action:** Najeeb's last call from the Step 4b STOP ((1) finish_reason fix, (2) YAML
  parser and (3) Q15 rounding are done): (4) Gemini n = 1: keep as a 3rd model (after 10:00 Qatar time,
  `uv run --env-file .env python scripts/run_eval.py lab/evals/configs/gemini-2.5-flash.yaml`,
  2 days) or drop. Then Step 5 (Najeeb's `docs/notes/week2.md`, README).
  `docs/notes/week1.md` text whenever he wants ("review").

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

## Open questions
- Q11: suite time. The YAML part is done (2026-10-02, ~2 s saved). Now pytest 28–41 s depending on machine load, `make all` 45–65 s (limit 60 s is for pytest); the biggest single test is bank validation (10.2 s). Bank validation costs ~0.33 s per problem plus ~2.2 s per timeout bug, twice per `make all`. Options: (A) leave it, the bank is complete; (B) make `validate_bank` grade all problems' jobs in one parallel pool (20 CPUs here), so the three timeouts overlap. Trade-off of B: more parallel load makes timeouts and the 25% timing check flakier. Measure before deciding.
- Q14: the memory-bomb flake (Decisions log, 2026-10-01). Options: (A) leave it and save full test output on every run, so a repeat names the test; (B) raise `MEMORY_TEST` from 2 s to 3 s. Trade-off of B: nothing is slower while the memory limit works, but if it ever broke, the bomb (~2.5 GB/s) would get more time to fill the 7.8 GB WSL machine before the timer stops it. Recommendation: A, until it happens again.

## Known limitations
- The "no code in hints" check is a heuristic (``` fences and lines starting with a Python keyword). Code written inside a sentence is not caught.
- Tests import helpers from `tests/conftest.py` directly (`from conftest import ...`). This works with pytest's default rootdir import mode; move them to a helpers module if that ever breaks.
- The subprocess sandbox is NOT secure: student code can read the user's files and use the network; fork bombs and setsid() escapes are not stopped. Use `DockerSandbox` for untrusted code (docs/grader.md, sections 5–6).
- The Docker sandbox shares the host kernel (a kernel bug can let code out), and the Docker daemon is root-equivalent, so the Week 3 worker must never expose it. In Docker, code that sleeps at the top level runs up to 5 s past the total limit (start-up margin); a daemon that fails mid-run shows up as `crashed`.
- Student code can catch the per-test timeout with a bare `except:` in a loop; only the total limit stops it (was Q4).
- The result token is in the child's memory and can be found; the real protection is that expected values never enter the child (was Q5).
- Timeouts depend on machine load, so grading is deterministic except for timeouts under heavy load. This also affects failure *labels*: a memory bomb can end as `timeout` or `runtime_error` depending on load (same reward, different label). Keep it in mind for Week 2 failure-type statistics.
- The validator's "solution < 25% of the time limit" check is measured while 4 gradings run in parallel, so it can be flaky on a busy machine.
- The input check compares with `==`: `[1]` and `[True]` count as equal, and a change undone before the function returns is not seen. It catches honest mistakes, not attackers.
