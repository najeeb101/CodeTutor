# Integrity checks and skill estimates (Week 5)

Week 5 adds **signals for a human**: which submissions look copied, pasted or AI-written, and
how hard each problem and how skilled each student is. Flags never punish anyone by themselves
(brief, principle 6): they come with reasons, and a teacher decides.

Status: **Step 0** (editor summary per submit, [api.md](api.md) §1), **Step 1** (the
simulated class, generated, loaded and graded, §1), **Step 2a** (a harder class + held-out seed
1, §1), **Step 2b** (the checks and `integrity_flags`, §2) and **Step 2c** (thresholds chosen
on seed 0 and frozen as version 1, measured on held-out seed 1, §2.4) and **Step 3**
(difficulty and skill, §3) are done. Next: Step 4 (wrap-up).

Code: `src/codetutor/sim/` (`personas.py`, `pools.py`, `transforms.py`, `editor.py`,
`cohort.py`, `load.py`), `scripts/sim_cohort.py`, `src/codetutor/db/admin.py`;
`src/codetutor/integrity/` (`normalize.py`, `signals.py`, `known_ai.py`, `store.py`,
`evaluate.py`, `report.py`), `src/codetutor/skill/` (`rasch.py`, `load.py`, `evaluate.py`,
`report.py`), `scripts/integrity.py`, `scripts/skill.py`. Tests: `tests/test_sim.py`,
`tests/test_sim_db.py`, `tests/test_integrity.py`, `tests/test_integrity_eval.py`, `tests/test_skill.py`. Reports:
`lab/integrity/reports/integrity.md`, `lab/skill/reports/skill.md`.

## 1. The simulated class (Step 1)

Real students aren't available (brief §3.6), so we simulate a class whose behaviour we
**know**: who copied, from whom, who pasted an AI answer, and every student's true skill. That
ground truth lets Steps 2 and 3 *measure* their detectors and estimates (precision, recall,
correlation with the true skill) instead of guessing.

### 1.1 How a student works
- 60 students, each with a persona and a hidden true skill θ (strong ≈ +1.5, average ≈ 0,
  struggling ≈ −1.5, spread 0.5). Each problem has a true difficulty b (easy −1, medium 0,
  hard +1, plus a seeded jitter of 0.3).
- The course starts Monday 2026-09-07; module m is week m. A student works on that week's
  problems on a random evening.
- Attempt k succeeds with probability `sigmoid(θ − b + 0.4·(k−1))` (students improve when
  they retry). Success draws correct code, failure wrong code. A student stops at the first
  passing submission or after their persona's maximum attempts (3 / 4 / 5).
- Each submit carries a synthetic editor summary with Step 0's fields, checked with the API's
  own `EditorStats`. The next submit happens exactly `since_open_ms` later, so the times and
  the summaries agree.

| Persona | Students | Behaviour |
|---|---|---|
| strong / average / struggling | 14 / 20 / 12 | honest |
| quitter | 6 | honest, average skill, stops after module 3–5 |
| copier | 4 | on ~60% of problems pastes an **earlier, passing, honest** submission of another student: exact, renamed, or renamed + reformatted (no comments) |
| AI user | 4 | on ~60% of problems pastes a 7B answer (30% renamed), up to 2 pastes |

Names are `sim-001` … `sim-060` in a shuffled order: a name never tells the persona.

**The hard cases (Step 2a).** Before building detectors we measured the first class: *every*
cheating row had one big paste and *no* honest row did, so a paste detector would have scored
100%, a number made by the simulator, not earned by the detector. Two real-world cases were
missing, and are now in:
- **Honest IDE pasters:** ~10% of honest students (a trait) write most problems in their own
  editor and paste the whole program in, sometimes touching it up. Honest, but it looks like a
  paste.
- **Retyping cheaters:** 30% of cheating submissions are typed in by hand: no paste at all,
  but fast (60-120 ms per character) with little thinking time.
Every label says how the code got in (`entry`: `typed`, `ide_paste`, `pasted`, `retyped`),
so a detector's hits and misses can be split by case.

### 1.2 Where the code comes from (no model is called)
| Pool | Contents |
|---|---|
| correct | `solution.py` + the 1.5B's accepted Week 2 answers + the accepted Week 4 tutor-eval answers (the 1.5B fixing a buggy file; 543 distinct programs) |
| wrong | the bank's buggy files + the 1.5B's other Week 2 and tutor-eval answers |
| ai (pasted by AI users) | the 7B's Week 2 answers with seeds 5–9 |
| reference (Step 2 only) | the 7B's answers with seeds 0–4; **never submitted** in the simulation, so the AI detector is never tested on the exact text it knows |

