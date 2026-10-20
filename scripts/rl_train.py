"""GRPO training on the 0.5B (Week 6 Steps 4-5).

Usage:
    make rl-smoke RUN=smoke-partial MODE=partial STEPS=30          # Step 4: 1 prompt per step
    make rl-train FOLD=c                                           # Steps 5-6: the real run
    uv run --group rl python scripts/rl_train.py --run-id x --steps 3 --prompts-per-step 4

Needs the GPU (Ollama idle), Docker (the reward grades in Docker) and `make rl-data` first.
Writes lab/rl/scratch/<run-id>/{steps.jsonl, meta.json, adapter/}. Starts fresh every time.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from codetutor.evals.metrics import load_run
from codetutor.evals.run import git_state
from codetutor.grader import SandboxUnavailableError
from codetutor.problems import load_all
from codetutor.rl.dataset import split
from codetutor.rl.env import GIB, loaded_ollama_models, vram_verdict
from codetutor.rl.train import (
    META_FILE,
    TrainConfig,
    build_trainer,
    mixed_problem_ids,
    run_dir,
    train_file,
)

BASELINE_RESULTS = (
    Path(__file__).resolve().parents[1]
    / "lab"
    / "evals"
    / "results"
    / "hf-qwen2.5-coder-0.5b-bf16-t0.8-n10.jsonl"
)


def mixed_ids(fold: str) -> list[str]:
    """The fold's training problems with a mixed baseline group (0.5B, Step 3 results)."""
    baseline = load_run(BASELINE_RESULTS)
    train, _ = split(load_all(), fold)
    return mixed_problem_ids(baseline.records, [p.id for p in train])


def main() -> int:
    # Fewer memory holes on a small, shared GPU (set before torch starts).
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=["partial", "all_or_nothing"], default="partial")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--fold", default="a")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prompts-per-step", type=int, default=1)
    parser.add_argument("--save-steps", type=int, default=None)
    parser.add_argument(
        "--only-mixed",
        action="store_true",
        help="train only on problems whose baseline answers did not all get the same reward",
    )
    parser.add_argument("--resume", action="store_true", help="continue from the last checkpoint")
    args = parser.parse_args()
    train_problems = mixed_ids(args.fold) if args.only_mixed else None
    config = TrainConfig(
        run_id=args.run_id,
        reward_mode=args.mode,
        steps=args.steps,
        fold=args.fold,
        seed=args.seed,
        prompts_per_step=args.prompts_per_step,
        save_steps=args.save_steps,
        train_problems=None if train_problems is None else tuple(train_problems),
    )

    import torch
    import transformers
    import trl

    if not torch.cuda.is_available():
        print("torch can't see the GPU (see `make rl-env`).", file=sys.stderr)
        return 1
    if not train_file(config).exists():
        print(f"{train_file(config)} is missing: run `make rl-data` first.", file=sys.stderr)
        return 1
    free_bytes, _ = torch.cuda.mem_get_info()
    problems = vram_verdict(free_bytes / GIB, loaded_ollama_models())
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    out_dir = run_dir(config)
    if not args.resume:
        shutil.rmtree(out_dir, ignore_errors=True)  # runs start fresh unless --resume
    out_dir.mkdir(parents=True, exist_ok=True)
    commit, dirty = git_state()
    meta = {
        "config": config.model_dump(),
        "train_problems": list(train_problems) if train_problems is not None else None,
        "git_commit": commit,
        "git_dirty": dirty,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "trl": trl.__version__,
        "device": torch.cuda.get_device_name(0),
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    try:
        trainer, reward = build_trainer(config, load_all(), out_dir)
    except SandboxUnavailableError as error:
        print(f"{error}\nStart Docker first.", file=sys.stderr)
        return 1
    trainer.train(resume_from_checkpoint=True if args.resume else None)
    trainer.save_model(str(out_dir / "adapter"))
    counters = reward.counters
    print(
        f"done: {counters.answers} answers graded, {counters.accepted} accepted, "
        f"{counters.errors} grading errors; log: {out_dir / 'steps.jsonl'}"
    )
    return 2 if counters.errors else 0


if __name__ == "__main__":
    sys.exit(main())
