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

## Unbiased pass@k (Week 2, Step 1)
pass@k is the chance that at least one of k attempts passes. We draw n ≥ k samples per problem,
count the c that pass, and use the estimator from the Codex paper (Chen et al. 2021):
`1 − C(n−c, k) / C(n, k)`, which is 1 minus the chance that k samples picked from our n all fail.
Why not plug the pass rate into `1 − (1 − c/n)^k`? Because that is **biased low**: `(1 − x)^k`
is curved (convex), so a noisy estimate of the pass rate overestimates the failure chance on
average (Jensen's inequality). Worked example: true pass rate p = 0.5, n = 2, k = 2, so the true
pass@2 = 1 − 0.5² = 0.75. Outcomes: c = 0 (chance 0.25) → both formulas give 0; c = 1 (chance 0.5)
→ unbiased 1.0, naive 0.75; c = 2 (chance 0.25) → both give 1. Averages: unbiased 0.75 (right),
naive 0.625 (too low). In code, compute the ratio as a product of (1 − k/i) for i = n−c+1 … n, so
there are no huge factorials. Two practical points: pass@k with k > 1 only means something with
temperature > 0 (at temperature 0 every sample is nearly the same, so pass@k ≈ pass@1), and a
bigger n than k lowers the variance of the estimate.
*How I'd say it:* "I use the unbiased estimator and sample n > k. I test it against brute-force
enumeration of every k-subset, and I check that it is unbiased exactly, by averaging it over the
binomial distribution of outcomes."

## Reliable model calls in an eval pipeline (Week 2, Step 2)
An eval run makes hundreds of API calls, and some will fail. The key idea: **sort each failure by
what reaction helps**. Transient failures (429 rate limit, 5xx, timeouts) are retried with
*exponential backoff* (wait ~2, 4, 8, 16 s), honouring the wait the server asks for
(`Retry-After`). Add *jitter* (a random part of the wait): without it, many clients that failed
together retry together and overload the server again (the "thundering herd"). Config errors
(401 wrong key, 404 wrong model) **fail fast**: retrying can't fix them and only hides the bug.
A used-up daily quota **stops the run**, which resumes later from the results file (each saved
sample is skipped, so a resumed run never pays twice). The most important rule for the metric:
**a failed API call is never graded**. An infrastructure failure is not a model failure;
scoring it as "wrong" would quietly push pass@k down, and you'd blame the model for your network.
*How I'd say it:* "I separate infrastructure errors from model errors. Infra errors are retried
or stop the run, but they never enter the metric; only real model outputs get graded. And I test
the retry logic against a local fake server, so every branch (429, 503, 401, timeout, quota)
is exercised without the internet."

## Reproducible eval runs (Week 2, Step 3)
An eval number is only useful if you can say exactly what produced it and get it again. Four
habits make that true. (1) **Config + meta**: every run is one config file, and a meta file
records what the config can't: prompt version, grader version, problem versions, git commit
(and whether the code had uncommitted changes), and the exact model weights (Ollama's digest
and precision, e.g. F16). If any of these changes, the harness refuses to add answers to the
old file, because mixed answers can't be compared. (2) **Append-only, resumable results**: each
answer is written the moment it is graded; rerunning the same config asks only for the missing
ones. A crash, Ctrl+C or a used-up quota costs almost nothing, and you never pay twice for an
answer. (3) **Seeds and order**: sample i gets seed i, and calls go one at a time in a fixed
order, because a server that batches parallel requests can change the numbers. With Ollama the
same seed really gave the same reply (checked). (4) **Infra failures stay out of the metric**:
a failed API call is retried or skipped, never graded as "wrong".
*How I'd say it:* "Every number in my report traces back to one results file and one meta file:
the exact weights, prompt, grader and commit. Runs are resumable and append-only, and I checked
that re-running a seeded sample reproduces the same answer byte for byte."

## Reading eval results (Week 2, Step 4)
One number hides a lot, so read four things together. (1) **pass@1 vs pass@k**: Qwen 1.5B has
pass@1 0.867 but pass@10 1.000, so it *can* solve every problem, just not reliably. That gap is
what RL training (GRPO) works on: it rewards the good answers the model already finds sometimes.
(2) **Mean reward vs pass rate**: mean reward 0.953 is much higher than pass@1, so most wrong
answers are *nearly* right (e.g. one tie case). Partial credit is a smoother training signal, but
it also pays for near-misses. (3) **Hidden-only failures**: 15 of 44 wrong answers passed every
visible test. That is what overfitting to the examples looks like; without hidden tests those
answers would count as correct, and a model trained on that reward would learn to satisfy the
examples instead of the spec (reward hacking). (4) **Error bars**: with 33 problems the 95%
bootstrap interval for pass@1 is 0.78–0.94, so a difference of a few points between two models
can be noise. Also slice the results (module, difficulty, concept) and read the actual failures:
here Conditions and Dictionaries are weak, and the most failed test's own note explains why
("tie for the largest").
*How I'd say it:* "I never report a single accuracy. I show pass@1 with a bootstrap interval,
pass@k for headroom, partial credit, and the share of failures only hidden tests catch, then I
read the failing cases, because the aggregate rarely tells you what to fix."

## Comparing two models fairly (Week 2, Step 4b)
A comparison is only fair if one thing changes. Both official runs use the same 33 problems,
the same prompt version, temperature 0.8, seeds 0–9, max_tokens 1024 and Docker grading; the
configs differ only in the model (checked by loading both and diffing them). Anything else that
differs is a **confounder**, and you name it instead of hiding it: here the 7B is 4-bit and the
1.5B is fp16 (the fp16 7B does not fit an 8 GB GPU), so "7B vs 1.5B" is really "bigger *and*
more rounded". Two more habits: (1) **check the numbers that look odd**. The 7B has a higher
pass@1 (0.945 vs 0.867) but a slightly lower pass@5 (0.978 vs 0.983); the reason is one problem
where it got 1 of 10 right instead of 2, which is noise, not a weakness. Also "0.57 vs 0.58" on
Dictionaries was the same true value (0.575) printed after float rounding. (2) **Read the
failures of both models**: both fail a test they can *see* in the prompt (group_anagrams example
1) because they sort in the wrong order. A model that cannot run code can't check itself
against the examples.
*How I'd say it:* "I compared models with identical configs except the model, pinned the seeds
so every answer can be reproduced, named the one confounder I couldn't remove (quantization),
and checked every surprising number back to the raw answers before believing it."

## HTTP 200 is not success (Week 2, finish_reason fix)
An API can say "OK" (HTTP 200) and still have failed: OpenRouter sometimes sends a normal-looking
reply with empty content and `finish_reason: "error"`, because the provider broke mid-answer.
This is an **in-band error** (the failure is inside the payload, not in the status code). If the
eval code trusts the status code, the empty answer is graded as a compile error, and the model
is blamed for an infrastructure problem: pass@k goes down for no real reason, and in RL the
model would get reward 0 for an answer it never gave. The fix is to check the payload too and
treat this like a 503: retry, and if it keeps failing, record a failed call that is never
graded. Partial text from a failed reply is thrown away. `"length"` (cut off by max_tokens) is
different: that is the model's real answer, so it is graded and counted separately.
*How I'd say it:* "In my eval client a failure is classified by what happened, not by the status
code: a 200 with finish_reason 'error' is retried like a 5xx and never graded, because
infrastructure noise must never end up in the model's score or in the reward."
