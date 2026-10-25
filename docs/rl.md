# RL training (Weeks 6-7)

The grader is the reward: a small Qwen model answers each problem several times, `grade()` scores
every answer, GRPO pushes the model towards the passing ones, and we re-test on problems it never
saw. Decided 2026-10-07: train **locally in WSL on the laptop GPU** (the real Docker grader is
the reward), model **Qwen2.5-Coder-0.5B-Instruct first, 1.5B as a stretch**, hold out **whole
modules** (33 problems only; no generated problems yet).

Status: **Step 0** (the training environment, §1) and **Step 1** (the dataset, §2) and **Step 2** (the reward, §3) and **Step 3** (the "before" baseline, §4) and **Step 4** (the GRPO smoke run, §5) are done. Next: the real runs and re-evaluation (Week 7).

## 1. The training environment (Step 0)

```bash
make rl-install   # uv sync --group rl: the training packages (not part of `make install`)
make rl-env       # GPU, free memory, Ollama, the model, one graded answer
uv run --group rl python scripts/rl_env_check.py --model Qwen/Qwen2.5-Coder-1.5B-Instruct
```
- **Packages** (dependency group `rl`, exact versions in `uv.lock`): torch 2.14.1 (CUDA 13.0
  build), transformers 5.19.0, trl 1.14.2, peft, accelerate, datasets. Installing them added
  60 packages (34 → 94) and the virtual environment grew from 104 MB to 5.7 GB. `make install` (a plain `uv sync`, which is exact) should remove the group again (not tried:
  it would delete 5 GB); `make rl-install` puts it back. `uv run`, as used by `make all`, kept it.
- **The machine** (measured 2026-10-07, on battery): RTX 4060 Laptop, 8.0 GiB; the Windows desktop
  already uses ~1.1 GiB, so **6.9 GiB are free**; torch sees the GPU in WSL and supports bf16.
  The check warns when Ollama still holds a model (`ollama.exe ps`) or less than 6 GiB are free.
- **Models** come from the Hugging Face hub into its cache (not into git): 0.5B 0.93 GiB of
  weights in bf16, 1.5B 2.88 GiB. First load took 118 s (download + WSL file bridge), later
  loads ~50 s (0.5B) and ~200 s (1.5B, first time).
- **Generation speed** (plain `generate`, no vLLM, 512 new tokens, sampled at 0.8): about 15
  decoding steps per second whatever the batch size, so one round takes ~32 s for 8 answers
  and for 64 answers alike (peak memory 1.09 GiB at 8, 2.21 GiB at 64; 1.5B: 3.20 GiB at 8).
  Large batches are therefore much cheaper per answer: 64 answers ≈ 340 tokens/s against 36
  for 8. Grading in Docker takes ~2 s per answer. A GRPO step of 8 prompts × 8 answers is
  estimated at about a minute (not measured yet; Step 4 measures it).
- **Honest first look:** the first 0.5B answer to fizzbuzz was accepted, the first of a second
  run scored 0.3 (3 of 10 tests); the 1.5B's was accepted. One sample says nothing about
  quality: the baseline step measures it.
- **Before training:** unload Ollama's models (`ollama.exe ps` empty), close browsers; the GPU
  is shared with Windows.

## 2. The dataset (Step 1)

```bash
make rl-data        # dist/rl/fold-<a..d>/{train,heldout}.jsonl + manifest.json, lab/rl/splits.json
```
- **Rows** are the Week 2 prompt (`PROMPT_VERSION`, student view only) as a chat (`prompt`), plus
  `problem_id`, `problem_version`, `module`, `content_hash`. TRL's `GRPOTrainer` reads `prompt`
  and passes the other columns to the reward function. The solution, hints, buggy files and
  hidden tests cannot get in: the prompt is built from `StudentProblem`, and a test checks every
  row against the bank (no solution text, no non-trivial solution line, no hint, no buggy file).
