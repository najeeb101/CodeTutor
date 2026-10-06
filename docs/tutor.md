# AI tutor (Week 4)

The tutor gives **hints, not answers**. A student asks for a hint; the tutor looks at the
problem, their code and their visible results, finds relevant course notes, and asks a model for
a hint. A **guardrail** checks the hint before the student sees it. Every hint is saved as a row
in Postgres (the trace), and students rate hints 👍/👎.

Status: **Week 4 is done** (Steps 0-5: the guardrail, course notes + search, the pipeline, the
tutor worker + API + UI, the offline tutor eval, the wrap-up).

Code: `src/codetutor/tutor/` (`guardrail.py`, `notes.py`, `rag.py`, `retrieval_eval.py`,
`context.py`, `prompt.py`, `service.py`, `safety.py`, `jobs.py`, `loop.py`,
`tutor_eval.py`, `tutor_eval_report.py`). Tests:
`tests/test_guardrail.py` (labelled hints in `tests/hints/guardrail_cases.yaml`),
`tests/test_notes.py`, `tests/test_rag.py`, `tests/test_tutor.py`, `tests/test_tutor_safety.py`,
`tests/test_tutor_jobs.py`, `tests/test_api_hints.py`, `tests/test_tutor_eval.py`.

Decisions for the whole week (2026-10-02):
- **Our own model client** (`evals/clients.py`), not LiteLLM.
- **Traces are rows in Postgres** (prompt version, model, retrieved notes, guardrail result,
  time, tokens, rating). Langfuse Cloud was optional, at the end; **not added** (2026-10-06):
  the `hints` table already holds the whole trace, and Langfuse would send hint data off the
  machine. A deviation from the brief; the idea is in [ideas.md](ideas.md).
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

## 3. The pipeline: one hint (Step 2)

`give_hint(request, *, model, session, embedder, config) -> HintResult` (`service.py`):

```
level 3 ──────────────────────────────────────────────► reference hint 3 (bottom-out, no model)
level 1-2: search notes (hybrid, top 3) → prompt → model → checks ─ ok ──► the model's hint
                                                      │ blocked
                                                      ▼
                                   one retry ("it contains code, write it in words") ─ ok ──►
                                                      │ still blocked, or the call failed
                                                      ▼
                                          the reference hint of that level ("fallback")
```

`give_hint` never raises for a model or search failure: a failed search means no notes (the
error is kept), a failed call means the reference hint. A failed call is not retried here (the
client already retries transient errors); a blocked hint is retried once.

### 3.1 What the model sees (`context.py`, `prompt.py`)
- **Yes:** the problem text and function name, the student's code (cut at 2,000 characters),
  the student's question, the visible tests as Python calls with expected vs got (or the error),
  the hidden tests **only as counts**, the top 3 note sections, the reference hints **up to the
  current level**, and the hints it already gave for this code.
- **Never:** `solution.py`, hidden inputs or expected values, the bottom-out hint 3, the
  student's print output. `HintRequest` refuses a grade result that reveals a hidden test.
- **Prompt injection:** the system message says the student's code and question are data, not
  instructions; both sit in labelled code fences that are always longer than any run of
  backticks inside them, so the student's text can't close the fence and add "instructions".
  The output checks are the real protection: whatever the model writes, a hint with code is
  never shown.
- `TUTOR_PROMPT_VERSION = "1"`, pinned by a test (like the eval prompt). The retry message
  says only "it contains code": naming the blocked solution line would tell the model what the
  solution looks like.

