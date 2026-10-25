# Week 7: is the result real? Noise, pooled draws, a second seed, reward hacking

Written by Najeeb, reviewed by Claude.

<!--
HOW TO USE THIS FILE (delete this box when you are done)
- Each section has a box like this one with raw facts from Claude. They are notes, not text.
  Write your own sentences under the box. Use your own words: in an interview you can only
  say what you really understand.
- You don't have to use every fact. Choosing what matters is part of the exercise.
- When you are done, say "review". Claude checks every claim and number, marks each section
  ✅ / ⚠️ / ❌, and does not rewrite your text. Then these boxes are removed.
-->

## 1. What we built

<!--
- Eval noise (rl/noise.py): the same models re-evaluated with another sampling seed (seed_base); the untrained 0.5B moved 0.636 -> 0.667 with no training.
- Pooled draws (rl/pooled.py): 3 draws x 10 answers = 30 per problem for every model; rule written first: above noise only if the interval excludes 0 AND the change is larger than 1.96 x SD / sqrt(m).
- Second training seed on fold c (rl/pooled.py seeds report): agreement rule written before the run.
- Reward-hacking audit (rl/hacking.py): AST check in function bodies, then every flag read by hand.
-->

## 2. Key design decisions and trade-offs

<!--
- Write the rule before looking at the result, and keep it even when the number looks nearly good.
- More samples reduce evaluation noise; only another training seed measures training noise.
- The first hard-coding check flagged the model's own test lines; the second ignores them. Detector = pointer for a human.
- Stopped adding GPU recipes: 8-problem folds cannot see an effect below about +-0.064.
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
- Fold c's +0.04 vanished on a second sampling draw: it was luck.
- The crude hard-coding check flagged 6-11% of answers; reading them showed test lines and honest category words (triangle_type).
-->

## 4. Numbers

<!--
- Pooled 33 problems: 0.652 -> 0.675, +0.02 [0.00, +0.04], 15 better / 8 worse / 10 same, band +-0.032: within noise.
- Fold c seeds: held-out +0.03 / +0.04 (agree, band +-0.064); train +0.07 / +0.08.
- Audit: 31-32 flagged of 990 per model (3.1-3.2%) for every model; 1 real attempt (fizzbuzz, adapter c, failed hidden tests) in 4,950 trained answers.
-->

## 5. How I'd explain this in 60 seconds

<!--
(write it yourself; no facts here on purpose)
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
- more held-out problems, more seeds, longer training or the 1.5B, audit the training-time answers too, DPO on real hint ratings
-->

## 7. Five likely interview questions (and my answers)

<!--
1. Your held-out change is +0.02. Why don't you claim it works?
2. How do you separate evaluation noise from training noise?
3. Why write the rule before the run?
4. How did you check for reward hacking, and what are the limits?
5. What would you change to make the experiment readable?
-->
