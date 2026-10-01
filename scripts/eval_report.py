"""Write the Markdown eval report from one or more results files.

Usage:
    uv run python scripts/eval_report.py lab/evals/results/*.jsonl --out lab/evals/reports/week2.md

Each results file needs its <run_id>.meta.json next to it. The same files always give the same
report text, so a regenerated report only changes when the results change.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codetutor.evals.metrics import load_run
from codetutor.evals.report import render_report
from codetutor.problems import load_all

DEFAULT_OUT = Path("lab/evals/reports/week2.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, nargs="+", help="results files (*.jsonl)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the report")
    parser.add_argument("--title", default="Week 2 eval report: CS1 problem bank")
    args = parser.parse_args()

    try:
        runs = [load_run(path) for path in sorted(args.results)]
    except (OSError, ValueError) as exc:
        parser.error(f"cannot read the results: {exc}")
    text = render_report(runs, load_all(), args.title)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    partial = [run.meta.config.run_id for run in runs if run.is_partial]
    print(f"Wrote {args.out} ({len(runs)} runs, {len(text.splitlines())} lines)")
    if partial:
        print(f"Partial runs (marked in the report): {', '.join(partial)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