The bank's own files lose their `# comments` (`tutor.guardrail.without_comments`): they are
teacher notes like `# bug: this is the Fahrenheit-to-Celsius formula`, which no student
writes and which would give a detector a clue no real class has. Model answers keep their
comments (models really write them). 70% of honest code gets the student's **own variable
names** (`sim/transforms.py`), so honest code on tiny problems is similar *by nature*, as in
real classes: the copy detector must cope with honest look-alikes. Each pile keeps every
distinct program once, so a program a model wrote ten times isn't ten times as likely.

Why the tutor-eval answers were added (Step 2a): with only the Week 2 answers, 2,895 of
2,902 honest rows had a "canonical twin" (another student's code that is the same once names
are ignored); with them, 2,606 of 2,805 honest typed rows do. Still most: on tiny problems
honest students converge, so similarity alone can't prove copying, and Step 2b must combine
evidence. Only answers graded on the bank's current problem versions are used.

### 1.3 The disguises (`sim/transforms.py`)
- **Rename:** every variable and parameter the code defines gets a fresh student-like name,
  at the exact positions Python's parser reports (formatting and comments stay). Left alone:
  builtins, the graded function's name, other function/class names, imports, `global` /
  `nonlocal` names, exception names, and any name also used as a keyword argument. The grader
  calls the function by position (`function(*args)`), so renamed parameters are safe.
- **Reformat:** `ast.unparse` (normalized spacing and quotes, comments gone).
- A test grades all 33 solutions renamed and renamed + reformatted: 66 of 66 accepted. The
  renamer worked on 659 of the 660 Week 2 answers (the other one doesn't parse; such code is
  left as it is).

### 1.4 The file
`uv run python scripts/sim_cohort.py generate` → `lab/sim/cohort-s0.jsonl` (one row per
submission: key, student, problem, attempt, time, code, editor summary, **label**) +
`cohort-s0.meta.json` (config, every student's persona / true θ / last module, every problem's
true b, input hashes, git commit). The rows file is **byte-identical** on every run (one
`random.Random(seed)`, no clock). Seed 0 (2026-10-06): 3,046 submissions in 3.5 s, 144 of them
cheating (4.7%: 73 copies, 71 AI pastes); intended pass share strong 86%, average 60%,
struggling 37%.

### 1.5 Its own database, graded by the real workers (Step 1b)
```bash
make sim          # = the four steps below (~12.5 min), or one at a time:
make sim-db       # DELETE and re-create codetutor_sim: migrations + problem sync
make sim-load     # queue the 3,046 submissions at their simulated times
make sim-grade    # 4 workers (`worker.py --drain`, Docker) share its queue, then exit
make sim-summary  # grades vs labels
```
- **The same door as a real submit:** `load_rows` calls `enqueue_submission` (problem and
  version checks, code checks) with one extra keyword, `created_at` (the simulated time). Users
  get their first submission's time as `created_at`. Loading into a database that already
  has submissions is refused (it would double the class).
- **Labels stay out:** only user, problem, code, time and editor summary go in. A test dumps
  every submissions and users row as text and checks that no label field name and no source
  reference appears. Labels join back by (student name, problem, time), unique by
  construction (`graded_rows`).
- **Safety:** every database command refuses a database whose name lacks "sim"; the drop
  itself goes through `recreate_database(..., must_contain="sim")`.
- **Measured (2026-10-06, mains power):** 3,046 jobs in 12 min 8 s with 4 workers (776 / 775
  / 765 / 730 each; 0 retried, 0 failed, 0 lost). Results: accepted 1,816, wrong_answer 952,
  runtime_error 201, timeout 49, compile_error 28. **The grade matched the label's "intended
  pass" for 3,046 of 3,046 rows**: every disguised copy and every renamed honest answer
  behaved like its source. Accepted share: strong 86.2%, AI user 82.9%, quitter 72.5%,
  copier 67.4%, average 60.2%, struggling 37.4%.
- `finished_at` is the real grading time (October); `created_at` is simulated (September).
  Steps 2-3 use `created_at`.

### 1.6 What the simulation can and cannot show
- The simulator decides how cheaters behave, so Step 2 measures "how well we catch **our**
  cheaters". The hard cases are in on purpose (honest look-alikes, disguised copies, honest
  small pastes, AI answers the detector has never seen), but real cheaters can be smarter.
- Step 3's Rasch fit is checked on data a Rasch-like rule made: it tests our fitting code, not
  whether real students follow Rasch.
- The editor numbers are rough shapes (typing speed, thinking time), not measured behaviour.
- "Honest" code partly comes from a 1.5B model: real beginners write messier code.

## 2. The integrity checks (Step 2b)

