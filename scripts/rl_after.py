"""The "after" report of one GRPO fold (Week 6 Step 5).

Usage:
    make rl-train FOLD=c          # ~2 h: trains the adapter (lab/rl/scratch/fold-c)
    # copy the adapter to lab/rl/adapters/fold-c, then:
    make rl-after-run RUN=c       # ~15 min: the same eval as the baseline, with the adapter
    make rl-after-report          # lab/rl/reports/fold-c.md (no GPU)
    make rl-folds-report          # lab/rl/reports/folds.md: all runs together (no GPU)
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
    parser.add_argument("command", choices=["report", "report-all"])
    parser.add_argument("--fold", default="c", choices=[n for n in RUNS if "-" not in n])
    args = parser.parse_args()
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
