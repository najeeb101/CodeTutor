# RL training (Weeks 6-7)

The grader is the reward: a small Qwen model answers each problem several times, `grade()` scores
every answer, GRPO pushes the model towards the passing ones, and we re-test on problems it never
saw. Decided 2026-10-07: train **locally in WSL on the laptop GPU** (the real Docker grader is
the reward), model **Qwen2.5-Coder-0.5B-Instruct first, 1.5B as a stretch**, hold out **whole
modules** (33 problems only; no generated problems yet).

Status: **Step 0** (the training environment, §1) and **Step 1** (the dataset, §2) and **Step 2** (the reward, §3) and **Step 3** (the "before" baseline, §4) are done. Next: GRPO smoke run (Week 6), then the real runs and re-evaluation (Week 7).

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

## 5. What is still open
- A 0.5B baseline does not exist yet. If it is near 0, the signal would be mostly format, and
  we would say so and start from 1.5B.
- Generation speed may need vLLM (a large new dependency): decide after the smoke run.