### 3.2 The checks on every reply
The guardrail (§1, with the student's own code allowed), an empty reply, more than 80 words, and
a **prompt that may have been cut**.

Ollama gives a model a 4,096-token window by default (its FAQ), and our OpenAI-style calls can't
change it. Measured on 2026-10-03 with a code word that only the system message contained: a
3,948-token prompt kept it (the model answered with the code word); prompts of about 5,400 and
18,000 tokens were **cut to about 2,050 tokens, keeping the end**, and the model made up a code
word. So an over-long prompt silently loses the rules, and it reports *fewer* tokens than the
window: a check for "close to 4,096" would never catch it. Rule: prompts stay under **2,048**
tokens (half the window). Before sending, `ceil(characters / 3)` must be below that; after the
reply, a reported `prompt_tokens` of 2,048 or more counts as "maybe cut" and is never shown.

### 3.3 The trace: the `hints` table (migration 0005)
`save_hint` stores the shown `text`, `source` (`model` / `fallback` / `reference`), level,
question, the student's code, the model and prompt version, the settings, the search text and
the found sections (id, hash, score), **every attempt** (text, issues, error, time, tokens), the
total time, and `rating` / `rated_at` (Step 3). Blocked attempts can contain solution code, so an
API must only ever return `text`. Offline runs have no `user_id`.

`scripts/ask_tutor.py` grades a file (Docker by default), gives one hint, prints the trace and
saves it.

## 4. The tutor worker, the API and the UI (Step 3)

```
browser ──POST /api/hints──► API ──insert hints row (queued)──► Postgres
   ▲                                                              │ claim (SKIP LOCKED + lease)
   └──GET /api/hints/{id} (poll 1 s)◄── text when done ◄── tutor worker: give_hint → save
```

**Why a separate worker, not the API.** A hint needs the sealed problem copy: the solution
for the guardrail and the teacher's hints. Only the workers read `problem_versions`; the API
never does (a source-scan test). So the API only saves a request, and `make tutor`
(`scripts/tutor_worker.py`, `tutor/loop.py`) answers it. This also keeps a slow model off the
API's request threads.

**The queue** (`tutor/jobs.py`) is the grading queue's design ([worker.md](worker.md)): the
`hints` row is the job (migration 0006), `FOR UPDATE SKIP LOCKED` claims, a 5-minute lease,
`claims` as the fencing token (a late save after a lost lease writes nothing), 3 claims then
`failed`. A model that is down or writes code is **not** a job error: `give_hint` already
falls back to the teacher's hint, so the student always gets one. Job errors are ours
(database, a broken problem copy). While the model works, no transaction is open: the note
search reads through an AUTOCOMMIT engine copy.

**What the worker gives `give_hint`:** the sealed problem copy, the code, the level and the
question, the submission's stored result (graded with `reveal_hidden=False`) when the request
is about a submission, and up to 3 earlier hints of this user for the same code ("don't repeat
them").

**Keeping the model loaded.** Ollama unloads a model 5 minutes after its last request.
Measured on 2026-10-05: loading the 7B again took **13.3 s and 12.0 s** (109 s right after a
reboot, with a cold disk); the 7B (4.42 GiB) and nomic-embed-text (0.3 GiB) fit on the GPU
together (5.1 of 8 GB used). So the worker loads both at start (`keep_loaded()` in
`evals/clients.py`: Ollama's own `/api/generate` with no prompt for the chat model,
`/api/embed` with an empty list for the embedder, `keep_alive: "10m"`) and refreshes them
every 4 minutes. Checked live: at the 4-minute mark both expiry times moved 10 minutes ahead.
When the worker stops, Ollama unloads both 10 minutes later by itself. A failed refresh only
logs a warning. If the model can't be reached at start, the worker stops with a clear message:
running on fallbacks only would be silent.

**Levels, limits, rating** (the API side, [api.md](api.md)): levels go in order (1 → 2 → the
last hint); 1 waiting request and 10 per 10 minutes per user; the API returns only the 12
fields of `HintOut`, never the trace; 👍/👎 is changeable, the last one wins.

**The UI** (`web/components/HintPanel.tsx`): an optional question, "Get a hint" (level 1, then
"Get a more specific hint" for level 2), "Show the last hint" after level 2 with a warning
("gives away most of the answer"), each hint with its level and source ("from the AI tutor" /
"from your teacher") and 👍/👎. The hint is about the shown submission when the editor holds
exactly its code, else about the editor's code. While waiting: "The tutor is thinking…", and
after 10 s "The first hint after a break can take up to 2 minutes". A request still waiting
after a page reload is followed again.

**Measured live (2026-10-05, real 7B, buggy fizzbuzz):** level 1 3.8 s and level 2 5.7 s from
request to answer (the level 2 reply was blocked once, the retry was shown), level 3 0.8 s
(no model call; the worker polls every second). `make e2e`: 11/11 checks (the hint 5.5 s);
`make web-e2e`: 9/9 (ask + 👍 in the browser 2.8 s; the rated hint is still shown after a
reload; gone after logout).

### 4.1 Limitations
- With temperature 0.2 and seed 0 the same situation gives the same hint word for word. A
  student who asks again about the same code gets a different prompt (the earlier hint is in
  it), so usually a different hint.
- The level 2 hint for fizzbuzz says "The student's code…" although the prompt says "talk as
  you", and it nearly states the fix. Step 4 measured it: 16 of 54 level-2 hints do this (§5.1).
- One tutor worker answers one hint at a time (one GPU). With many students the queue grows;
  `Retry-After` and the 1-waiting limit keep it fair, not fast.
- The model's name is stored per hint, but not the Ollama model digest (same as the notes).

## 5. The offline tutor eval (Step 4)

**The question.** Does a hint help a student fix a bug? A real student is not available, so a
small model plays the student, and `grade()` decides whether the fix worked (the same grader
as everywhere else).

**Situations.** A situation is one buggy file whose bug is **hidden-only**: every visible test
passes, a hidden test fails. That is the moment a real student asks for a hint ("my code looks
right, why is it wrong?"). The bank has **54** such buggy files in 33 problems (the plan
guessed ~50).

**Conditions** (6): `none` (no hint), `teacher-1`, `teacher-2`, `teacher-3` (the bank's
reference hints; hint 3 is the bottom-out hint, §1.4), `tutor-1`, `tutor-2` (the 7B tutor's
hint, made by `give_hint` exactly as in the app: notes search, guardrail, retry, fallback).

**The student** is `qwen2.5-coder:1.5b-instruct-fp16` (temperature 0.8, seed i for answer i,
max_tokens 1024, 5 answers per situation and condition). Its prompt is the Week 2 problem
prompt + the buggy code + what the grader showed (`describe_result`: hidden failures as counts
only) + the hint + one task line. The prompt text is pinned by a sha256 in a test.

**Metrics** (`tutor_eval_report.py`). Fix rate = accepted answers / answers, first per
situation, then the mean (every situation counts the same). **Help** = a condition's fix rate
minus the no-hint fix rate *in the same situation* (a paired difference), with a 95% bootstrap
interval over situations (2000 resamples, seed 0).

**Running it.** `uv run python scripts/tutor_eval.py` (Ollama + Docker + `make db-up`). It
makes the tutor hints first, then the answers; every record is appended to
`lab/tutor/results/tutor-eval-<student>.jsonl` as soon as it exists, so Ctrl+C and a rerun
continue where it stopped. The `.meta.json` file holds the settings and the problem versions; a
rerun with other settings stops with an error. `--report-only` rebuilds
`lab/tutor/reports/tutor_eval.md` (byte-identical for the same records). `--limit N` is a
scratch run (gitignored folder).

### 5.1 Measured (2026-10-05 pilot + 2026-10-06 full run)

The no-hint pilot (270 answers) ran on 2026-10-05 on battery (5.7 s per answer). The other
1,350 answers ran on 2026-10-06 in 63 minutes (mostly on mains, ~2.4 s per answer, Docker
grading). 1,619 answers were graded; **1 call failed** (below).

| Condition | Fix rate [95%] | Help vs `none` [95%] | Situations better / worse / same |
|---|---|---|---|
| `none` | 0.58 [0.49, 0.67] | – | – |
| `teacher-1` | 0.66 [0.57, 0.75] | +0.09 [+0.03, +0.15] | 24 / 12 / 18 |
| `tutor-1` | 0.62 [0.54, 0.71] | +0.04 [−0.02, +0.11] | 19 / 13 / 22 |
| `teacher-2` | 0.63 [0.54, 0.72] | +0.05 [−0.03, +0.13] | 20 / 15 / 19 |
| `tutor-2` | 0.63 [0.54, 0.72] | +0.06 [−0.03, +0.15] | 24 / 17 / 13 |
| `teacher-3` | 0.70 [0.61, 0.79] | +0.12 [+0.04, +0.21] | 24 / 9 / 21 |

Tutor vs teacher, paired the same way (the report's "Tutor vs teacher" table):
`tutor-1 − teacher-1` = −0.04 [−0.10, +0.02] (11 better / 17 worse); `tutor-2 − teacher-2` =
+0.01 [−0.09, +0.10]; `tutor-1 − teacher-3` = −0.08 [−0.18, +0.02].

**The tutor's hints** (108): level 1: 52 from the model, 2 fallbacks (both tries blocked);
level 2: 54 from the model (4 needed the retry). Median 19 / 41 words, ~1.2 / 1.4 s each.
**16 of 54 level-2 hints talk about "the student"** instead of "you" (2 of 52 at level 1),
although the prompt says "talk as you".

What the numbers say, and what they don't:
- Only `teacher-1` and `teacher-3` help with an interval above 0. The tutor's hints help a
  little on average (+0.04, +0.06), but the intervals include 0: **with 54 situations and 5
  answers each, we can't tell them from "no help".**
- No sign that `tutor-1` gives the answer away: it is below `teacher-3` (the bottom-out hint)
  by −0.08, but the interval [−0.18, +0.02] just reaches 0, so this is a hint, not a proof.
  It is a little below `teacher-1` (−0.04), also not significant.
- More detail is not always more help: `teacher-2` (0.63) is below `teacher-1` (0.66).
- **Hints also hurt.** In every condition 9-17 situations got worse. A clear example:
  `group_anagrams/ignores_letter_counts` (the bug: `set(word)` drops repeated letters) fell
  0.80 → 0.00 with `tutor-2`. The teacher's hint 1 lists three things to check, one of them
  "repeated words"; the tutor picked that one and told the student to fix repeated words. A
  wrong diagnosis sends the student the wrong way.
- One level-2 tutor hint is close to a recipe (`reverse_words`: "use `sentence.split()` without
  any arguments, then reverse the list and join"). The guardrail allows it on purpose (an
  expression, no solution line), and it only repeats the teacher's own hint 2, which the model
  sees at level 2.

**The failed call.** `factorial/zero_returns_zero`, `teacher-2`, answer #1: Ollama answered
HTTP 500 "token repeat limit reached" (the student model repeated itself) 5 times, so it was
never graded (the Week 2 rule: a failed call is not an answer). With a fixed seed a rerun
gives the same loop, so that situation has 4 answers in `teacher-2`. Counting it as "not
fixed" would move `teacher-2` by 0.2 / 54 ≈ 0.004.

### 5.2 Limits
- The student is a 1.5B model, not a person. A model can fix code by rewriting the whole
  function, without reading the hint; a hint that helps a model may not teach a human.
- One student model, one tutor model, one prompt version each. Seeds make the run repeatable,
  not representative: other seeds give other answers.
- 54 situations × 5 answers: one situation moves a fix rate by 1.9 points, and differences of
  ~0.05 are inside the noise. More answers per situation (n = 10) would narrow the intervals
  by about √2 at twice the time.
- The bank's hints, the buggy files, the course notes and this eval were all written by the
  same author (Claude). Hidden-only bugs are only one kind of situation; hints for code that
  fails visible tests are not measured here.
