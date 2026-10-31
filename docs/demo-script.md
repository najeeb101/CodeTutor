# Demo script: 3 minutes for a Scale AI interviewer

You record this yourself (screen + voice). Say the quoted lines in your own words.
Every number below comes from a generated report in `lab/*/reports/`. If you change a
sentence, keep the numbers as they are.

## 1. Before you record

Run these in order. Each long-running command needs its own terminal. Keep the terminals
open while you record.

1. Start **Docker Desktop** (Windows). Wait until `docker ps` works in WSL.
2. Free memory if the laptop is low: stop containers you do not need
   (`docker ps`, then `docker stop <name>`). The Supabase containers on this laptop are not needed.
   The 7B model needs about 5 GB of the 8 GB GPU. Close Opera and the Epic launcher too.
3. Plug in the laptop (battery makes everything slower).
4. Terminal 1: `make db-up`
5. Terminal 2, **warm the tutor first**: `make tutor`.
   It loads the 7B model and the embedder at start. Wait for the log line
   `... and ... loaded in N s`. The first load can take ~110 s (measured after a reboot).
   Then ask one hint yourself (step 9) so the model is certainly warm. It stays loaded
   (the worker refreshes it every 4 minutes).
6. Terminal 3: `make worker` (grades in Docker).
7. Terminal 4: `make api` (student API, port 8000).
8. Terminal 5: `make web` (student web UI, http://localhost:3100).
9. Test run, off camera: log in as `demo`, open fizzbuzz, submit the buggy file, ask for a
   hint. Then use a **new name** (for example `demo2`) for the real recording, so the
   hint rate limit (1 waiting, 10 per 10 min) and old drafts do not show.
10. Teacher part (needs the simulated class: `make sim`, ~13 min, then `make integrity`;
    both only once, not before every recording; seed 0 is the default class):
    - Terminal 6: `INSTRUCTOR_TOKEN=$(openssl rand -hex 16) API_PORT=8010 make api-sim`
      (the token is 16+ characters; write it down, you type it in the browser).
    - Terminal 7: `WEB_PORT=3101 CODETUTOR_API_URL=http://127.0.0.1:8010 make web`
      then open http://localhost:3101/instructor.
    - Why a second web server: the web UI talks to one API only. The student UI (3100)
      uses the normal API on 8000. The teacher UI (3101) uses the API on the simulated class.
    - Port 8000 or 3100 may be taken by other Windows services (CLAUDE.md: 8000 answers 404,
      3000 is taken). If `make api` cannot bind, use `API_PORT=8010` style ports and set
      `CODETUTOR_API_URL` to match. `make api` reads `API_PORT` too (default 8000), so
      `API_PORT=8010 make api` works when 8000 is busy.
11. Open these files in editor tabs, ready to paste/show:
    - `problems/cs1/03_loops/fizzbuzz/buggy/checks_fizz_first.py`
    - `problems/cs1/03_loops/fizzbuzz/solution.py`
    - `lab/evals/reports/week2.md`
    - `lab/rl/reports/pooled.md`
12. Quick check: `make e2e` (needs worker, tutor, api, web running) should print 11/11. If the API runs on
    another port, give the same port to all three: `API_PORT=8010 make api`,
    `CODETUTOR_API_URL=http://127.0.0.1:8010 make web`, `API_PORT=8010 make e2e`.
    Dry run on 2026-10-31 (API on 8010, fresh dev DB after `make db-reset`): 11/11.
    It uses its own `e2e-...` user, so it does not touch your demo user.

Commands checked with `grep` in the Makefile: `db-up`, `tutor`, `worker`, `api`, `web`,
`api-sim` (needs `INSTRUCTOR_TOKEN`; reads `API_PORT`, default 8000), `sim`, `integrity`,
`e2e`. `WEB_PORT` is read by `web/package.json`. `CODETUTOR_API_URL` is read by
`web/lib/config.ts`.

## 2. Storyline (target 3:00)

### 0:00 Pitch (20 s)

- **Do:** show the problem list in the student UI (http://localhost:3100).
- **Say:** "This is CodeTutor, a practice platform for first-year Python. Every problem has
  automatic tests, so the same grader that scores a student also scores language models, and
  it is the reward function when I train a small model with GRPO. I will show the student
  side, the teacher side, and the lab."
- **If it goes wrong:** the list is empty. Run `make db-sync`, reload. Say the pitch over
  the terminal output instead.

### 0:20 Student (55 s)

- **Do:**
  1. Log in as `demo2`. Open fizzbuzz.
  2. Paste `checks_fizz_first.py`. Click Submit.
  3. Show the result: a wrong answer; the hidden tests fail **without details**
     (inputs and expected values are not shown).
  4. In the hint panel, ask a question and click level 1. Wait for the hint.
  5. Paste `solution.py`. Submit. Show "Accepted".
- **Say:**
  - "This buggy version checks 3 before 15. It passes the visible tests, but hidden tests
    catch it, and the student only sees that some hidden tests failed, not which ones."
  - "The AI tutor gives a hint, not the answer. It never sees the solution file, and every
    hint passes a guardrail that blocks code and solution lines."
  - "Now the correct solution. Accepted, 10 of 10."
- **If it goes wrong:**
  - Result stays "waiting": the worker is not running (`make worker`). The UI polls for 2 minutes.
  - Hint takes long: the model was cold. Say "the first hint after a model load can take
    about two minutes; warm hints take a few seconds", and cut the pause when editing.
  - 429 on hints: you hit the rate limit. Use a new user name.
  - Docker error: start Docker Desktop, restart `make worker`.

### 1:15 Teacher dashboard (45 s)

- **Do:** open http://localhost:3101/instructor, type the token.
  1. Overview cards: students, submissions, how many need review.
  2. Students table: the first row (most to review comes first). Click it.
  3. On the student page: show the flags with their reason sentences and the line
     "A mark is a reason to look at the work, never proof."
  4. Show the skill number and the Risk card.
  5. Back on the table, sort by Risk. Read the caption above it.
- **Say:**
  - "This is a simulated class: 60 students, 3,145 submissions, with known cheaters, so I
    can measure the detectors."
  - "Each flag has a plain sentence for the teacher. A flag is a reason to look, never proof.
    Honest students trigger flags too."
  - "Risk is an early-warning score from weeks 1 to 3. It is fitted on a simulated class
    and is not shown to beat simply looking at the first-try share. It is a reason to check
    in, never a verdict."
- **If it goes wrong:**
  - Token box comes back: wrong token, type it again (the API logs show 401/403).
  - 503: `INSTRUCTOR_TOKEN` was not set for `make api-sim`.
  - Empty flags: run `make integrity` first (it writes the flags).
  - Risk empty: it only shows once the class has reached week 3. Say so and move on.

### 2:00 Lab (40 s)

- **Do:**
  1. Open `lab/evals/reports/week2.md`, the Headline table.
  2. Open `lab/rl/reports/pooled.md`, section 2, the "all folds pooled" row.
- **Say:**
  - "The same grader runs the eval harness. On 33 problems, Qwen2.5-Coder 1.5B has pass@1
    0.867 and the 7B (4-bit) 0.945. Pass@5 is 0.983 and 0.978."
  - "Then I trained the 0.5B model with GRPO, using the grader's share of passed tests,
    hidden tests included, as the reward. Each problem is held out once, in four folds.
    Pooled over all 33 problems, pass@1 goes from 0.652 to 0.675, a change of +0.02 with
    interval [0.00, +0.04]. The noise band is plus or minus 0.032. My own rule says: within
    noise. I do not claim the training helps on unseen problems."
- **If it goes wrong:** a file does not open. Read the numbers from the terminal:
  `grep -n "all folds pooled" lab/rl/reports/pooled.md`.

### 2:40 Close (20 s)

- **Do:** stay on `pooled.md` or show the README.
- **Say:**
  - "What is solid: one grader for everything, hidden tests that protect the reward, and
    reports that regenerate byte-identical."
  - "What is not: the students are simulated, nothing is validated on a real class, the tutor
    was not shown to help (plus 0.04, interval from minus 0.02 to plus 0.11), and the GRPO
    result is no proof of transfer. I wrote those limits down on purpose."
- **If it goes wrong:** you run over time. Drop the Risk sort; keep the last two sentences.

## 3. Lines not to skip

Say these in some form. They are the honest parts.

1. Flags and risk are "a reason to look, never proof / never a verdict".
2. The class is simulated: "we catch our own cheaters", not real ones.
3. Risk is not shown to beat the first-try share (held-out AUC 0.94 [0.86, 0.99] vs 0.92
   [0.84, 0.98]; intervals overlap).
4. Tutor help: +0.04 [-0.02, +0.11] with a 1.5B model as the student; not shown to help.
5. GRPO: pooled +0.02 [0.00, +0.04], within a noise band of plus or minus 0.032. No proof
   of transfer.
6. Hidden tests are never shown to students, and the tutor never sees the solution.

## 4. Numbers used (and where they come from)

| Number | File |
|---|---|
| 1.5B pass@1 0.867 [0.779, 0.942], pass@5 0.983; 7B (4-bit) 0.945 [0.867, 1.000], pass@5 0.978 | `lab/evals/reports/week2.md` (Headline) |
| Pooled GRPO: 0.652 -> 0.675, +0.02, [0.00, +0.04], band ±0.032, 15 better / 8 worse / 10 same, "within noise" | `lab/rl/reports/pooled.md` section 2 |
| Class: 60 students, seed 0: 3,145 submissions | `lab/early/reports/early_warning.md`, `lab/skill/reports/skill.md` |
| Risk AUC 0.94 [0.86, 0.99] vs first-try 0.92 [0.84, 0.98] (held-out seed 1) | `lab/early/reports/early_warning.md` |
| Tutor +0.04 [-0.02, +0.11] | `lab/tutor/reports/tutor_eval.md` (via CLAUDE.md Status; re-check before you say it) |

Rehearse once with a timer. Cut the Risk sort first if you are over 3:00.
