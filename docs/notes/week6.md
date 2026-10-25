# Week 6: GRPO training of a small model with the grader as reward

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
Raw facts (pick 3-5 bullets, say what each part DOES):
- RL environment (rl/env.py): `rl` dependency group (torch, transformers, TRL, peft); the 0.5B fits the 8 GB GPU in bf16.
- Prompt folds (rl/dataset.py): hold out two whole modules per fold (a=1+5, b=2+6, c=3+7, d=4+8), so every problem is held out once. Split committed in lab/rl/splits.json.
- Reward (rl/reward.py): extract code, grade with the same grade() (hidden tests included), partial credit; 660/660 stored Week 2 answers get exactly their stored reward.
- Baseline (rl/hf.py, rl/baseline.py): untrained 0.5B pass@1 0.64, 1.5B 0.90; the 0.5B has more mixed groups, so it is the one to train.
- Training (rl/train.py): GRPO + LoRA r16, 1 prompt x 8 answers in the smoke run; the real run 100 steps x 4 prompts, only problems with mixed baseline results.
-->

## 2. Key design decisions and trade-offs

<!--
- Hold out whole modules, not random problems (a different topic, not an unrelated skill).
- Partial reward vs all-or-nothing: tie in the smoke runs, so partial (rule written before).
- LoRA instead of full tuning (GPU memory); micro-batches of 4 and expandable segments after an out-of-memory error.
- Re-measured the baseline through Hugging Face rather than reuse the Ollama number.
- Skipped the second seed on fold c in Week 6 (saves ~2.25 h GPU); done in Week 7.
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
- 64% of the 1.5B's groups were all-equal (no learning signal), so the 0.5B was chosen.
- CUDA out of memory at step 3 with one batch of 8; Triton needed python3.12-dev.
- Resume from checkpoint-50 failed because Ollama held a model in GPU memory.
-->

## 4. Numbers

<!--
Held-out pass@1 before -> after, first draw: a 0.80->0.81, b 0.73->0.73, c 0.41->0.45, d 0.61->0.64; pooled +0.02 [-0.02, +0.06]. Train problems improve (b +0.11, c +0.10, d +0.05). Fold d: 3,200 answers, 2,183 accepted, 0 grading errors. Docker grading 4.5 answers/s at 8 workers.
-->

## 5. How I'd explain this in 60 seconds

<!--
(write it yourself; no facts here on purpose)
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
- bigger model, more problems (LLM-drafted + validated), vLLM for generation, more seeds, a learning curve on held-out problems during training
-->

## 7. Five likely interview questions (and my answers)

<!--
1. Why must a GRPO reward vary inside a group?
2. Why split by module and report all four folds?
3. Why is the grader a good reward, and what can go wrong (reward hacking)?
4. Why LoRA, and what does it change about what you can claim?
5. Why did you train the 0.5B and not the 1.5B?
-->
