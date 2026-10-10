"""A GRPO smoke run on the 0.5B (Week 6 Step 4): does the loop run, and what does it cost?

Usage:
    make rl-smoke RUN=smoke-partial MODE=partial STEPS=30
    uv run --group rl python scripts/rl_train.py --run-id x --mode all_or_nothing --steps 3

Needs the GPU (Ollama idle), Docker (the reward grades in Docker) and `make rl-data` first.
Writes lab/rl/scratch/<run-id>/{steps.jsonl, meta.json, adapter/}. Starts fresh every time.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from codetutor.evals.run import git_state
from codetutor.grader import SandboxUnavailableError
from codetutor.problems import load_all
from codetutor.rl.env import GIB, loaded_ollama_models, vram_verdict
from codetutor.rl.train import META_FILE, SmokeConfig, build_trainer, run_dir, train_file


def main() -> int:
    # Fewer memory holes on a small, shared GPU (set before torch starts).
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=["partial", "all_or_nothing"], default="partial")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--fold", default="a")
    args = parser.parse_args()
    config = SmokeConfig(
        run_id=args.run_id, reward_mode=args.mode, steps=args.steps, fold=args.fold
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
    shutil.rmtree(out_dir, ignore_errors=True)  # scratch runs always start fresh
    out_dir.mkdir(parents=True)
    commit, dirty = git_state()
    meta = {
        "config": config.model_dump(),
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
    trainer.train()
    trainer.save_model(str(out_dir / "adapter"))
    counters = reward.counters
    print(
        f"done: {counters.answers} answers graded, {counters.accepted} accepted, "
        f"{counters.errors} grading errors; log: {out_dir / 'steps.jsonl'}"
    )
    return 2 if counters.errors else 0


if __name__ == "__main__":
    sys.exit(main())
