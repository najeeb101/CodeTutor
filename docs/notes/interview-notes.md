# Interview notes

Running list of 📌 interview notes, one section per concept, appended as they come up.

## Strict schemas protect the data (Week 1, Step 1)
Every problem goes through a pydantic schema with `extra="forbid"`: an unknown key (like the typo
`hiden: true`) is an error, not silently ignored. `hidden` has no default, so forgetting it can't
turn a hidden test into a visible one. Why it matters: in an eval or RL pipeline, a silent data
error (a leaked hidden test, a wrong expected value) doesn't crash anything. It just makes your
numbers wrong, and you may never notice. Fail loudly at load time instead.
*How I'd say it:* "I treat problem definitions like a data contract. Anything that can be checked
without running code is checked when loading, with an error that names the file and field."

## Hidden tests and the student view (Week 1, Step 1)
Each problem has two views: internal (everything) and student (description, starter code, visible
tests only). Models in evals get exactly the student view. If a model (or student) could see all
tests, it could overfit to them, e.g. hard-code the answers. That is **reward hacking**: getting
a high score without solving the real task. Hidden tests are the defense. They only work if
they never leak, so the "what is hidden" rule is enforced in one place, in code.

## "Missing" vs "null" (Week 1, Step 1)
`expected: null` is a real answer (e.g. `second_largest([7, 7, 7])` returns None), so None can't
also mean "not filled in yet". The schema tracks whether the key was present at all
(`model_fields_set`). A classic data-pipeline bug is treating "missing" and "null" as the same thing.

## Mutation testing with buggy solutions (Week 1, Step 1)
Every problem ships 1–3 realistic wrong solutions. The validator (Step 3) requires that each one
fails at least one test. If a buggy solution passes, the tests are too weak. This measures
**test strength**, a quality metric for the reward signal itself. It's also why each problem
has at least one bug that only hidden tests catch (e.g. `negative_crash.py`).

## Sandboxing: layers of defense (Week 1, Step 2)
Student (or model) code runs in a separate process with its own process group, a temp folder, an
almost empty environment and resource limits: memory (RLIMIT_AS), CPU, file size, open files,
plus a timer for each test and a wall-clock limit for the whole run. After every run the grader kills
the whole process group. Each layer catches what the others miss (e.g. the CPU limit backs up the
wall-clock limit). *Be honest about limits:* a subprocess sandbox doesn't stop file reading, network
access or fork bombs. That's why production graders use containers (Docker, gVisor, Firecracker).

## Why expected outputs never enter the child (Week 1, Step 2)
The child only receives inputs and reports return values; the parent compares. Student code runs
inside the child and can read its memory, so anything in the child is readable by the student. If the
expected answers were there, a submission (or an RL policy!) could learn to look them up instead of
solving the task. That would be reward hacking by reading the answer key.

## The token (Week 1, Step 2)
Student code can print anything, including something that looks like a result. The runner writes its
report after a fresh random token, and the parent reads only the text after the last token and
validates it. Honest weakness: the token is in the child's memory. It still can't be abused, because
a fake report can only claim return values, not "passed", and the child never saw the right answers.

## Hidden tests and side channels (Week 1, Step 2)
Hidden tests stop overfitting to visible examples. But hidden inputs can leak through *side
channels*: the student's print output, or error messages ("ValueError: the input was 100"). The
grader captures output per test and, for students, drops hidden-test output and shortens
hidden-test errors to the exception type. Lesson: "don't return X" is not enough; check every
channel that carries data back.

## Partial credit as a reward (Week 1, Step 2)
reward = passed / total. A 0/1 reward is *sparse*: a small model that rarely solves a problem
completely gets almost no learning signal. Partial credit gives a gradient toward correct
solutions. Risk: it can be gamed, e.g. by hard-coding the visible tests for a few points. Hidden
tests and a held-out problem split limit that. Crashes and total timeouts get 0, so "crash the
grader" is never a winning strategy.

## Deterministic grading (Week 1, Step 2)
Same code + same problem version → same result. We fix PYTHONHASHSEED so the order of sets of strings
is stable. (A surprise we found by running it: Python's `-I` flag silently ignores PYTHONHASHSEED.)
We record grader_version and problem version in every result. Only exception: timeouts on a
heavily loaded machine. For RL this matters: a noisy reward is a worse training signal.
