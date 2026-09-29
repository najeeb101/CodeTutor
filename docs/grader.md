# The grader

`grade(problem, code) -> GradeResult` is the **one** grading path in this project. Student
submissions (Week 3), model evaluations (Week 2) and the RL reward (Week 6) all call it, so they
all get the same tests, the same comparison rules and the same scoring.

Code: `src/codetutor/grader/`

| File | Runs in | Job |
|---|---|---|
| `grader.py` | parent | Public API: `grade()`, `grade_many()`, `execute()`. Builds the job, parses the report, compares, scores. |
| `sandbox.py` | parent | Starts the child process with limits, feeds it the job, collects its output, kills it. |
| `runner.py` | **child** | Loads the student code, calls the function on each input, reports return values. |
| `compare.py` | parent | Decides whether an actual value matches the expected value. |
| `models.py` | both sides' data | Limits, results, job and report shapes, constants. |

## 1. One grading run, step by step

```
 PARENT (grader process)                                CHILD (python -S -s -P runner.py)
 ───────────────────────                                ─────────────────────────────────
 grade(problem, code)
   │ limits: per-test = problem.time_limit_s,
   │         total = n_tests × per-test + 3 s
   │ token = random 32 hex characters
   │ job = {token, code, function_name,
   │        tests: [{id, input}],   ← NO expected values
   │        limits}
   ▼
 SubprocessSandbox.run(job)
   │ new temp dir, env = {PYTHONHASHSEED: 0},
   │ own process group
   │ ──────────── job as JSON on stdin ─────────────►   read job
   │                                                    set rlimits (memory, CPU, file size, files)
   │                                                    capture print() output
   │                                                    exec(student code)  → compile error?
   │                                                    for each test:
   │                                                       copy input, start timer
   │                                                       value = function(*input)
   │                                                       → returned / bad_return / error / timeout
   │                                                       input_changed = input != original copy
   │ ◄──── stdout: "...student noise...\n" + TOKEN + {report as JSON} ──
   │                                                    os._exit(0)
   │ wait (max total time) → kill whole process group
   ▼
 parse text after the LAST token; validate with pydantic
   │ for each test: compare(actual, expected)   ← only the parent knows expected
   │   (if problem.check_input_unchanged and input_changed → wrong_answer)
   │ status = accepted, or the status of the first failing test
   │ reward = passed / total
   ▼
 GradeResult (hidden-test details removed unless reveal_hidden=True)
```

## 2. Limits (`Limits` in `models.py`)

| Limit | Default | Enforced by | What happens |
|---|---|---|---|
| `per_test_timeout_s` | 2.0 (or `problem.time_limit_s`) | `signal.setitimer` in the runner | that test → `timeout`, the next tests still run |
| `total_timeout_s` | auto: n_tests × per-test + 3 s | parent's `wait(timeout=...)` | whole run → `timeout`, reward 0 |
| `memory_mb` | 512 | `RLIMIT_AS` | usually `MemoryError` → `runtime_error` |
| `max_file_mb` | 1 | `RLIMIT_FSIZE` | `OSError: File too large` → `runtime_error` |
| `max_output_bytes` | 64 000 | runner's capped writer | print output is cut, marked `[output truncated]` |
| CPU time | total + 1 s | `RLIMIT_CPU` | backstop if the wall-clock limit fails |
| open files | 64 | `RLIMIT_NOFILE` | |
| return value | 1 MB of JSON | runner | that test → `wrong_answer` "return value is too large" |
| child output read by the parent | 32 MB stdout / 64 KB stderr | parent's capped readers | `crashed`: "output limit exceeded" |

**Why the total limit is automatic:** if it were a fixed 20 s, a problem with 12 tests that all
time out (12 × 2 s = 24 s) would hit the total limit and lose the partial credit it had earned.
With `n_tests × per_test + 3 s`, per-test timeouts can never add up to a total timeout. A total
timeout then only happens for real abuse: an endless loop at the top level, or code that
catches our timeout exception.

The runner sets its own rlimits (before it runs any student code) instead of using
`subprocess.Popen(preexec_fn=...)`. Python documents `preexec_fn` as unsafe when the parent has
threads, and `grade_many` uses threads.

## 3. Statuses and reward

Per test: `passed`, `wrong_answer`, `runtime_error`, `timeout`.

Whole submission:

| Status | When | reward | `tests` |
|---|---|---|---|
| `accepted` | every test passed | 1.0 | all |
| `wrong_answer` / `runtime_error` / `timeout` | the status of the **first failing test in test order** | passed / total | all |
| `compile_error` | loading failed (syntax error, top-level exception, function missing) | 0.0 | empty |
| `timeout` (total) | the whole run went over the total limit | 0.0 | empty |
| `crashed` | no valid report (e.g. `os._exit`, killed by a signal, output flood) | 0.0 | empty |

