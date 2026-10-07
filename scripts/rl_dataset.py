"""Build the RL prompt files: four module folds, train and held-out (Week 6 Step 1).

Usage:
    python scripts/rl_dataset.py build              # all folds -> dist/rl/fold-<a..d>/
    python scripts/rl_dataset.py build --fold a     # one fold

Also writes lab/rl/splits.json (committed): which problems are train and held-out per fold.
Prompts come from the student view only. Same bank, same bytes. See docs/rl.md §2.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from codetutor.rl.dataset import (
    FOLDS,
    RL_DIR,
    UnknownFoldError,
    build_fold,
    fold_names,
    load_bank_with_hashes,
    split,
    write_splits,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write the dataset files")
    build.add_argument("--fold", choices=fold_names(), help="one fold (default: all)")
    args = parser.parse_args()

    bank = load_bank_with_hashes()
    problems = [problem for problem, _ in bank]
    folds = [args.fold] if args.fold else fold_names()
    print(f"{len(problems)} problems; prompts from the student view; files in {RL_DIR}")
    print("fold  held-out modules  train  held-out  held-out difficulty")
    try:
        for fold in folds:
            build_fold(bank, fold)
            train, held_out = split(problems, fold)
            mix = Counter(p.difficulty.value for p in held_out)
            modules = ", ".join(str(m) for m in FOLDS[fold])
            print(
                f"{fold:<4}  {modules:<16}  {len(train):>5}  {len(held_out):>8}  "
                + ", ".join(f"{k} {v}" for k, v in sorted(mix.items()))
            )
    except UnknownFoldError as exc:
        print(exc, file=sys.stderr)
        return 1
    path = write_splits(problems)
    print(f"wrote {path.relative_to(path.parents[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
