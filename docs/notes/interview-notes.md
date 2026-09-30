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

## Mutation testing with buggy solutions (Week 1, Step 3)
How do you know your tests are good? Passing the reference solution proves nothing: an empty test
list also "passes". So every problem has 2–3 buggy solutions with realistic student mistakes
(off-by-one, forgetting the empty list). The validator requires that every buggy solution fails at
least one test. This is a simple, hand-made form of *mutation testing*: you measure a test suite by
the mistakes it catches. For RL it matters directly: a weak test suite is a hackable reward, because
a wrong program can get reward 1.0. We also track bugs that only hidden tests catch, to check that
the hidden tests add something beyond the visible ones.

## Content hashing and data versioning (Week 1, Step 3)
Each problem line in dist/problems.jsonl carries a sha256 `content_hash` of its files. An eval or
training run records the hashes it used, so later you can prove which exact data produced a number.
The `version` field is a promise made by a human ("I bumped it"); the hash is a check done by a
machine (any change shows up, even a forgotten bump). Details matter: hash a fixed file list (so
junk files don't count), include file names (so renames count), and separate the parts clearly (so
"ab"+"c" and "a"+"bc" give different hashes). Same idea as git commit ids and dataset lineage in
ML pipelines.

## Checking side effects, not just return values (Week 1, Step 4)
A function can return the right answer and still be wrong: `nums.pop(i)` inside remove_duplicates
gives the correct list back, but it also destroys the caller's data. A grader that only compares
return values scores that as 1.0. So the grader can also check that the arguments are unchanged
after the call (`check_input_unchanged`, turned on per problem, because the spec must state the
rule). Design: the sandboxed child only *reports* "input changed"; the parent *decides*, same as for
answers. For evals and RL this is the general lesson: the reward must check every property the
task asks for, or a model learns the shortcut (right output, bad behavior). Limits worth saying out
loud: it compares with `==`, so it catches honest mistakes, not a determined attacker.

## Test isolation: one process for all tests, or one per test? (Week 1, Step 4)
Our grader runs all tests of one submission in one child process. Trade-off: it is much faster
than a fresh process per test, and it behaves like a real program that calls the function many
times, so state bugs are caught. Example: `def flatten(nested, result=[])` shares one default list
between calls; test 1 passes, test 2 still contains test 1's numbers. With one process per test,
that bug would get reward 1.0. The cost: one test can affect the next. We reduce that by giving
every test a fresh deep copy of its input, and the total time limit stops a test that breaks the
process. For evals the lesson is general: how you isolate test cases changes what your metric
measures, so write the choice down.

## Security vs speed in sandboxes (Week 1, Step 5)
The grader has two sandboxes behind one small interface (`Sandbox.run(job)`), so `grade()` never
changes. The subprocess sandbox is fast (~0.1 s per submission here) but only limits resources:
code can still read files and use the network. The Docker sandbox adds walls: no network, no host
files, non-root, no capabilities, a process limit. It costs about 1 s per submission, almost all
of it container start-up. So you choose by who wrote the code: our own tests and trusted model
outputs → subprocess; strangers → Docker. At scale you remove the start-up cost with a pool of
warm containers, and you reduce the shared-kernel risk with gVisor or Firecracker microVMs. Two
lessons that transfer to eval and RL infrastructure: (1) prove every protection with a hostile
test (our secret-file test reads the secret on subprocess and gets FileNotFoundError in Docker);
(2) measure the details: without `--init`, the runner was PID 1 in the container, Linux ignored
its CPU-limit signal, and the same endless loop was labelled `timeout` in one run and `crashed` in
the next. Unstable labels would have corrupted the Week 2 failure-type statistics.
