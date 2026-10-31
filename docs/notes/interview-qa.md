# Interview practice: likely questions about CodeTutor

Drafted by Claude from CLAUDE.md, the generated reports in `lab/*/reports/` and
`interview-notes.md`. Practice saying each answer in your own words. Before an interview,
re-check every number against its report (the file is named in brackets).

## The project

**Q1. Describe CodeTutor in 30 seconds.**
A practice site for first-year Python. Students submit code and get instant grading from
hidden tests. An AI tutor gives hints, not answers. A teacher dashboard shows integrity flags
and skill estimates. The same grader also scores language models and is the reward function
when I train a small model with GRPO.

**Q2. Why one grader for everything?**
If students, evals and training each had their own grader, their numbers could not be
compared, and a bug in one would hide in the others. `grade(problem, code)` is the only
path. Hidden tests protect the reward: a model cannot learn to pass tests it never sees.

**Q3. What is the hardest design decision you made?**
Postgres as the job queue instead of Redis. The submission row is the job, so there is no
"saved the row but lost the job" problem. Workers claim with `FOR UPDATE SKIP LOCKED` and a
lease, and an `attempts` counter acts as a fencing token so a late save after a lost lease
writes nothing. Cost: I wrote about 100 lines of claim and retry logic myself.

## Grading and evals

**Q4. How do you keep student code from hurting the machine?**
Layers. The subprocess sandbox uses resource limits but is NOT secure. The Docker sandbox
has no network, a read-only filesystem, a non-root user and a pids limit. Containers share
the host kernel, so at real scale I would use gVisor or Firecracker. The runner never
receives expected outputs: the parent compares.

**Q5. What is pass@k, and why not just average?**
The chance that at least one of k samples is correct. I use the unbiased estimator from n
samples with c correct, not "take the first k". [`lab/evals/reports/week2.md`]

**Q6. What did your eval show?**
On 33 problems: Qwen2.5-Coder 1.5B pass@1 0.867 [0.779, 0.942]; the 7B (4-bit) 0.945
[0.867, 1.000]. Honest caveat: the 7B is 4-bit and the 1.5B is fp16, so size is not the
only difference. [`week2.md`]

**Q7. How do you know your problems are good?**
Each problem has buggy solutions, and the validator checks that the real solution passes and
every buggy one fails (mutation testing). Some bugs are hidden-only: they pass all visible
tests, so only the hidden tests catch them.

## The tutor

**Q8. How do you stop the tutor giving the answer?**
Three things. The model never sees `solution.py`. Every hint passes a guardrail that
blocks code blocks, code statements and solution lines. If a hint is blocked, the model gets one retry; if that fails
too, a reference hint written by a human is shown. Limits: it compares text, it does not understand
meaning, and I wrote down three known misses.

**Q9. Does the tutor help?**
Not shown. With a 1.5B model as the simulated student, tutor level 1 gives +0.04
[-0.02, +0.11] over no hint: the interval includes 0. Hints also made some situations worse.
[`lab/tutor/reports/tutor_eval.md`]

**Q10. Why no Langfuse?**
The `hints` table already stores every attempt as a trace. Langfuse would add a package and
send student code off the machine. It is in `docs/ideas.md`.

## Integrity, skill, early warning

**Q11. How do you evaluate a cheating detector with no real cheaters?**
I built a simulated class with known labels, chose thresholds on seed 0 and report on a
held-out seed 1. My first class made paste detection look 100% perfect, which was a bug in
the simulator, so I added honest pasters and retyping cheaters. Held-out: precision 0.64
[0.32, 0.99], recall 0.86 [0.74, 0.97]. The intervals are wide (8 cheating students).
Flags inform a teacher and never punish.

**Q12. Why Rasch, and did it beat counting?**
It estimates student skill and problem difficulty together, so a hard problem does not
unfairly lower a student. Honest result: only slightly better than counting pass rates. Rasch
skill correlates 0.91 / 0.86 with the true skill (seeds 0 / 1); it was ahead of counting in
8 of 8 missing-data comparisons, but only by 0.01-0.04. [`lab/skill/reports/skill.md`]

**Q13. Does your early-warning model work?**
Held-out AUC 0.94 [0.86, 0.99], but a one-line rule "low first-try share" scores 0.92. The
difference is inside the interval, so it is not shown to beat the simple rule. I keep the
model because it is served from a versioned file and `make early` refuses to run if the
file drifts. [`lab/early/reports/early_warning.md`]

## Training

**Q14. What did GRPO do?**
I trained the 0.5B model with LoRA, using the grader's share of passed tests (hidden
included) as the reward. Four folds, each holding out two whole modules, so every problem is
held out once. Pooled held-out pass@1 0.652 to 0.675, +0.02 [0.00, +0.04], inside a noise
band of ±0.032. Train problems improved more than held-out ones. My conclusion: no proof of
transfer. [`lab/rl/reports/pooled.md`]

**Q15. Why is that a good result to show?**
Because I measured the noise before believing the gain: the untrained model moved
0.636 to 0.667 between two draws. A second seed on fold c agreed with the first
(+0.03 / +0.04). I would rather report "within noise" than a number that does not repeat.

**Q16. Did the model hack the reward?**
I audited the stored answers for literal results and `if`-on-visible-input patterns. 3.1-3.2%
flagged, the untrained model the same as every adapter. Read by hand, almost all were
legitimate category words in `triangle_type` and base cases; one real attempt, which
failed the hidden tests. Limit: it only sees literals and `if` guards, and only eval-time
answers.

## Honesty questions

**Q17. What would you do differently?**
Get real student data early instead of simulating. Use a larger model or more problems so
folds are not 8 problems wide. Add real authentication before anyone but me uses it
(the dev login is spoofable).

**Q18. What is not done?**
The browser checks of the dashboard never ran (WSL could not start Chrome). The API is
dev-grade: shared instructor token, spoofable login. All students are simulated.

## Numbers to re-check before an interview

Re-read, do not trust this file: `week2.md` Headline, `pooled.md` section 2,
`early_warning.md` seed 1 table, `tutor_eval.md` `tutor-1` row, `integrity.md` held-out
section.