- **Split by whole module**, four folds that hold out two modules each, so every problem is held
  out exactly once: `a` = modules 1+5, `b` = 2+6, `c` = 3+7, `d` = 4+8. Train 24-25 problems,
  held-out 8-9. The definition lives in one place (`FOLDS` in `rl/dataset.py`); the resulting
  problem lists are committed in `lab/rl/splits.json`, and a test fails if a changed bank would
  move a problem. `dist/rl/` is generated and byte-identical for the same bank.
- **Limits:** modules build on each other (recursion uses lists and functions), and a few
  problems are near-twins across modules, so "held out" means a different topic, not an unrelated
  skill. About 8 held-out problems per fold means wide intervals: report every fold, and
  never pick the fold after seeing results. The visible examples are in the prompts.

## 3. The reward (Step 2)

```bash
make rl-reward-bench   # consistency + speed + signal on the stored Week 2 answers (needs Docker, ~7 min)
```
- **`reward_for`** = `extract_code` + `grade(reveal_hidden=False)`: the same path as submissions
  and evals. **`TrlReward`** wraps it for `GRPOTrainer(reward_funcs=[...])` (it is called with
  `completions=[chat messages]` and the dataset's `problem_id` column; one float per answer, in
  order). It runs in the trainer process and sees the hidden tests; the model never does.
- **Modes** (`RewardConfig.mode`): `partial` (passed / total) or `all_or_nothing` (1.0 only if
  every test passes). The choice is made in Step 4 from measured signal, not by taste.
- **Never crashes a run:** one answer whose grading fails (a broken sandbox) is logged, counted
  in `counters.errors` and scored 0.0; an unknown `problem_id` is a loud setup error instead.
  This is the one broad `except Exception` besides the runner's (commented in the code).
- **Cheats tested** (fizzbuzz, real subprocess runs; none reaches 1.0): hard-coding the visible
  examples (caught by hidden tests; 0 under all-or-nothing), printing instead of returning,
  `sys.exit(0)`, `os._exit(0)`, a fake result token, no code, and code without the function.
- **Same number as the evals** (measured 2026-10-07, Docker): all **660 of 660** stored Week 2
  answers (330 per model) get exactly their stored reward.
- **Speed** (64 answers of the 1.5B, on mains): Docker 1 worker 1.3 answers/s, 4 workers 3.1,
  **8 workers 4.5** (14 s for 64); subprocess 48/s (trusted fixtures only). So the reward costs
  ~15 s per 64 answers, about half of one generation round (~32 s, §1): worth overlapping later,
  not a blocker.
- **Signal** (1.5B, 10 answers per problem): mean reward 0.953 (partial) or 0.867 (all-or-
  nothing), and **64% of the 33 groups are all-equal** (mostly all passing): nothing to learn
  there. The all-or-nothing mode raises the spread (0.21 → 0.36) but not the number of flat
  groups. So the 1.5B's problems are mostly "already solved"; Step 3 measures the 0.5B, which
  should have more informative groups, and Step 4 may train only on problems with a mixed group.
- **Limits:** partial credit lets a model earn points on easy tests; the Docker sandbox is the
  protection for model code (the subprocess one is for fixtures); an answer in a format the
  extractor misses scores 0, which also punishes honest format slips.

## 4. The "before" baseline (Step 3)

```bash
make rl-baseline-run      # both runs: GPU + Docker, ~35 min each, resumable (Ollama idle, on mains)
make rl-baseline-report   # lab/rl/reports/baseline.md from the committed results (no GPU)
```
- **One harness for everything:** the two runs are Week 2 `run_eval` runs with a new model
  prefix `hf/<hub id>` (`rl/hf.py`): all 33 problems, 10 answers each, temperature 0.8, plain
  sampling (no top-p, top-k or repetition penalty), 1024 new tokens, Docker grading, committed
  results + meta in `lab/evals/results/`. The 10 answers of a problem are generated in **one
  batch** (`BatchedResponder`), because a GPU decodes 10 about as fast as 1. In these records
  `seed` means the position in the batch (the batch itself uses seed 0). Every problem is held
  out in one fold, so one run per model is the baseline of all four folds.
