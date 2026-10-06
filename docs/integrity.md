# Integrity checks and skill estimates (Week 5)

Week 5 adds **signals for a human**: which submissions look copied, pasted or AI-written, and
how hard each problem and how skilled each student is. Flags never punish anyone by themselves
(brief, principle 6): they come with reasons, and a teacher decides.

Status: **Step 0** (editor summary per submit, [api.md](api.md) §1) and **Step 1** (the
simulated class, generated, loaded and graded, below) are done. Next: Step 2 (integrity
checks), Step 3 (difficulty and skill), Step 4 (wrap-up).

Code: `src/codetutor/sim/` (`personas.py`, `pools.py`, `transforms.py`, `editor.py`,
`cohort.py`, `load.py`), `scripts/sim_cohort.py`, `src/codetutor/db/admin.py`. Tests:
`tests/test_sim.py`, `tests/test_sim_db.py`.

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

### 1.2 Where the code comes from (no model is called)
| Pool | Contents |
|---|---|
| correct | `solution.py` + the 1.5B's accepted Week 2 answers |
| wrong | the bank's buggy files + the 1.5B's other Week 2 answers |
| ai (pasted by AI users) | the 7B's Week 2 answers with seeds 5–9 |
| reference (Step 2 only) | the 7B's answers with seeds 0–4; **never submitted** in the simulation, so the AI detector is never tested on the exact text it knows |

The bank's own files lose their `# comments` (`tutor.guardrail.without_comments`): they are
teacher notes like `# bug: this is the Fahrenheit-to-Celsius formula`, which no student
writes and which would give a detector a clue no real class has. Model answers keep their
comments (models really write them). 70% of honest code gets the student's **own variable
names** (`sim/transforms.py`), so honest code on tiny problems is similar *by nature*, as in
real classes: the copy detector must cope with honest look-alikes.

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