A **batch job** (`make integrity`, or `scripts/integrity.py run --seed N | --dev`) reads every
submission of one database, runs four signals and replaces the whole `integrity_flags` table
in one transaction. It runs outside the worker (decided 2026-10-06): copy checks compare a
submission with *everyone's* earlier code, and a teacher looks at flags days later anyway.
The detectors see only what the database has (`SubmissionInfo`: student, problem, time, code,
editor summary, grade), never the simulation's labels; a test checks their imports.

### 2.1 The four signals (`integrity/signals.py`)
| Signal | Group | Value | Fires when (version 1, §2.4) |
|---|---|---|---|
| `paste` | how the code got in | largest paste ÷ code length | ≥ 0.9 |
| `fast_typing` | how the code got in | typed characters per active second | ≥ 5, and ≥ 80% of the code was typed, and no big paste |
| `same_as_student` | what the code is | similarity to the closest **earlier** submission of **another** student, same problem | ≥ 1.0 |
| `same_as_ai` | what the code is | similarity to the closest known AI answer | ≥ 1.0 |

- A submission **needs review** when it has a signal from each group. That is computed when
  the flags are read, not stored: the single signals stay visible as evidence.
- **Only the later student is flagged.** The earlier one may be the person copied from; a
  student's own earlier code is never a match.
- **Every flag carries a sentence** for the teacher and its numbers in `details`. The copy
  reason says how many students' earlier code matches ("the more, the likelier an honest
  common solution"); the paste reason says how often this student pastes, failing attempts
  included. That habit is **context only**: it never adds or removes a flag (decided
  2026-10-06), because in the simulation it separates honest IDE pasters from cheaters only
  because the simulator gave them different rates (80% vs 60%).
- **Known AI answers** (`integrity/known_ai.py`): the 7B's Week 2 answers with the reference
  seeds 0–4 (165, five per problem), current problem versions only. Simulated AI users paste
  seeds 5–9, so this signal never sees the exact text it knows.

### 2.2 Rename-proof similarity (`integrity/normalize.py`)
`canonical` parses the code and prints it back without comments, docstrings and type hints,
with every variable, parameter and helper function renamed `v0, v1, …` in order of first
appearance (builtins, imported names and the graded function keep their names). Similarity =
Jaccard overlap of the token 4-grams of two canonical texts. Measured: the renamed +
reformatted disguise of each of the 33 solutions has exactly the solution's canonical form;
none of the 97 buggy files reaches 1.0 against its solution (median 0.63, max 0.96: a
one-character bug is "close", never "the same"). Code that doesn't parse has no form and gets
no content signal.

### 2.3 Each signal alone (Step 2b, provisional thresholds 0.5 / 5 / 1.0, 2026-10-06)
| Signal | seed 0: flagged / precision / recall | seed 1 |
|---|---|---|
| paste | 296 / 0.40 / 0.73 | 217 / 0.51 / 0.66 |
| fast_typing | 42 / 0.88 / 0.23 | 54 / 0.93 / 0.30 |
| same_as_student | 2,328 / 0.05 / 0.79 | 2,269 / 0.06 / 0.81 |
| same_as_ai | 451 / 0.16 / 0.45 | 469 / 0.16 / 0.45 |
| **needs review** | **265 / 0.51 / 0.84** | **223 / 0.64 / 0.86** |

(With version 1's paste 0.9, seed 0 is unchanged and seed 1 has 215 pastes and 221 needing
review; §2.4.)

Each signal alone is weak. `same_as_student` fires on three quarters of the honest class
because honest students on tiny problems write the same programs (§1.2). Combining one entry
and one content signal is better than any single one. Fast typing looks precise only because
the simulator chose the speeds: retypers 60–120 ms per character with little thinking time,
honest students ~120–650 ms by skill plus 20–300 s of thinking (`sim/editor.py`, §1.6). The development database
(96 submissions, mostly `make e2e` users submitting the reference solution through the API):
90 `same_as_student`, 1 `fast_typing`, 0 needing review. The batch job takes ~3.6 s per
simulated class.