- **Reproducible:** a 2-problem scratch run twice gave 20 of 20 identical answers.
- **Results** (details and per-fold tables: `lab/rl/reports/baseline.md`):

| Model | pass@1 [95%] | pass@5 | All-equal groups | Problems with a mixed group |
|---|---|---|---|---|
| 0.5B (HF) | 0.64 [0.53, 0.74] | 0.88 | 18% (partial) / 27% (all-or-nothing) | **24 of 33** |
| 1.5B (HF) | 0.90 [0.82, 0.96] | 0.98 | 64% / 64% | 12 of 33 |
| 1.5B (Ollama, Week 2) | 0.87 [0.78, 0.94] | 0.98 | 64% / 64% | – |

- **Reading:** the 1.5B through Hugging Face lands within 3 points of the Week 2 Ollama number
  (another runtime and sampler), so the two pipelines agree. The **0.5B is the model to train**:
  lots of room (pass@1 0.64) and a learning signal in 24 of 33 problems; for the 1.5B, 64% of the
  groups are all-equal, so GRPO would mostly see nothing to learn. Held-out folds differ a lot
  (0.5B: 0.41 on fold c, 0.80 on fold a, 8 problems each), so Week 7 must report all folds.
- **Limits:** one seed per run; 8-9 problems per held-out side; the all-or-nothing reward makes
  more groups all-equal for the 0.5B (27% vs 18%), so the reward mode is a real choice in Step 4.

## 5. The GRPO smoke run (Step 4)

```bash
make rl-smoke RUN=smoke-partial MODE=partial STEPS=30      # ~10 min; GPU + Docker; Ollama idle
make rl-smoke RUN=smoke-aon MODE=all_or_nothing STEPS=30
```
- **Setup** (`rl/train.py`, `scripts/rl_train.py`): Qwen2.5-Coder-0.5B-Instruct with a **LoRA
  adapter** (rank 16, all linear layers, lr 1e-5), fold `a` training side (25 problems), **1 prompt
  per step, 8 answers** (the GRPO group), 512 new tokens (the baseline used 1024), temperature
  0.8, seed 0, TRL 1.14.2 defaults otherwise (`beta` 0, DAPO loss, group-scaled advantages), the
  Docker grader as reward with 8 workers. The 8 answers are processed as 2 micro-batches of 4:
  the group and the update are the same, only less memory is needed at once.
- **It runs.** 30 steps each, 240 answers graded per run, **0 grading errors**, no leftover
  containers. Logs: `lab/rl/results/smoke/*/steps.jsonl` (+ `meta.json`).
- **Cost** (on mains): median **19.9 s per step** (partial) and 15.1 s (all-or-nothing; same
  work, so the gap is machine noise), first step ~28 s; grading is **~2 s of each step**
  (8 answers in parallel), so generating and updating the model is the cost. **Peak GPU memory
  4.86 GiB** (torch's own count; the first try with one batch of 8 hit an out-of-memory error
  at step 3 on the 6.9 GiB free). A 30-step run is ~10 min; 1,000 steps would be ~5.5 h.
- **Two things had to be fixed to start:** TRL's fused kernel needs Triton to compile a helper
  and that needs the C headers (`sudo apt install python3.12-dev`); and the memory fix above plus
  `PYTORCH_ALLOC_CONF=expandable_segments:True`.
- **Signal:** with one prompt per step, a step's group is all-equal in **7 of 30 steps (23%)**
  with partial credit and **9 of 30 (30%)** with all-or-nothing. Mean reward (all steps)
  0.81 vs 0.65; the all-or-nothing reward is lower because a 7-of-8-tests answer scores 0.
  The reward of the last 10 steps was 0.88 (partial; first 10: 0.77) and 0.64 (all-or-nothing;
  first 10: 0.65). **That is not learning evidence**: each step has a different problem, so
  those numbers mostly measure which problems came up.
