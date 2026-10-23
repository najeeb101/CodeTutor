"""The "after" report of one GRPO fold (Week 6 Step 5).

Usage:
    make rl-train FOLD=c          # ~2 h: trains the adapter (lab/rl/scratch/fold-c)
    # copy the adapter to lab/rl/adapters/fold-c, then:
    make rl-after-run RUN=c       # ~15 min: the same eval as the baseline, with the adapter
    make rl-after-report          # lab/rl/reports/fold-c.md (no GPU)
    make rl-folds-report          # lab/rl/reports/folds.md: all runs together (no GPU)
    make rl-noise-report          # lab/rl/reports/noise.md: the same models, two draws (Week 7)
    # optional second seed on fold c (not run): make rl-train FOLD=c SEED=1 (RUN=c-s1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codetutor.evals.metrics import load_run
from codetutor.problems import load_all
from codetutor.rl.after import FoldRun, render_folds_report, render_report
from codetutor.rl.baseline import NamedRun
from codetutor.rl.noise import render_noise_report
from codetutor.rl.train import META_FILE, STEP_LOG, read_step_log

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "lab" / "evals" / "results"
# name -> (fold, training seed). Seed 0 of every fold, then a second seed on fold c.
RUNS = {"a": ("a", 0), "b": ("b", 0), "c": ("c", 0), "d": ("d", 0), "c-s1": ("c", 1)}
# The second seed is optional: it was skipped on 2026-10-23 (Najeeb), the four folds stand alone.
OPTIONAL_RUNS = {"c-s1"}
BEFORE_FILE = "hf-qwen2.5-coder-0.5b-bf16-t0.8-n10.jsonl"


def after_file(name: str) -> str:
    """The results file of the eval of run `name`'s adapter."""
    return f"hf-qwen2.5-coder-0.5b-grpo-{name}-t0.8-n10.jsonl"


def redraw_file(filename: str) -> str:
    """The results file of the same eval with the other sampling draw (seed_base 1000)."""
    return filename.removesuffix(".jsonl") + "-s1000.jsonl"


# Folds whose adapters were re-evaluated with a second draw (Week 7 Step 1); b is optional.
NOISE_FOLDS = ("c", "b")


def noise_missing(names: list[str]) -> list[str]:
    """Files the noise report needs that are not there yet."""
    needed = [RESULTS / BEFORE_FILE, RESULTS / redraw_file(BEFORE_FILE)]
    for name in names:
        needed += [RESULTS / after_file(name), RESULTS / redraw_file(after_file(name))]
        needed += [train_dir(name) / STEP_LOG]
    return [str(p.relative_to(REPO)) for p in needed if not p.exists()]


def write_noise_report() -> Path:
    """Build lab/rl/reports/noise.md from the committed results."""
    names = [n for n in NOISE_FOLDS if n == NOISE_FOLDS[0] or not noise_missing([n])]
    bank = load_all()
    base = (
        NamedRun("draw 0", load_run(RESULTS / BEFORE_FILE)),
        NamedRun("draw 1000", load_run(RESULTS / redraw_file(BEFORE_FILE))),
    )
    adapters, folds = {}, {}
    for name in names:
        fold, seed = RUNS[name]
        pair = tuple(
            NamedRun(f"{name} draw {d}", load_run(RESULTS / f))
            for d, f in ((0, after_file(name)), (1000, redraw_file(after_file(name))))
        )
        adapters[name] = pair
        folds[name] = tuple(
            FoldRun(name, fold, seed, b, a) for b, a in zip(base, pair, strict=True)
        )
    target = REPO / "lab" / "rl" / "reports" / "noise.md"
    target.write_text(render_noise_report(base, adapters, folds, bank), "utf-8")
    return target


def train_dir(name: str) -> Path:
    """The committed training log folder of run `name`."""
    return REPO / "lab" / "rl" / "results" / f"fold-{name}"


def missing_files(name: str) -> list[str]:
    """Files run `name` needs that are not there yet."""
    needed = [RESULTS / BEFORE_FILE, RESULTS / after_file(name), train_dir(name) / STEP_LOG]
    return [str(p.relative_to(REPO)) for p in needed if not p.exists()]


def runs_for_report_all() -> tuple[list[str], list[str]]:
    """(runs to report, files missing from them). An absent optional run is skipped."""
    names = [n for n in RUNS if n not in OPTIONAL_RUNS or not missing_files(n)]
    return names, [m for n in names for m in missing_files(n)]


def load_fold_run(name: str) -> FoldRun:
    """Load the baseline and the adapter's eval of run `name`."""
    fold, seed = RUNS[name]
    before = NamedRun("before", load_run(RESULTS / BEFORE_FILE))
    after = NamedRun("after (GRPO)", load_run(RESULTS / after_file(name)))
    return FoldRun(name, fold, seed, before, after)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["report", "report-all", "noise"])
    parser.add_argument("--fold", default="c", choices=[n for n in RUNS if "-" not in n])
    args = parser.parse_args()
    if args.command == "noise":
        missing = noise_missing([NOISE_FOLDS[0]])
        if missing:
            print(f"missing: {', '.join(missing)} (make rl-noise-run)", file=sys.stderr)
            return 1
        print(f"wrote {write_noise_report().relative_to(REPO)}")
        return 0
    if args.command == "report":
        names = [args.fold]
        missing = missing_files(args.fold)
    else:
        names, missing = runs_for_report_all()
        for skipped in sorted(set(RUNS) - set(names)):
            print(f"note: run {skipped} not found, skipped (optional)", file=sys.stderr)
    if missing:
        print(f"missing: {', '.join(missing)} (see the usage above)", file=sys.stderr)
        return 1
    reports = REPO / "lab" / "rl" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    bank = load_all()
    if args.command == "report":
        run = load_fold_run(args.fold)
        steps = read_step_log(train_dir(args.fold) / STEP_LOG)
        meta = json.loads((train_dir(args.fold) / META_FILE).read_text(encoding="utf-8"))
        target = reports / f"fold-{args.fold}.md"
        target.write_text(
            render_report(args.fold, run.before, run.after, bank, steps, meta), "utf-8"
        )
    else:
        target = reports / "folds.md"
        target.write_text(render_folds_report([load_fold_run(n) for n in names], bank), "utf-8")
    print(f"wrote {target.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
