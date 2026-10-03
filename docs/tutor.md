# AI tutor (Week 4)

The tutor gives **hints, not answers**. A student asks for a hint; the tutor looks at the
problem, their code and their visible results, finds relevant course notes, and asks a model for
a hint. A **guardrail** checks the hint before the student sees it. Every hint is saved as a row
in Postgres (the trace), and students rate hints 👍/👎.

Status: **Steps 0-1 of 6 are done** (the guardrail, course notes + search). Next: the tutor
pipeline (Step 2), API + UI (Step 3), the offline tutor eval (Step 4), wrap-up (Step 5).

Code: `src/codetutor/tutor/` (`guardrail.py`, `notes.py`, `rag.py`, `retrieval_eval.py`). Tests:
`tests/test_guardrail.py` (labelled hints in `tests/hints/guardrail_cases.yaml`),
`tests/test_notes.py`, `tests/test_rag.py`.

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

## 2. Course notes and search (Step 1)

The tutor should base its hints on course material, the way a teaching assistant looks
something up before answering. This part finds the right note section for a question, and it
is **measured on its own**, before any model writes a hint.

### 2.1 The notes
`course/notes/01_variables.md` … `08_recursion.md`: one per module, named like the bank's
module folders. Each note is an H1 title and 5-6 `##` sections (41 in total, 58-134 words each).
The content follows the bank's concepts and the mistakes the buggy files show, explained in
general (off-by-one with `range`, `split()` vs `split(" ")`, changing an input list, `return` vs
`print`, `dict.get` with a default, base cases, the mutable default argument, …). Written by
Claude, to be reviewed by Najeeb.

`load_notes` checks every rule and lists all broken ones in one error: one note per module
folder, at least 3 sections, 40-350 words per section (far inside the embedder's 2K-token
window), every ```` ```python ```` example parses, and **no line of any bank solution**
appears in a note (the guardrail's `solution_lines` and comparison).

### 2.2 From sections to vectors
- One section = one **chunk**, id `"<file>#<heading slug>"` (e.g.
  `03_loops#while-loops-must-make-progress`). The embedded text is `<title> > <heading>`, a
  blank line, then the body: the title and heading give a short section its context.
- **Embedder:** `nomic-embed-text` v1.5 in Ollama (274 MB, 768 numbers per text, already
  scaled to length 1). Its model card says every text **must** start with a task prefix:
  `search_document: ` for notes, `search_query: ` for questions. `EmbeddingClient` in
  `evals/clients.py` adds them (it shares the chat client's HTTP, retry and error code), and
  `make_embedder` refuses unknown models, because a wrong size or a missing prefix fails
  silently.
- **Storage:** `note_chunks` with `embedding vector(768)` (pgvector 0.8.7, migration 0004). Our
  own small `Vector` column type (`db/vector.py`) replaces the `pgvector` Python package, which
  would need numpy. pgvector stores 4-byte floats.
- **`make notes-sync`** embeds only new or changed sections (another text or another model),
  and deletes removed ones. Measured: 41 sections in 3.0 s; a second run: 41 unchanged, no
  model call.

### 2.3 Three search methods (`rag.py`)
| Method | How | Measured time per question |
|---|---|---|
| `keyword` | Postgres full-text search: any of the question's words (OR), English stemming, ranked by `ts_rank_cd` | ~20 ms |
| `vector` | the question's embedding vs every section's, cosine distance (`<=>`) | ~120-155 ms (mostly the embedding call) |
| `hybrid` | both lists (top 20 each) merged by **reciprocal rank fusion**: score = sum of 1/(60 + rank) | ~160-175 ms |

There is no index: 41 rows are read in full, which is exact and fast. Vector search refuses to
run when the stored sections were embedded by another model (vectors of two models can't be
compared).

### 2.4 Measured (2026-10-03, `lab/tutor/reports/retrieval.md`)
40 labelled questions (`lab/tutor/retrieval_questions.yaml`, 5 per module): 15 `concept`
("what is a base case?") and 25 `symptom` ("my while loop never ends and the test times
out", "TypeError: unhashable type: 'list'"). A hit = a relevant section in the top k.

| Method | recall@1 | recall@3 | MRR@10 | recall@3 concept | recall@3 symptom |
|---|---|---|---|---|---|
| keyword | 25/40 | 34/40 | 0.755 | 14/15 | 20/25 |
| vector | **35/40** | 39/40 | **0.931** | 15/15 | 24/25 |
| hybrid | 33/40 | **40/40** | 0.900 | 15/15 | 25/25 |

- **Keyword search misses paraphrases:** "add up numbers in a loop" doesn't find "the
  accumulator pattern"; "takes forever" doesn't find "fast enough". It is fine when the student
  pastes an error message (the notes quote them).
- **Vector search** misses one question: "my grade function says D for a score of 95". The
  answer (the order of the conditions) needs reasoning, not similar words.
- **Choice for Step 2: hybrid** (the plan's rule: best recall@3, because the tutor puts the top
  3 sections into its prompt). Honestly, it is one question ahead of vector (40 vs 39), and
  vector is better at rank 1. With 40 questions, one question is 2.5 points: these three
  numbers say "vector and hybrid are both good, keyword is clearly worse", not more.
- The report is byte-identical across two runs (Ollama's embeddings are deterministic here).

### 2.5 Limits
- **Same author:** Claude wrote the notes and the questions. The questions were written first
  (from the buggy files), but the numbers are still optimistic. The best check: questions
  written by someone else (Najeeb, or real students later).
- Where two sections both answer a question, both count as relevant (4 of 40 questions); those
  second labels were added after the notes existed.
- The tutor's real search text will be built from the student's code and test results
  (Step 2), not typed by a student. Measure again then.
- `embed_model` stores the model's name, not its digest: re-pulling a newer `nomic-embed-text`
  would not trigger re-embedding. Run `make notes-sync` after pulling, and check the report.
