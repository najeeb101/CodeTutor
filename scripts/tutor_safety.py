"""Run the tutor on every buggy file and report what each model tries to show (docs/tutor.md §3).

Usage (Ollama running, `make notes-sync` done):
    python scripts/tutor_safety.py --model ollama/qwen2.5-coder:7b \
        --model ollama/qwen2.5-coder:1.5b-instruct-fp16
    python scripts/tutor_safety.py --report-only --model ...  # rebuild the report from results
    python scripts/tutor_safety.py --limit 3 --model ...      # a quick try: 3 problems, scratch

Writes lab/tutor/results/safety-<model>.jsonl and lab/tutor/reports/tutor_safety.md; with
--limit, everything goes to lab/tutor/scratch/ (gitignored), so a partial run never replaces
the official files. Grading uses the subprocess sandbox: the code is the bank's own buggy files.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.evals.clients import make_client, make_embedder
from codetutor.grader import SubprocessSandbox
from codetutor.problems.loader import load_all
from codetutor.tutor.notes import DEFAULT_EMBEDDER
from codetutor.tutor.safety import (
    DEFAULT_REPORT,
    DEFAULT_RESULTS_DIR,
    build_situations,
    read_records,
    render_report,
    results_path,
    run_safety,
    write_records,
)
from codetutor.tutor.service import TutorConfig

SCRATCH_DIR = DEFAULT_RESULTS_DIR.parent / "scratch"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", action="append", required=True, help="repeat for each model")
    parser.add_argument("--limit", type=int, default=None, help="only the first N problems")
    parser.add_argument("--report-only", action="store_true", help="only rebuild the report")
    args = parser.parse_args()

    results_dir = SCRATCH_DIR if args.limit else DEFAULT_RESULTS_DIR
    report_path = SCRATCH_DIR / "tutor_safety.md" if args.limit else DEFAULT_REPORT
    if not args.report_only:
        _run(args.model, args.limit, results_dir)
    missing = [m for m in args.model if not results_path(results_dir, m).exists()]
    if missing:
        print(f"no saved results for {missing} in {results_dir}", file=sys.stderr)
        return 1
    runs = {model: read_records(results_path(results_dir, model)) for model in args.model}
    report = render_report(runs)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"written to {report_path}")
    return 0


def _run(models: list[str], limit: int | None, results_dir: Path) -> None:
    problems = load_all()[:limit] if limit else load_all()
    started = time.perf_counter()
    situations = build_situations(problems, sandbox=SubprocessSandbox())
    print(f"{len(situations)} situations graded in {time.perf_counter() - started:.0f} s")
    embedder = make_embedder(DEFAULT_EMBEDDER)
    engine = make_engine()
    try:
        for spec in models:
            with Session(engine) as session:
                records = run_safety(
                    situations,
                    make_client(spec),
                    session=session,
                    embedder=embedder,
                    config=TutorConfig(model=spec),
                    progress=_printer(spec),
                )
            write_records(results_path(results_dir, spec), records)
    finally:
        engine.dispose()


def _printer(spec: str) -> Callable[[dict[str, Any]], None]:
    """A progress function that prints one numbered line per hint."""
    count = 0

    def progress(record: dict[str, Any]) -> None:
        nonlocal count
        count += 1
        tag = " injected" if record["injected"] else ""
        print(
            f"[{spec}] {count:3} {record['problem_id']} {record['buggy']} "
            f"L{record['level']}{tag}: {record['source']} ({record['latency_ms']:.0f} ms)",
            flush=True,
        )

    return progress


if __name__ == "__main__":
    raise SystemExit(main())
