"""Does a hint help a student model fix a hidden-only bug? (the tutor eval, docs/tutor.md §5)

Usage (Ollama running; Docker running; `make notes-sync` done):
    python scripts/tutor_eval.py --conditions none     # the pilot: the no-hint baseline only
    python scripts/tutor_eval.py                       # every condition (resumes; skips done)
    python scripts/tutor_eval.py --report-only         # rebuild the report from the results
    python scripts/tutor_eval.py --limit 2             # a quick try: 2 problems, in scratch

Writes lab/tutor/results/tutor-eval-<student>.jsonl (+ .meta.json) and
lab/tutor/reports/tutor_eval.md. With --limit, everything goes to lab/tutor/scratch/
(gitignored) and starts fresh (like run_eval.py), so a partial run never mixes with the
official file, and an older scratch run with another --limit never blocks a new one. The
student's answers are graded in the Docker sandbox (model code is untrusted).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.evals.clients import ModelError, make_client, make_embedder
from codetutor.grader import DockerSandbox, SandboxUnavailableError, SubprocessSandbox
from codetutor.problems.loader import load_all
from codetutor.tutor.notes import DEFAULT_EMBEDDER
from codetutor.tutor.safety import build_situations
from codetutor.tutor.service import TutorConfig
from codetutor.tutor.tutor_eval import (
    CONDITIONS,
    DEFAULT_REPORT,
    DEFAULT_RESULTS_DIR,
    SCRATCH_DIR,
    TutorEvalMismatchError,
    TutorEvalSettings,
    hidden_only,
    make_tutor_hints,
    meta_path_for,
    read_records,
    results_path,
    run_student,
    start_or_check_meta,
)
from codetutor.tutor.tutor_eval_report import render_report


def _progress(started: float) -> Any:
    def show(record: dict[str, Any], done: int, expected: int) -> None:
        if record["kind"] == "hint":
            what = f"hint L{record['level']} {record['source']}"
        else:
            what = f"{record['condition']:<9} #{record['sample_index']} {record['status']}"
        elapsed = time.monotonic() - started
        print(f"[{done}/{expected} {elapsed:6.0f} s] {record['situation']}: {what}", flush=True)

    return show


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    defaults = TutorEvalSettings()
    parser.add_argument("--student", default=defaults.student)
    parser.add_argument("--tutor", default=defaults.tutor)
    parser.add_argument("--n", type=int, default=defaults.samples, help="answers per condition")
    parser.add_argument(
        "--conditions", nargs="+", default=list(CONDITIONS), choices=CONDITIONS, metavar="C"
    )
    parser.add_argument("--limit", type=int, help="only the first N problems (scratch run)")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    settings = TutorEvalSettings(student=args.student, tutor=args.tutor, samples=args.n)
    scratch = args.limit is not None
    path = results_path(SCRATCH_DIR if scratch else DEFAULT_RESULTS_DIR, settings.student)
    report = SCRATCH_DIR / "tutor_eval.md" if scratch else DEFAULT_REPORT
    problems = load_all()[: args.limit] if scratch else load_all()

    if not args.report_only:
        if scratch:  # scratch runs always start fresh (only the scratch folder's files)
            path.unlink(missing_ok=True)
            meta_path_for(path).unlink(missing_ok=True)
        status = _run(args, settings, problems, path)
        if status != 0:
            return status
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(read_records(path), path), encoding="utf-8")
    print(f"report: {report}")
    return 0


def _run(args: argparse.Namespace, settings: TutorEvalSettings, problems: list, path: Path) -> int:
    try:
        sandbox = DockerSandbox()
    except SandboxUnavailableError as exc:
        print(f"{exc}\nStart Docker: the student's answers are model code.", file=sys.stderr)
        return 1
    # The buggy files are the bank's own code: the subprocess sandbox is fine for them.
    situations = hidden_only(build_situations(problems, sandbox=SubprocessSandbox()))
    print(f"{len(situations)} hidden-only situations in {len(problems)} problems")
    tutor_config = TutorConfig(model=settings.tutor)
    try:
        start_or_check_meta(settings, tutor_config, situations, path)
    except TutorEvalMismatchError as exc:
        print(exc, file=sys.stderr)
        return 1
    started = time.monotonic()
    engine = make_engine()
    try:
        if any(condition.startswith("tutor") for condition in args.conditions):
            with Session(engine) as session:
                hints = make_tutor_hints(
                    situations,
                    make_client(settings.tutor),
                    path,
                    session=session,
                    embedder=make_embedder(DEFAULT_EMBEDDER),
                    config=tutor_config,
                    on_record=_progress(started),
                )
            print(f"tutor hints: {hints.added} new, {hints.already_done} already saved")
        answers = run_student(
            situations,
            args.conditions,
            settings,
            make_client(settings.student),
            sandbox,
            path,
            on_record=_progress(started),
        )
    except ModelError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"answers: {answers.added} new, {answers.already_done} already saved, "
        f"{len(answers.failed_calls)} failed calls, {time.monotonic() - started:.0f} s"
    )
    for failure in answers.failed_calls:
        print(f"  failed: {failure}")
    if answers.stop_reason:
        print(f"stopped early: {answers.stop_reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
