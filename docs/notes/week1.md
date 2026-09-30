# Week 1: problem bank + auto-grader

Written by Najeeb, reviewed by Claude.

<!--
HOW TO USE THIS FILE (delete this box when you are done)
- Each section has a grey box like this one with raw facts from Claude. They are notes, not text.
  Write your own sentences under the box. Use your own words: in an interview you can only
  say what you really understand.
- You don't have to use every fact. Choosing what matters is part of the exercise.
- When you are done, say "review". Claude checks every claim and number, marks each section
  ✅ / ⚠️ / ❌, and does not rewrite your text. Then these boxes are removed.
-->

## 1. What we built

<!--
Raw facts (pick 3-5 bullets, say what each part DOES, not only its name):
- Problem format: one folder per problem (problem.yaml, starter.py, solution.py, tests.yaml,
  buggy/*.py); strict pydantic schema + loader. src/codetutor/problems/
- Grader: grade(problem, code) -> GradeResult. Child process runs the code with limits, parent
  compares. Also grade_many() for parallel grading. src/codetutor/grader/
- Bank tools: fill_expected (runs solution.py to write expected values), validator (solution
  passes, starter fails, every buggy solution is caught), dataset build (dist/*.jsonl with
  content_hash). src/codetutor/bank/ + scripts/
- 33 CS1 problems in 8 modules. problems/cs1/
- Test suite with 27 hostile submissions (infinite loops, memory bombs, os._exit, fake result,
  print floods). tests/
- Docs: docs/grader.md, docs/problem-format.md, README.md
-->

## 2. Key design decisions and trade-offs

<!--
Raw facts: pick 4-5. For each one say: the decision, WHY, and what it COSTS.
A decision without a cost sounds like you didn't think about it.

- Child gets test inputs only; the parent compares.
    why: expected answers can't leak or be faked.  cost: return values must be JSON; more code.
- One process for all tests of a submission (not one per test).
    why: fast (~34 ms for a whole grading).  cost: os._exit or a crash ends all tests (reward 0);
    a test can see what the previous test left behind (this is how flatten's mutable default
    list bug is caught).
- Week 1 sandbox = subprocess + rlimits, not Docker.
    why: simple and fast to build and run.  cost: NOT secure (can read files, use the network).
- Reward = partial credit (passed / total).
    why: a smoother learning signal for RL than 0/1.  cost: slow-but-correct is_prime still
    scores 0.93 (13/14), so speed tests are worth little.
- Hidden tests + a student view (no solution, no hidden tests, no hints).
    why: stops solutions that only fit the examples.  cost: less feedback; hidden-test errors
    are cut to the exception type so they can't leak inputs.
- Every problem has buggy solutions that the validator must catch (mutation testing).
    why: proves the tests are strong.  cost: time to write them; a buggy file that times out
    costs ~2.2 s per validation run.
- Strict schema: unknown fields are errors, `hidden` and `compare` have no default.
    why: a typo can never make a hidden test visible.  cost: longer YAML.
- Exact compare: 30.0 != 30, True != 1.
    why: no false passes.  cost: problems with float answers must say compare: float.
- Optional check_input_unchanged flag (grader 0.2.0).
    why: catches side effects (sorting the input in place).  cost: it uses ==, so it catches
    honest mistakes, not attackers; off by default so old problems grade the same.
- Deterministic grading: PYTHONHASHSEED=0, grader version + problem version + content_hash.
    why: an eval run can be repeated and compared.  cost: timeouts still depend on machine load.
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
Raw facts: pick ONE and tell it as a story: what we saw -> what we measured -> the cause ->
the fix -> what we learned. All five are true and measured.

- Q12, flaky memory test: test_memory_bomb failed about 1 run in 8. The memory bomb and the
  0.5 s timer were in a race. Measured: filling 256 MB took 186 ms median but up to 503 ms.
  Fix: a 2 s timer for that test only (max seen after: 303 ms). Rejected: "accept timeout too",
  because then a broken memory limit would also pass.
- `python -I` ignores PYTHONHASHSEED: set order changed between runs, so grading was not
  deterministic. Found by running it, not by reading docs. Fix: `-S -s -P` + env PYTHONHASHSEED=0.
- Q8, fibonacci: naive fib(35) takes only 0.87 s, so the "too slow" test would PASS the slow
  code. Fix: test n = 40 (naive ~10-18 s, always times out; loop version 8 microseconds).
- count_digits: int(math.log10(n)) + 1 gives 16 for 999999999999999 (15 nines), because the
  float log10 rounds up to 15.0. Now a hidden test.
- rotate_right without `k % len(nums)`: still RIGHT while k < 2 * len, because negative slice
  indexes count from the end. Needed a test with k = 10, len 4 to catch it.
-->

## 4. Numbers

Measured by Claude on 2026-09-30. Najeeb: check them before an interview.

| What | Number |
|---|---|
| Problems | 33 in 8 modules (17 easy, 15 medium, 1 hard) |
| Tests | 374 (242 hidden) |
| Buggy solutions | 97, all 97 caught by the validator |
| Bugs only hidden tests catch | 54, at least one in each of the 33 problems |
| pytest tests | 179, including 27 hostile submissions |
| Grading one correct submission (fizzbuzz, 10 tests) | ~34 ms (median of 10) |
| Validating the whole bank | ~10 s |
| `make all` (lint + tests + validate) | ~32–48 s, depending on machine load |
| Code size | ~1,900 lines in `src/`, ~1,350 lines in `tests/` |
| Grader version | 0.2.0 |
| Time | 3 days (2026-09-28 → 2026-09-30); 18 commits up to the README rewrite |

## 5. How I'd explain this in 60 seconds

<!--
No facts from Claude here, on purpose. Write it yourself, about 150 words, then say it out loud
without reading. Tip: say what it is, who it is for, the one idea that makes it interesting,
and one number.
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
Raw keywords (pick 3-4, and say WHY each one matters):
- A real sandbox: Docker with no network, a read-only file system and a non-root user; at big
  scale, gVisor or Firecracker microVMs.
- Grading as a job queue with many workers (Week 3 plan); grade_many() already runs in parallel.
- Timeouts: the per-test timer is wall-clock time (plus a CPU-time limit for the whole process),
  so a busy machine can cause false timeouts. Options: CPU-time limits, fewer parallel jobs,
  retry once on timeout.
- Faster validation: one parallel pool for the whole bank (open question Q11).
- An AST check for banned calls, e.g. sort() in merge_sorted (docs/ideas.md).
- Reward design for RL: efficiency tests are worth little under partial credit (docs/ideas.md).
- More problems: LLM-drafted problems, with the validator + buggy solutions as the quality gate.
-->

## 7. Five likely interview questions (and my answers)

<!-- The questions are Claude's (playing the interviewer). The answers are yours: 3-5 sentences
each, with one concrete example from this project. -->

**1. Why does the student's code never receive the expected outputs?**

**2. How do you know your tests are good enough?**

**3. Why partial credit as the reward, and what is its downside?**

**4. Is your sandbox safe? What would you change before real users?**

**5. How do you make grading deterministic and your data versioned?**
