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