- **Reward mode for the real runs: `partial`.** The rule written before the runs (fewer all-equal
  groups, tie goes to partial) picks it: 23% vs 30% is 2 steps of 30, too close to call, so it
  is a tie and the tie-break decides. Reason in words: partial gives a gradient inside groups
  where nobody passes everything. Watch-out: a slow-but-right `is_prime` earns 0.93.
- **Limits:** one seed, 30 steps, 30 prompts out of 25 problems (some repeat), different
  problems per step, a LoRA (can learn less than full tuning), 512 tokens (0.4% of answers cut
  off). Both runs started with the same first answers (same seed), then moved apart, so the two
  modes are not a controlled comparison. The metas say `git_dirty: true`: the runs started
  before the Step 4 code was committed (the code did not change during them).
- **Not measured:** whether training helps. That is Week 7: more steps, several prompts per
  step, all four folds, and the same eval as §4.

## 6. What is still open
- Generation takes most of a step (~15 s). vLLM would speed it up but is a large new dependency:
  decide in Week 7 only if the real runs are too slow (1,000 steps ≈ 5.5 h is bearable).
- `prefer_mode` in `rl/train.py` was written by Claude at Najeeb's request (2026-10-15); the decision above was made by the written rule.

## 7. The first real GRPO run, fold c (Step 5)
Fold c holds out modules 3 and 7 (8 problems). Chosen before any result because it had the most
room to improve (0.5B pass@1 0.41). Setup: Qwen2.5-Coder-0.5B + LoRA r16, 100 steps x 4 prompts
x 8 answers, `partial` reward, learning rate 1e-5, seed 0, trained only on the 20 train problems
whose baseline group was mixed. The report is `lab/rl/reports/fold-c.md`; the "before" and
"after" runs use the same eval pipeline (33 problems, 10 answers, temperature 0.8, Docker).

- **How it ran:** 1,600 answers graded, 1,245 accepted, 0 grading errors; train loss 0.026.
  The run was done in two parts: steps 1-50 on 2026-10-10 (stopped on purpose), then resumed
  from `checkpoint-50` on 2026-10-16 (the optimizer and random state are saved in the
  checkpoint, but a resumed run is not guaranteed to equal an uninterrupted one). The first try
  of the resume failed at once because Ollama still held a model in GPU memory; unloading it
  fixed that. The adapter (`d2083c23ec9f`) is kept in `lab/rl/adapters/fold-c`; the weights file
  is git-ignored, so only its config is committed.
- **Held-out problems (8):** pass@1 0.41 -> 0.45, pass@5 0.68 -> 0.69, mean reward 0.63 -> 0.65.
  Problem by problem: 3 better (+0.10 each), 0 worse, 5 the same; mean change +0.04.
  `group_anagrams` and `word_frequency` stay at 0.0, `two_sum` at 0.1.
- **Train problems (25):** pass@1 0.71 -> 0.81, mean reward 0.84 -> 0.92; 15 better, 3 worse,
  7 the same; mean change +0.10 [+0.05, +0.16].
- **Side effects:** answers got shorter (mean tokens 149 -> 121 on train, 146 -> 127 held out),
  compile errors fell (train 15 -> 5), nothing is cut off. The crude hard-coding check did not
  go up (train 36 -> 25 answers, held out 2 -> 1).
- **Honest reading:** the model got better at the problems it trained on, and moved a little in
  the right direction on problems it never saw. One held-out problem is 10 answers, so +0.10 is
  one more passing answer; three such moves are small. The per-problem interval
  [+0.01, +0.08] only resamples the 8 problems and does not include the noise of drawing 10
  answers, so it is too narrow to call the held-out gain proven. The training curve (0.81 ->
  0.92) is not a learning curve, because each step has different problems; the before/after
  table is the evidence. This is one fold, one seed, one run.
- **For Week 7:** the other three folds with the same settings, and a second seed on at least
  one fold, before any claim about transfer. Reading the flagged "visible result written out"
  answers by hand is still to do.

