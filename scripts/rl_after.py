"""The "after" report of one GRPO fold (Week 6 Step 5).

Usage:
    make rl-train-c        # ~2 h: trains the adapter (lab/rl/scratch/fold-c)
    # copy the adapter to lab/rl/adapters/fold-c, then:
    make rl-after-run      # ~15 min: the same eval as the baseline, with the adapter
    make rl-after-report   # lab/rl/reports/fold-c.md (no GPU)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codetutor.evals.metrics import load_run
from codetutor.problems import load_all
from codetutor.rl.after import render_report
from codetutor.rl.baseline import NamedRun
from codetutor.rl.train import META_FILE, STEP_LOG, read_step_log

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "lab" / "evals" / "results"
RUNS = {
    "c": (
        "hf-qwen2.5-coder-0.5b-bf16-t0.8-n10.jsonl",
        "hf-qwen2.5-coder-0.5b-grpo-c-t0.8-n10.jsonl",
        "lab/rl/results/fold-c",
    )
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["report"])
    parser.add_argument("--fold", default="c", choices=sorted(RUNS))
    args = parser.parse_args()
    before_file, after_file, train_dir = RUNS[args.fold]
    needed = [RESULTS / before_file, RESULTS / after_file, REPO / train_dir / STEP_LOG]
    missing = [str(p.relative_to(REPO)) for p in needed if not p.exists()]
    if missing:
        print(f"missing: {', '.join(missing)} (see the usage above)", file=sys.stderr)
        return 1
    before = NamedRun("before", load_run(RESULTS / before_file))
    after = NamedRun("after (GRPO)", load_run(RESULTS / after_file))
    steps = read_step_log(REPO / train_dir / STEP_LOG)
    meta = json.loads((REPO / train_dir / META_FILE).read_text(encoding="utf-8"))
    report = REPO / "lab" / "rl" / "reports" / f"fold-{args.fold}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(args.fold, before, after, load_all(), steps, meta), "utf-8")
    print(f"wrote {report.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