Bad return types are `wrong_answer` with an explanation, e.g. "returned a set; return a list instead".

If a problem sets `check_input_unchanged: true` and the function changed its input (for example
sorted the list in place), that test is `wrong_answer` with "your function changed its input;
build and return a new list instead", **even if the returned answer is right**.

**Partial credit as a reward.** `reward = passed / total` gives a learning signal even when a
solution is not fully correct. For RL this matters: with only 0/1 rewards, a small model that
rarely solves a problem completely gets almost no signal. The downside is that partial credit can
be gamed (hard-code the visible tests, get a few points). Hidden tests limit that.

## 4. Design decisions

- **Expected outputs never enter the child.** The runner only gets inputs. Student code runs in the
  same process as the runner and can read its memory, so anything in the child is readable
  by the student. If expected values were there, a submission could just look them up.
- **The parent decides pass/fail.** The child reports return values only. Even a fake report can
  only claim return values; it cannot claim "passed".
- **The token.** Student code can write to the real stdout (`os.write(1, ...)`). The parent only
  trusts the text after the **last** occurrence of a fresh random token, and validates it with
  pydantic. Honest limitation: the token lives in the child's memory, so determined code could find
  it and write a fake report. That still doesn't help, because of the two points above: a fake report
  would need the correct answers, which the child never had.
- **Python flags `-S -s -P` and `PYTHONHASHSEED=0`, not `-I`.** We checked by running it: `-I`
  ignores `PYTHONHASHSEED`, so the order of a set of strings changes between runs, and grading
  would not be deterministic. `-S` also keeps the venv's packages (pydantic etc.) out of reach.
  Side effect: `exit()` doesn't exist without `site` (use `sys.exit()`).
- **Always kill the process group**, even after a normal exit. This removes processes the student
  started. The runner ends with `os._exit(0)`, so threads the student started can't keep it alive.
- **Output is captured per test.** With `reveal_hidden=False`, the output printed during hidden
  tests is dropped and hidden-test error messages are shortened to the exception type. Otherwise
  `print(n)` or `raise ValueError(n)` would show students the hidden inputs.
- **Deep copy of every input** (`json.loads(json.dumps(...))`). Each test already gets its own
  objects, so this is defense in depth.
- **Side effects are checked only when the problem asks (`check_input_unchanged`).** The child
  compares the arguments with the job's untouched copy after the call and only *reports*
  `input_changed`; the parent decides. It is off by default, because a rule the description does
  not state would be a hidden surprise. The error message contains no input, so hidden tests
  show it too. (Added in grader 0.2.0.)
- **`Sandbox` is a Protocol.** `grade(..., sandbox=...)` accepts any object with
  `run(job) -> RawResult`, so a Docker sandbox can replace the subprocess one (Step 5).
- **`grade_many` uses threads**, not processes: each grade spends its time waiting for a child
  process, which doesn't hold the GIL. `ThreadPoolExecutor.map` keeps the input order.

## 5. Threat model

**This sandbox protects against:**
- endless loops (per-test timer, total limit, CPU limit);
- memory bombs (`RLIMIT_AS`);
- huge files (`RLIMIT_FSIZE`) and print floods (capped writer, capped readers);
- crashing or hanging the grader (separate process, timeouts, readers that give up);
- faking results (token + validation + expected values never in the child + parent decides);
- mutating inputs between tests (fresh copies);
- leaking hidden tests through results, print output or error messages (`reveal_hidden=False`);
- leftover processes and threads (process-group kill, `os._exit`).

**It does NOT protect against:**
- **reading files** your user can read (e.g. `~/.ssh`, the `problems/` folder with all solutions);
- **network access** (sending data out, downloading things);
- **fork bombs** (no `RLIMIT_NPROC`: it counts all of the user's processes; decision Q6), and
  processes that leave the process group with `setsid()` (they survive the kill);
- code that **catches our timeout** with a bare `except:` in a loop (only the total limit stops it);
- **a determined attacker** in general (e.g. ctypes tricks, reading the token from memory).

**Conclusion:** good enough for Najeeb, friends, and AI-model outputs on this machine.
**A Docker sandbox (no network, read-only filesystem, non-root, pids limit) is required before
strangers submit code.**

## 6. Known limitations
- Timeouts depend on machine load: a slow or busy machine can turn a borderline solution into a
  timeout. Grading is deterministic *except* for timeouts under heavy load.
- The process-group id could in theory be reused between the child exiting and the kill. This is
  extremely unlikely on Linux; noted for completeness.
- Output limits count characters, not exact bytes.
- The runner's own internal errors (after it captures output) show up as `crashed` with little detail.
- The input check uses `==`, so `[1]` and `[True]` count as equal, and a change that is undone
  before the function returns is not seen. It catches honest mistakes, not attackers: code that
  finds the runner's original copy in memory could change that too.
