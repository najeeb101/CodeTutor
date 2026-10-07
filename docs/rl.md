# RL training (Weeks 6-7)

The grader is the reward: a small Qwen model answers each problem several times, `grade()` scores
every answer, GRPO pushes the model towards the passing ones, and we re-test on problems it never
saw. Decided 2026-10-07: train **locally in WSL on the laptop GPU** (the real Docker grader is
the reward), model **Qwen2.5-Coder-0.5B-Instruct first, 1.5B as a stretch**, hold out **whole
modules** (33 problems only; no generated problems yet).

Status: **Step 0** (the training environment, §1) and **Step 1** (the dataset, §2) are done. Next:
reward function, "before" baseline, GRPO smoke run (Week 6), then the real runs and re-evaluation (Week 7).

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

## 3. What is still open
- A 0.5B baseline does not exist yet. If it is near 0, the signal would be mostly format, and
  we would say so and start from 1.5B.
- Generation speed may need vLLM (a large new dependency): decide after the smoke run.
