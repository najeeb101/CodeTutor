# Early warning (Week 8 Step 3a)

A light model that ranks students by the chance they will struggle later. Code:
`src/codetutor/early/`; command: `make early`; report: `lab/early/reports/early_warning.md`.

## 1. The question
At the end of week 3, which students will solve fewer than 40% of the problems they first try
*after* week 3, on the first try? Cutoff and 40% were fixed before any result. The label comes
from the submissions table (outcomes). It never reads the simulator's persona labels (a test
checks the imports).

Why not "will quit"? Measured on both simulated classes: only the 6 quitters fail to finish,
and they behave like average students until the week they stop. No model can see that coming,
and we did not add a warning sign to the simulator to find it later.

## 2. Method
- Inputs (only submissions up to the cutoff): first-try share, problems tried, tries per solved
  problem, activity trend, days since the last submission, Rasch skill on the first tries so far.
- `features.py` cuts the list first (`prefix`), so later rows cannot leak in; a test changes all
  later rows and checks nothing moves, and fails if the cut is removed (checked by hand).
- `logistic.py`: Newton's method, standardised inputs, fixed L2 = 1.0 (keeps weights finite
  when classes separate). No library.
- Fit on seed 0, score seed 1 (the Week 5 rule). Baselines: low first-try share; days since the
  last submission; random order.
- Metrics: AUC with a bootstrap over students; precision and recall for the top 10.

## 3. Result (end of week 3, held-out seed 1)
Model AUC 0.94 [0.86, 0.99]; first-try rule 0.92 [0.84, 0.98]; inactivity rule 0.60; chance 0.50.
Top 10: 8 of 10 at risk for both the model and the first-try rule. At other cutoffs the model is
sometimes worse than the simple rule (week 2: 0.81 vs 0.94). **The model is not shown to beat a
one-line rule.** Checked a second way: the rank formula for AUC gives the same 0.9214 as the
pairwise count; one student's features were recomputed by hand from raw rows.

## 4. Limits
Simulated classes (success is drawn from skill, so past success predicts future success by
construction); about 14 at-risk students; wide intervals; six inputs; the simulator's students
never react to a warning.

## 5. Before this touches a real class
Real labels (who actually needed help) and consent; the model fitted on real data with its
version stored; a fairness check (does it flag a group more often?); wording on screen that says
"check in", never "failing". Showing the score on the dashboard is idea 3b in `docs/ideas.md`.
