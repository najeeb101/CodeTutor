# Lab (Weeks 2, 5–7)

The AI-lab half of CodeTutor: evals now; simulated students, the dataset builder and GRPO
training later.

## evals/ (Week 2)
- `configs/`: one YAML file per official run (model, samples, temperature, seeds, ...).
- `results/`: committed results of official runs. `<run_id>.jsonl` has one graded answer per
  line (`EvalRecord`); `<run_id>.meta.json` says what produced them (versions, git commit,
  model digest).
- `scratch/`: test and smoke runs (gitignored).

Run: `uv run --env-file .env python scripts/run_eval.py lab/evals/configs/<name>.yaml`.
How it works: [docs/evals.md](../docs/evals.md). The code is in `src/codetutor/evals/`.
