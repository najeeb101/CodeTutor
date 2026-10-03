# AI tutor (Week 4)

The tutor gives **hints, not answers**. A student asks for a hint; the tutor looks at the
problem, their code and their visible results, finds relevant course notes, and asks a model for
a hint. A **guardrail** checks the hint before the student sees it. Every hint is saved as a row
in Postgres (the trace), and students rate hints 👍/👎.

Status: **Step 0 of 6 is done (the guardrail).** Next: course notes + retrieval (Step 1), the
tutor pipeline (Step 2), API + UI (Step 3), the offline tutor eval (Step 4), wrap-up (Step 5).

Code: `src/codetutor/tutor/`. Tests: `tests/test_guardrail.py`, with labelled hints in
`tests/hints/guardrail_cases.yaml`.

Decisions for the whole week (2026-10-02):
- **Our own model client** (`evals/clients.py`), not LiteLLM.
- **Traces are rows in Postgres** (prompt version, model, retrieved notes, guardrail result,
  time, tokens, rating). Langfuse Cloud is optional, at the end.
- **The model never sees `solution.py`.** It gets the problem text, the 3 reference hints, the
  student's code and their visible results (hidden tests: only pass/fail counts).
- **Hint 3 is the "bottom-out" hint** (§1.4).

## 1. The guardrail

`check_hint(text, problem, *, student_code="") -> list[Violation]` returns every reason a hint
must not be shown; an empty list means it is OK. A `Violation` has a `kind` and a `detail` (the
text that broke the rule, cut at 200 characters). The detail goes into the trace and is never
shown to the student.

### 1.1 Rules

| Kind | Blocks | Example |
|---|---|---|
| `solution_line` | a non-trivial line of `solution.py`, anywhere in the hint (spaces and quote style ignored) | "set a, b = b, a % b in a loop" (gcd) |
| `code_block` | a fenced block (```` ``` ```` or `~~~`, also inline), or 2+ lines in a row that are Python and start with a statement | a `for` loop over two lines |
| `code_statement` | one whole line that is a statement, or a `` `backtick` `` span that is a statement | "Use `count += 1`" |

- **The solution's lines** (`solution_lines(problem)`, also used by the e2e checks): every line
  of `solution.py` without comments (cut with `tokenize`, so a `#` inside a string stays),
  docstrings, and lines that are also in the starter code or the description (the `def`
  line). **Trivial** lines are left out too, because they say nothing about the answer:
  `return` + a name or constant, a name set to a simple value (`count = 0`, `i += 1`,
  `result = []`), `else:`, and headers made of plain words (`for word in words:`,
  `if need in seen:`). That leaves 116 lines in the bank, at least one per problem.
- **Statement vs expression:** a fragment is parsed with `ast.parse`. Expressions stay allowed
  (`number % 15 == 0`, `fizzbuzz(15)`), because the reference hints use them. `Example:
  fizzbuzz(15)` parses as an annotation without a value; that counts as prose.
- **Always allowed:** text that is also in the starter code, the problem description or the
  **student's own code**. Quoting a student's line back ("your `if number % 3 == 0:` runs
  first") is good tutoring, and a solution line the student already wrote is not a secret.

Rejected while measuring: "anything that parses as Python is code". It would block 9 of 33
hint 1s, because English like "first: 2024" or "return the" is valid Python.

### 1.2 Measured (2026-10-03)

| Set | Hints | Result |
|---|---|---|
| The bank's hints 1 and 2 (written for students) | 66 | **0 blocked** (no false alarm) |
| The bank's hint 3 (bottom-out, §1.4) | 33 | 9 blocked, each for a real solution line (pinned in the test) |
| Generated leaks: the full solution (fenced, unfenced), and each of the 116 solution lines in a sentence and in backticks | 298 | 298 blocked |
| Hand-written good hints | 10 | 10 passed |
| Hand-written leaks | 10 | 10 blocked |
| Hand-written strict case (`low = 0` in backticks) | 1 | blocked: an accepted false alarm |
| Hand-written known misses | 3 | 3 passed (missed, see §1.3) |

The generated leaks are caught **by construction** (each contains a solution line). They test
the details (spacing, quotes, fences, comments), not cleverness. The hard cases are the
hand-written ones, and real model hints from Step 2 onward. The tests run in ~0.5 s.

### 1.3 What it does not catch (known misses)

It compares text and parses code; it does not understand meaning.
- **Code inside a sentence** without backticks passes, unless it is a solution line. Example: a
  *different* full solution written as a one-liner in a sentence.
- **Renamed variables:** "tally[w] = tally.get(w, 0) + 1" is word_frequency's solution line with
  other names.
- **An algorithm in plain words** passes on purpose: hints are words. A whole algorithm is fine
  as a last hint and too much as a first one, but the guardrail can't tell the levels apart.
  That's the prompt's job (Step 2).

So the guardrail is one layer. The others: the model never sees `solution.py` (it can still
solve most problems by itself: the 7B model's pass@1 is 0.945), the prompt asks for words only,
and a blocked hint is never shown (Step 2: one retry, then the reference hint).

### 1.4 Hint 3 is the "bottom-out" hint

The brief asks for hint 3 to be "near-pseudocode but NOT code". In 9 problems, our own hint 3
contains a line of `solution.py` (e.g. recursive_sum's `return nums[0] +
recursive_sum(nums[1:])`). The Week 1 check (`"```"` or a line starting with a keyword) missed
them, because the code sits inside a sentence. Najeeb's decision (2026-10-02): keep them. In
tutoring systems the last hint is often a **bottom-out hint** that nearly gives the answer.
The UI will show hint 3 only when the student asks for the last hint (Step 3). The AI tutor is
held to the strict rule at every level. This is a deviation from the brief, and the test pins
the 9 problems.
