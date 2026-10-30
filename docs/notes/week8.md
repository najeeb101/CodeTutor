# Week 8: the teacher's view: instructor API, dashboard, early warning

Written by Najeeb, reviewed by Claude.

<!--
HOW TO USE THIS FILE (delete this box when you are done)
- Each section has a grey box like this one with raw facts from Claude. They are notes, not text.
  Write your own sentences under the box. Use your own words: in an interview you can only
  say what you really understand.
- You don't have to use every fact. Choosing what matters is part of the exercise.
- When you are done, say "review". Claude checks every claim and number, marks each section
  ✅ / ⚠️ / ❌, and does not rewrite your text. Then these boxes are removed.
-->

## 1. What we built

<!--
Raw facts (pick 3-5 bullets, say what each part DOES, not only its name):
- Instructor API (Step 1, api/instructor.py): 4 read-only routes under /api/instructor/
  (overview, students, students/{id}, problems) behind a shared dev token in the header
  X-Instructor-Token (env INSTRUCTOR_TOKEN, 16+ characters). Unset or short = 503, none = 401,
  wrong = 403, constant-time compare. Skill and difficulty (Rasch on first tries) and review
  counts are computed per request; nothing stored; no student code returned. No schema change,
  no new package. `make api-sim` runs the API on the simulated class's database.
- Dashboard (Step 2, web/app/instructor/): token box (kept in sessionStorage), overview cards,
  sortable students table, problems table, one student page with every problem tried and every
  flag with its reason sentence. Client components, because the token lives only in the browser.
  Text on screen: "A mark is a reason to look at the work, never proof."
- Early-warning model (Step 3a, early/): logistic regression in pure Python (Newton, standardised
  inputs, fixed L2 1.0). Question: at the end of week 3, who will solve less than 40% of the
  problems they first try later, on the first try? Inputs from submissions up to the cutoff only.
  Fitted on seed 0, scored on seed 1. Two simple rules scored beside it.
- Risk on the dashboard (Step 3b): the API returns `risk` (0 to 1 or null) and `risk_available`;
  the model is a committed file (early/model_week3.json, version "1") loaded by early/served.py,
  not fitted per request. Sortable Risk column and a Risk card on the student page, with an
  honest caption. `make early` refuses to run if the served file differs from a fresh fit.
-->

## 2. Key design decisions and trade-offs

<!--
Raw facts (pick 3-5, say what you gave up):
- Dev token, not real accounts: one shared secret, no limit on wrong guesses. Fine on 127.0.0.1;
  must be replaced before hosting. Gave up: per-teacher accounts.
- Compute skill, difficulty and risk on every request, store nothing: a class of tens of students
  takes 0.2-0.3 s per call; no stale numbers, no new tables. Gave up: speed for big classes.
- The label for early warning comes from outcomes (submissions), never from the simulator's
  persona labels (a test checks the imports). Cutoff (week 3) and the 40% were fixed before any
  result.
- "Will quit" was dropped as a question: only 6 students quit, and they look average until the
  week they stop. We did not add a warning sign to the simulator to find it later.
- Serve a committed model file instead of fitting per request: the report and the dashboard use
  the same weights. Gave up: the model does not update by itself.
- Students stay ordered by review count, not by risk; Risk is a sortable column. Risk never
  decides anything alone.
- The 3-minute demo script is a file (docs/demo-script.md), so the numbers come from the
  reports, not from memory.
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
Raw facts (pick 1-2 and tell them as a story):
- The model did not clearly beat a one-line rule. Held-out AUC 0.94 [0.86, 0.99] vs 0.92
  [0.84, 0.98] for "low first-try share"; top 10: 8 of 10 at risk for both. At the end of week 2
  the model was worse (AUC 0.81 vs 0.94). The dashboard text says so.
- Success in the simulator is drawn from skill, so past success predicts future success by
  construction. A good AUC here is partly the simulator's doing.
- Port 8000 is held by another Windows service that answers 404, so `make api` can fail to
  bind; the teacher API runs on API_PORT=8010 and the web UI needs CODETUTOR_API_URL for it.
- The web UI talks to one API only, so the demo needs two web servers (student on 3100,
  teacher on 3101).
- Rank-formula check: AUC from the rank formula gives the same 0.9214 as the pairwise count;
  one student's features were recomputed by hand from raw rows.
-->

## 4. Numbers

Checked against `lab/early/reports/early_warning.md`, `lab/rl/reports/pooled.md` and
`lab/evals/reports/week2.md` on 2026-10-30. Najeeb: check them before an interview.

| What | Number |
|---|---|
| Early warning classes | seed 0: 60 students, 3,145 submissions, 59 scored, 15 at risk (25%); seed 1: 60 students, 3,076 submissions, 59 scored, 14 at risk (24%) |
| Held-out AUC, end of week 3 [95% over students] | model 0.94 [0.86, 0.99]; low first-try share 0.92 [0.84, 0.98]; days since last submission 0.60 [0.43, 0.77]; random 0.50 |
| Top 10 students, seed 1 | model precision 0.80, recall 0.57; first-try rule 0.80 / 0.57 (recall capped at 0.71: 14 at risk) |
| Other cutoffs, seed 1 (model AUC vs first-try AUC) | week 1: 0.87 vs 0.86; week 2: 0.81 vs 0.94; week 4: 0.95 vs 0.95 |
| Instructor routes on the simulated class | 4 routes; 60 students, 3,145 submissions, 265 to review (same as Week 5); 0.2-0.3 s per call |
| For the demo: Week 2 | 1.5B pass@1 0.867 [0.779, 0.942]; 7B (4-bit) 0.945 [0.867, 1.000] |
| For the demo: GRPO pooled over 33 problems | 0.652 -> 0.675, +0.02 [0.00, +0.04], band ±0.032, 15 better / 8 worse / 10 same: within noise |

| Project | Number |
|---|---|
| Commits | 4 feature commits: ccac093 (Step 1), 6592ec5 (Step 2), c8025b9 (Step 3a), b8ec42c (Step 3b) |
| Code this week (files changed) | Step 1: 9; Step 2: 19 (web); Step 3a: 14; Step 3b: 20 |
| Database | no schema change this week |
| Packages | 0 new Python packages, 0 new npm packages (check at review) |
| pytest | 790 after Step 1 (CLAUDE.md); re-count at review |
| Time | <!-- fill in the dates when you review --> |

## 5. How I'd explain this in 60 seconds

<!--
No facts from Claude here, on purpose. Write it yourself, about 150 words, then say it out loud
without reading. Tip: start with "what does a teacher need to see?", then the rule that every
mark is a reason to look and never proof, then one honest sentence about what the early-warning
numbers cannot say.
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
Raw facts (pick 2-3 and say why they matter):
- Real accounts and roles for teachers (the dev token is shared and has no limit on guesses).
- Real classes with consent: real labels for "who needed help", then refit the model and store
  its version.
- A fairness check: does the risk score flag one group of students more often?
- Wording on screen: "check in", never "failing".
- Store estimates and flags with a version, so a teacher can see how a number changed over time.
- At scale: computing skill and risk per request will not hold for thousands of students; move
  it to a batch job with stored results.
-->

## 7. Five likely interview questions (and my answers)

<!--
Raw questions (write your own answers, short):
1. Your risk model has AUC 0.94. Why should I not be impressed?
2. Why did you compute skill and risk per request instead of storing them?
3. Why does the dashboard say "never proof" next to every flag?
4. What would you need before showing this to a real teacher?
5. The model is worse than a one-line rule at the end of week 2. What do you do with that?
-->
