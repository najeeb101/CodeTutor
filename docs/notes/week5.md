# Week 5: simulated students, integrity checks, difficulty and skill

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
- Editor summary (Step 0): the browser sends one summary per submit (typed characters, pasted
  characters, largest paste, active time, edits, restored draft). Stored in
  submissions.editor_stats. No keystroke log.
- A simulated class (sim/): 60 students with personas and true skills, true problem
  difficulties, cheaters (copiers, AI users), honest students who paste from their own editor,
  cheaters who retype. Code comes from existing files and answers plus disguises (rename,
  reformat); no model call. Two classes: seed 0 (tune) and seed 1 (held out). Each is loaded
  through the real submit door and graded by 4 Docker workers; grade = label for all rows.
- Four integrity signals (integrity/signals.py): paste, fast_typing, same_as_student,
  same_as_ai. "Needs review" = one entry signal + one content signal. A batch job writes
  integrity_flags (one row per signal, with a sentence for the teacher).
- Rename-proof comparison (integrity/normalize.py): parse, drop comments/docstrings/hints,
  rename variables v0, v1..., then Jaccard overlap of token 4-grams.
- Threshold search (integrity/evaluate.py): 60 settings, F0.5, chosen on seed 0, frozen as
  version 1, measured once on seed 1, intervals that resample students.
- Difficulty and skill (skill/): first attempts only; pass-rate baselines and a Rasch fit in
  pure Python with a prior; scored against the true values.
-->

## 2. Key design decisions and trade-offs

<!--
Raw facts (pick 3-5, say what you gave up):
- Simulate instead of waiting for real students: we get labels (precision, recall) but the
  simulator chooses how cheaters behave. Result = "how well we catch OUR cheaters".
- Make the class harder first (honest IDE pasters, retyping cheaters, shared honest code):
  the first class gave a 100% paste detector, made by the simulator.
- Choose thresholds on one class, report on another: costs one more graded class (13 min).
- Combine evidence ("needs review" needs an entry and a content signal): each signal alone has
  honest explanations (same_as_student alone: precision 0.06).
- Flag only the later of two matching submissions: the earlier student may be the one copied.
- The paste habit of a student is context in the reason text, never a flag input (it would work
  only through rates the simulator chose).
- Batch job, not in the worker: copy checks compare with everyone's earlier code.
- First attempt only for skill; Rasch with a fixed prior (not tuned); no numpy.
- Flags never punish; no route shows them yet (Week 8).
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
Raw facts (pick 1-2 and tell them as a story):
- A perfect score as a bug report: the first simulated class made paste detection 100% precise
  and 100% recall, because every cheater pasted and no honest student did. We added the hard
  cases, and the same rule fell to precision 0.40 / recall 0.73 on seed 0 (0.51 / 0.66 on seed 1).
- Monaco applies a new `value` prop with executeEdits, not setValue: a restored draft or Reset
  looked like "typed a whole draft in 1 second". Fix: tell the tracker to expect the replace.
- The bank's buggy files carried teacher comments (`# bug: ...`) into "student" code: an unfair
  clue for a detector. Pools now strip them.
- Almost every honest row has a "canonical twin" (same code once names are ignored): on tiny
  problems honest students converge, so similarity alone proves nothing (precision 0.06).
- The threshold grid was flat: the top 10 of 60 settings are within 0.005 F0.5; three tie.
  The tie rule picked paste 0.9. The limit is the evidence, not the thresholds.
- My first draft said Rasch "should hold up better" with missing data; measured: 0.01-0.04.
-->

## 4. Numbers

Measured by Claude on 2026-10-06 and 2026-10-07. Najeeb: check them before an interview.

| What | Number |
|---|---|
| Simulated classes | seed 0: 3,145 submissions, 161 cheating; seed 1: 3,076, 166 cheating; 60 students each, 8 cheat |
| Grading the class | 4 Docker workers, ~10-13 min per class; grade = label for 3,145 of 3,145 and 3,076 of 3,076 |
| Each signal alone, seed 1: precision / recall | paste 0.51 / 0.66; fast typing 0.93 / 0.30; same as student 0.06 / 0.81; same as AI 0.16 / 0.45 |
| Needs review, seed 0 (tuning): precision / recall | 0.51 / 0.84 (265 flagged) |
| Needs review, seed 1 (held out) [95% over students] | precision 0.64 [0.32, 0.99]; recall 0.86 [0.74, 0.97] (221 flagged) |
| Per student, seed 1 | 8 of 8 cheating students flagged; 5 of 52 honest students with a false flag |
| False flags, seed 1 | 76 of 79 are honest IDE pastes |
| Caught, seed 1 | copies 79 of 80; AI pastes 63 of 86 |
| Threshold grid | 60 settings; best F0.5 0.553, worst 0.367; top 10 within 0.005 |
| Search time | 172 s (compare 60 times) → 3.3 s (compare once) |
| Difficulty r with the truth (Rasch / counting), seed 0 / 1 | 0.84 / 0.82 and 0.89 / 0.88 |
| Skill r with the truth (Rasch / counting), seed 0 / 1 | 0.91 / 0.90 and 0.86 / 0.85; 0.93 / 0.93 without flagged first tries |
| Rasch gain with 30% answers missing | ahead in 8 of 8 comparisons, by 0.01 to 0.04 |

| Project | Number |
|---|---|
| Database | 8 tables, 8 migrations (2 new: editor_stats column, integrity_flags) |
| Packages | 0 new Python packages, 0 new npm packages |
| pytest | 716 tests by default (+1 slow, +33 Docker-only); 112 of them new this week (604 at the end of Week 4) |
| Code this week (non-blank lines) | sim/ 794, integrity/ 991, skill/ 527; tests for them 1,079 |
| Time | 2 days (2026-10-06, 10-07), 20 commits incl. this wrap-up and its status update |

## 5. How I'd explain this in 60 seconds

<!--
No facts from Claude here, on purpose. Write it yourself, about 150 words, then say it out loud
without reading. Tip: start with "how do you measure a cheating detector without real cheaters?",
then the held-out class, then one honest sentence about what the numbers cannot say.
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
Raw facts (pick 2-3 and say why they matter):
- Real data with consent: tune on real classes; the simulator chose our cheaters' behaviour.
- New evidence for honest IDE pasters (the main false flag): paste habit with failing work,
  tests run before submit, time between runs.
- Store estimates and flags in tables and build the Week 8 instructor screens.
- Rasch with partial credit or Elo for live updates; more useful when answers are missing.
- Banned-call checks (AST) for problems like merge_sorted.
- At scale: the batch job compares every submission with all earlier code; use hashing
  (locality-sensitive) or an index of fingerprints instead of pairwise comparison.
-->

## 7. Five likely interview questions (and my answers)

<!--
Raw questions (write your own answers, short):
1. How do you evaluate a cheating detector when you have no labelled cheaters?
2. Why choose thresholds on one class and report on another?
3. Why resample students instead of submissions for the interval?
4. A student's code matches another student's. Why is that not enough to flag them?
5. Rasch vs counting: when does Rasch help, and what did you actually measure?
-->
