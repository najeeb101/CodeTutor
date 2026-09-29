# Problem format

This document explains how one problem is stored on disk, what every field means, and the rules
a problem must follow. The code that enforces these rules is
`src/codetutor/problems/schema.py` (the rules) and `src/codetutor/problems/loader.py` (reading files).

## 1. One folder per problem

```
problems/<course>/<NN>_<module_slug>/<problem_slug>/
├── problem.yaml     # metadata and description
├── starter.py       # what the student sees first (signature + docstring + pass)
├── solution.py      # reference solution, never shown to students
├── tests.yaml       # test cases
└── buggy/           # 1–3 realistic WRONG solutions, named after the mistake
    ├── off_by_one.py
    └── ...
```

Example: `problems/cs1/03_loops/sum_of_evens/`.

**Why folders and not one big JSON file?** Code inside JSON strings (escaped newlines and quotes)
is hard to read, review and diff. Real `.py` files can be opened, run and linted. A build script
(Step 3) compiles all folders into one `dist/problems.jsonl` file for machines.

**The folder decides the id.** The folder `cs1/03_loops/sum_of_evens` must contain a problem with
`id: cs1.loops.sum_of_evens` and `module: 3`. The loader rejects a mismatch, so ids and folders
can never drift apart.

## 2. `problem.yaml`

| Field | Type | Rules |
|---|---|---|
| `id` | text | `<course>.<module_slug>.<problem_slug>`, lowercase letters, digits and `_`. **Never changes.** |
| `version` | integer ≥ 1 | Start at 1. Increase it whenever the tests or the expected behaviour change. |
| `title` | text | Human-readable name, e.g. "Sum of Even Numbers". |
| `module` | integer 1–8 | Must match the `NN` in the folder name. |
| `module_name` | text | e.g. "Loops". |
| `order` | integer ≥ 1 | Position inside the module. Two problems can't share the same module and order. |
| `difficulty` | `easy` / `medium` / `hard` | |
| `concepts` | list | From a fixed list: `arithmetic`, `conditionals`, `for_loops`, `while_loops`, `strings`, `lists`, `dicts`, `functions`, `recursion`, `sorting`, `searching`, `edge_cases`, `efficiency`. No duplicates. |
| `function_name` | text | A valid Python name; must be defined at the top level of `starter.py` and `solution.py`. |
| `description_en` | text | The problem statement: inputs, output, constraints, 1–2 examples (matching visible tests). |
| `description_ar` | text or `null` | Arabic version, later. |
| `hints` | list of exactly 3 | (1) a nudge, (2) a more specific approach, (3) almost pseudocode, but **not code**. |
| `time_limit_s` | number, optional | Per-test time limit in seconds (default 2.0, max 10). |
| `author` | `najeeb` / `claude` | Who wrote the problem. |

Unknown keys are **errors**. A typo such as `dificulty:` is reported instead of being silently
ignored.

**The "no code in hints" check is a simple heuristic.** It rejects ``` code fences and lines that
start with a Python keyword (`for i in range(n):`). It does not catch code written inside a
sentence. Reviewing hints by eye is still needed.

## 3. `tests.yaml`

```yaml
tests:
  - {id: t01, input: [10], expected: 30, hidden: false, compare: exact, note: "example 1"}
  - {id: t05, input: [0],  expected: 0,  hidden: true,  compare: exact, note: "edge: zero"}
```

| Field | Rules |
|---|---|
| `id` | Unique within the problem; lowercase letters, digits, `_` (we use `t01`, `t02`, …). |
| `input` | **Always a list of arguments.** One argument `10` → `[10]`. One list argument `[3, 1]` → `[[3, 1]]`. |
| `expected` | The correct return value. **Never typed by hand:** `scripts/fill_expected.py` (Step 3) runs `solution.py` to fill it. `null` is a real value (e.g. "no answer → `None`"). |
| `hidden` | **Required** (`true`/`false`). Hidden tests are never shown to students or to models. |
| `compare` | `exact`, `unordered` or `float` (see below). Required. |
| `note` | Optional explanation for humans. Put comments here, not as `#` YAML comments, because `fill_expected.py` rewrites the file and would lose them. |

Rules:
- At least **8 tests**, at least **3 visible** and at least **3 hidden**.
- Hidden tests must include the **edge cases** (empty input, zero, negative numbers, single element,
  duplicates, large values; whatever applies). Visible tests alone should not catch every bug.
- Values must be **JSON-compatible**: numbers, strings, `true`/`false`, `null`, lists, and dicts with
  string keys. No tuples, sets, dates, NaN or infinity. If a function "returns a pair", the problem
  says it returns a **list**.

### Compare modes
- `exact`: equal after turning tuples into lists. `True` and `1` count as **different** (Python says
  `True == 1`, but a function that should return a number must not pass by returning `True`).
- `unordered`: the same items with the same counts, in any order.
- `float`: numbers are close enough (`math.isclose`, rel_tol 1e-6, abs_tol 1e-9), also inside lists.
  Booleans are not numbers here.

(The comparison code arrives in Step 2.)

### YAML pitfalls
- YAML turns some words into booleans: `yes`, `no`, `on`, `off`, `true`, `false`. If a test needs
  the **string** "no", write `"no"` with quotes.
- Unquoted text that looks like a date (`2026-01-01`) becomes a date, which is rejected. Quote it.
- When in doubt, quote strings.

## 4. Two views of a problem

- **Internal view**: the full `Problem` (everything). Used by the grader, validator, evals and training.
- **Student view**: `problem.to_student_view()` → `StudentProblem`. It contains the metadata,
  description, starter code and the **visible** tests (called `examples`). It does **not** contain
  the solution, the buggy solutions, hidden tests or hints. Hints are given out one at a time by
  the tutor later. Week 2 evals give models this same view, so models see exactly what students see.

## 5. Full example

`problems/cs1/03_loops/sum_of_evens/`: see the files in that folder. It has 9 tests (4 visible,
5 hidden) and 3 buggy solutions:
- `off_by_one.py`: `range(2, n, 2)` forgets `n` itself (caught by visible tests).
- `sums_odds.py`: wrong condition (caught by visible tests).
- `negative_crash.py`: raises an error for negative `n` instead of returning 0. It passes every
  visible test and fails only the hidden negative test. This is why hidden tests exist.

## 6. How to add a problem

1. Create the folder `problems/cs1/<NN>_<module>/<slug>/` (the folder decides the id).
2. Write `problem.yaml`, `starter.py` (signature + docstring + `pass`), `solution.py`.
3. Write `tests.yaml` with **inputs only** (no `expected`).
4. Write 1–3 buggy solutions in `buggy/`, named after the mistake.
5. Check it loads:
   `uv run python -c "from codetutor.problems import load_problem; from pathlib import Path; print(load_problem(Path('problems/cs1/03_loops/sum_of_evens'), require_expected=False).title)"`
6. `uv run python scripts/fill_expected.py <folder>` (writes `expected`; the file is fully
   regenerated, so `#` comments are lost; use `note`).
7. `make validate`. Fix every ❌. A buggy solution that passes all tests means a test is missing.
8. Try it like a student: `uv run python scripts/grade_cli.py <problem_id> <file.py>`.
9. `make build` writes `dist/problems.jsonl` and `dist/problems_student.jsonl`.
