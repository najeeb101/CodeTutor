# Lab (Weeks 2, 4, 5–7)

The AI-lab half of CodeTutor: model evals (Week 2) and the tutor's measurements (Week 4) now;
simulated students, the dataset builder and GRPO training later.

## evals/ (Week 2)
- `configs/`: one YAML file per official run (model, samples, temperature, seeds, ...).
- `results/`: committed results of official runs. `<run_id>.jsonl` has one graded answer per
  line (`EvalRecord`); `<run_id>.meta.json` says what produced them (versions, git commit,
  model digest).
- `reports/`: the generated report (`week2.md`), made by `scripts/eval_report.py`.
- `scratch/`: test and smoke runs (gitignored).

Run: `uv run --env-file .env python scripts/run_eval.py lab/evals/configs/<name>.yaml`.
How it works: [docs/evals.md](../docs/evals.md). The code is in `src/codetutor/evals/`.

## tutor/ (Week 4)
- `retrieval_questions.yaml`: 40 labelled questions for the note search (`scripts/eval_retrieval.py`).
- `results/`: committed results. `safety-<model>.jsonl`: the tutor on every buggy file (what
  it tries to show, what the guardrail blocks); `tutor-eval-<student>.jsonl` + `.meta.json`:
  the offline tutor eval (tutor hints and graded student answers, one per line).
- `reports/`: generated `retrieval.md`, `tutor_safety.md`, `tutor_eval.md` (do not edit by hand).
- `scratch/`: `--limit` runs (gitignored; a tutor-eval scratch run starts fresh).

Run: `uv run python scripts/tutor_eval.py` (resumable) or `--report-only`. How it works:
[docs/tutor.md](../docs/tutor.md) §5. The code is in `src/codetutor/tutor/`.

## sim/ (Week 5)
- `cohort-s<seed>.jsonl`: the simulated class, one planned submission per line (code, time,
  editor summary, and the **label**: persona, where the code came from, cheating or not).
- `cohort-s<seed>.meta.json`: the config, every student's true skill and persona, every
  problem's true difficulty, input hashes, git commit.

Run: `uv run python scripts/sim_cohort.py generate` (byte-identical rows every time). How it
works: [docs/integrity.md](../docs/integrity.md) §1. The code is in `src/codetutor/sim/`.