### 2.4 Choosing the thresholds on one class, measuring on another (Step 2c)
```bash
make integrity                                # run on both classes + write the report
uv run python scripts/integrity.py tune --seed 0   # the search alone (top 10, ~7 s)
uv run python scripts/integrity.py report          # lab/integrity/reports/integrity.md
```
- **The search** (`integrity/evaluate.py`): paste share {0.3, 0.5, 0.7, 0.9} × typing speed
  {3, 4, 5, 6, 7} chars/s × similarity {0.8, 0.9, 1.0} = 60 settings, **on seed 0 only**,
  scored by **F0.5** of "needs review": (1 + β²)·P·R / (β²·P + R) with β = 0.5, so precision
  counts more than recall (a false flag costs an honest student's time and trust). Ties go
  to the stricter setting: fewer flagged, then higher thresholds.
- **Fast without a second detector:** a content flag's value is its best similarity, so the
  flags for a higher similarity threshold are exactly the ones whose value reaches it.
  `FastFlags` compares the code once (at 0.8) and filters; a test checks it against `detect`
  at all 60 settings (and fails when the filter is broken on purpose). 172 s → ~3 s.
- **Result (2026-10-06):** paste 0.5, 0.7 and 0.9 tie at the top (F0.5 0.553: P 0.51, R 0.84,
  265 flagged), because almost every paste is a whole program; the tie rule picks **paste 0.9
  / 5 chars/s / similarity 1.0**, now the `IntegrityConfig` defaults, `INTEGRITY_VERSION =
  "1"`. The top 10 settings are within 0.005 of each other (the worst of the 60: 0.367).
  `report` re-runs the search and refuses to write if the defaults are not the winner.
- **Held-out seed 1** (measured once, after freezing), 95% intervals that resample the 60
  **students** 2,000 times, not the rows (one student's rows are not independent):

| Signal | seed 1 flagged | Precision [95%] | Recall [95%] |
|---|---|---|---|
| **needs review** | 221 | **0.64 [0.32, 0.99]** | **0.86 [0.74, 0.97]** |
| paste alone | 215 | 0.51 [0.21, 1.00] | 0.66 [0.57, 0.74] |
| fast_typing alone | 54 | 0.93 [0.79, 1.00] | 0.30 [0.25, 0.36] |
| same_as_student alone | 2,269 | 0.06 [0.02, 0.10] | 0.81 [0.67, 0.96] |
| same_as_ai alone | 469 | 0.16 [0.06, 0.27] | 0.45 [0.28, 0.61] |

- **What it means:**
  - Per student, all 8 cheating students have at least one submission to review in both
    classes. 8 (seed 0) and 5 (seed 1) of the 52 honest students have at least one false flag.
  - 76 of seed 1's 79 false flags are honest IDE pastes: a whole program pasted from the
    student's own editor whose structure other students also wrote. That is why the
    precision interval is so wide: it depends on how many of those few students a resample
    draws.
  - Thresholds can't fix this. Only other evidence could, for example a paste habit that
    includes failing work. We kept that as context only (decided 2026-10-06), because in the
    simulation it would work only through the rates we chose.
  - Copies are caught more often (seed 1: 79 of 80) than AI pastes (63 of 86). `same_as_ai`
    knows only 5 answers per problem, and a model can write other versions.
- The limits in §1.6 apply. The report's own limits section says them again.

## 3. Difficulty and skill (Step 3)

```bash
make skill                                  # lab/skill/reports/skill.md (both classes, ~25 s)
uv run python scripts/skill.py show --dev   # hardest problems + lowest skills of the dev database
```
Estimated from **first attempts only**: one response per (student, problem), "accepted or
not" (`skill/load.py`). Later tries are practice, so they would blur "skill minus difficulty".

- **Pass rates** (the baseline): difficulty = log(failed / solved) with half an answer added
  to each side (so 0 and 100% stay finite); skill = share of the student's problems solved.
- **Rasch** (`skill/rasch.py`, pure Python): P(solve) = sigmoid(skill − difficulty), one
  number per student and per problem, fitted together by alternating Newton steps. A
  Gaussian prior (spread 1.0, fixed by convention, never tuned) keeps a student who solved
  everything finite; difficulties are centred to mean 0, because the scale has no natural zero.
- **Scoring** (`skill/evaluate.py`): the simulation's true skills and difficulties, Pearson
  and Spearman correlation, RMSE after centring, 95% intervals that resample the problems
  (or the students). Nothing is tuned on either class, so both are reported the same way.

**Result (2026-10-07, detector version 1):** difficulty r 0.84 (seed 0) and 0.89 (seed 1),
skill r 0.91 and 0.86; pass rates 0.82 / 0.88 and 0.90 / 0.85. Without the first tries the
integrity checks flag, skill r rises to 0.93 / 0.93; difficulty barely moves. With 30% of the
answers missing, Rasch stays ahead of the pass rates in 8 of 8 comparisons, but only by 0.01 to
0.04. So on this data **Rasch is only slightly better than counting**, as expected when almost
every student tried almost every problem; it earns more when answers are missing in a biased
way. It also gives problems an estimated difficulty to compare with the declared level (§4 of
the report): for example `remove_duplicates`, declared easy, is clearly easier than the
other easy problems.

Limits: the simulator follows Rasch, so this tests our fitting code, not whether real students
do (§1.6); skill numbers are for a teacher to see who needs help, never a grade. No table
stores the estimates. Since Week 8 the instructor routes compute skill and difficulty per request
and show them (`src/codetutor/api/instructor.py`, [api.md](api.md) §8).