## 8. All four folds (Step 6)

Same recipe as fold c (§7) for folds a, b and d: 100 steps x 4 prompts, partial reward, the 0.5B
with a LoRA adapter, seed 0, trained only on the problems whose baseline group was mixed. Each
adapter then got the same eval as the baseline (33 problems x 10 answers). Reports:
`lab/rl/reports/fold-<a|b|c|d>.md` and `lab/rl/reports/folds.md` (made by `make rl-folds-report`).
Fold d: 3,200 answers graded, 2,183 accepted, 0 grading errors, about 1 h 27 min.

- **Held-out pass@1, before -> after (per-problem mean change):** a 0.80 -> 0.81 (+0.01),
  b 0.73 -> 0.73 (0.00), c 0.41 -> 0.45 (+0.04), d 0.61 -> 0.64 (+0.03).
- **Pooled:** every problem is held out in exactly one fold, so 33 changes. Mean change +0.02,
  interval [-0.02, +0.06], 11 better / 9 worse / 13 the same.
- **Honest reading:** the direction is slightly positive in three folds and flat in one, but the
  pooled interval includes 0 and it only resamples problems (it leaves out the noise of 10
  answers per problem). This is not evidence of transfer. The train problems do improve
  (fold b +0.11, d +0.05, c +0.10).
- **Not done:** a second seed (planned for fold c, skipped by Najeeb on 2026-10-23 to save about
  2.25 h of GPU time). The run-to-run noise of training is therefore unmeasured, so a difference
  between two folds can be luck of the run. `rl_after.py report-all` treats the `c-s1` run as
  optional, and the report says no second seed was run.
- **Not done either:** reading the flagged "visible result written out" answers by hand.

## 9. How big is eval luck? (Week 7, Step 1)

```bash
make rl-noise-run       # ~45 min; GPU + Docker: the baseline, adapter c and adapter b, draw 1000
make rl-noise-report    # lab/rl/reports/noise.md (no GPU)
```
- **Method:** the same three models were evaluated again on all 33 problems (10 answers,
  temperature 0.8, Docker); only `seed_base` changed from 0 to 1000, which shifts the batch seed
  (`HF_SEED + seed_base`, `rl/hf.py`). With `seed_base: 0` the official runs are unchanged.
  Every difference between two draws of one model is luck of the sampling. 990 answers, 0 failed.
- **Result:** the untrained 0.5B moved from pass@1 0.636 to 0.667 (+0.03) with no training at all;
  adapter c 0.724 -> 0.691, adapter b 0.721 -> 0.697. The per-problem differences have a spread
  (SD) of 0.16 (baseline), 0.11 (c), 0.13 (b).
- **Rule, written before the runs:** a fold's held-out change is "above noise" only if it is
  larger than `1.96 x SD / sqrt(m)` in both draws. With SD 0.161 and m = 8 the band is **±0.11**.
  Fold c: +0.04 (draw 0) and 0.00 (draw 1000); fold b: 0.00 and -0.01. **Both are within noise.**
  Fold c's +0.04 was a luck-sized move: on the other draw it vanished.
- **Pooled (33 problems), computed by hand, not in the report:** the same SD gives a band of
  about ±0.055, so the Week 6 pooled +0.02 is inside it as well.
- **Honest reading:** the Week 6 held-out numbers cannot be told apart from evaluation luck.
  This does **not** show that GRPO does nothing; it shows our 8-problem folds cannot see an
  effect of this size. Train-side gains (+0.05 to +0.11, 25 problems) are larger than the
  pooled band's scale, but were not re-measured on another draw.
- **Limits:** two draws only (the SD is uncertain); evaluation noise only, **training noise**
  (another training seed) is still unmeasured and can be larger; the metas say
  `git_dirty: true` because `Makefile` and `scripts/rl_after.py` were edited while the runs
  went (the `seed_base` code itself was committed first, `c2c32db`).
- **Consequence for Step 2:** a stronger recipe must be judged against ±0.11 per fold, so it
  needs a much larger gain, or more held-out answers per problem (e.g. 30 instead of 10), to be
  readable.

## 10. Thirty answers per problem (Week 7, Step 2a)

```bash
make rl-pool-run        # ~1.75 h; GPU + Docker: the 7 missing draws (resumable)
make rl-pool-report     # lab/rl/reports/pooled.md (no GPU, byte-identical)
```
- **Method:** every model (untrained 0.5B, adapters a-d) now has three draws (`seed_base` 0,
  1000, 2000) of 10 answers per problem, pooled to 30 answers per problem. 7 new runs, 330
  answers each, metas `git_dirty: false` (commit 0782f6d). The rule was written in `rl/pooled.py`
  before the runs: "above noise" only if the 95% interval over problems excludes 0 **and** the
  change is larger than `1.96 x SD / sqrt(m)`; SD 0.092 comes from the untrained model's 3 draws.
- **Result (held-out, before -> after):** a +0.03 [-0.01, +0.06], b 0.00 [-0.04, +0.05],
  c +0.03 [0.00, +0.05], d +0.04 [0.00, +0.09]; **all 33 problems pooled +0.02 [0.00, +0.04],
  15 better / 8 worse / 10 same, band ±0.032. Every row is "within noise".** Pooled pass@1 over
  all problems: untrained 0.652; adapters 0.688 / 0.710 / 0.710 / 0.690 (these include
  problems each adapter trained on).
- **Honest reading:** the pooled interval now just touches 0 and the direction is positive in all
  four folds, but the change (+0.023) is smaller than the band (0.032), so by our own rule we
  do not claim transfer. This is a small possible effect, not a shown one.
- **Limits:** SD from 3 draws is uncertain; evaluation noise only. **Training noise** (another
  training seed) is still unmeasured. The band treats problems as independent.

## 11. A second training seed on fold c (Week 7, Step 2b)

Same recipe as §7 (LoRA r16, 100 steps x 4 prompts x 8 answers, partial reward, lr 1e-5, only the
mixed-baseline problems), only `--seed 1`. Question: is the training run itself repeatable?

**Rule, written and committed before the run.** Fold c held-out change is measured on the pooled
3 draws (30 answers per problem) for both seeds. The seeds **agree** if both changes point the
same way (a change of 0 counts as neither) and differ by less than the evaluation band
`1.96 x SD / sqrt(m)` (SD 0.092, m = 8: ±0.064). Otherwise they **disagree**, and a single
training run cannot be trusted. Agreement shows repeatability, not transfer: "above noise" is still
decided by the Step 2a rule. Code: `seeds_agree`, `render_seed_report` in `rl/pooled.py`.

```bash
make rl-train FOLD=c SEED=1   # ~1.5 h; copy the adapter to lab/rl/adapters/fold-c-s1
make rl-seed-run              # ~45 min: three sampling draws of that adapter
make rl-seed-report           # lab/rl/reports/seeds.md (no GPU)
```

Results (`lab/rl/reports/seeds.md`, byte-identical on rebuild; seed 1 adapter `807e3d7d0c6d`,
weights git-ignored like fold c; 100 steps):

| Problems | Change seed 0 | Change seed 1 | Seed 1 − seed 0 | Noise band | Verdict |
|---|---|---|---|---|---|
| fold c held out (8) | +0.03 | +0.04 | +0.02 [−0.02, +0.05] | ±0.064 | seeds agree |
| fold c train (25) | +0.07 | +0.08 | +0.01 [−0.01, +0.03] | ±0.036 | seeds agree |

- **Reading:** the two training runs give almost the same result, on the held-out and on the train
  problems. So one training run is repeatable here: the first seed was not a lucky one.
- **Not shown:** both held-out changes (+0.03, +0.04) are still under the Step 2a evaluation band
  for 8 problems, so this is repeatability, not proof of transfer. Two seeds on one fold only.
