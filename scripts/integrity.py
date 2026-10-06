"""Run the integrity checks over a database and store the flags (Week 5 Steps 2b-2c).

Usage:
    python scripts/integrity.py run --seed 0     # the simulated class codetutor_sim
    python scripts/integrity.py run --seed 1     # the held-out class codetutor_sim_s1
    python scripts/integrity.py run --dev        # the development database
    python scripts/integrity.py tune --seed 0    # the threshold search (prints the top 10)
    python scripts/integrity.py report           # lab/integrity/reports/integrity.md

A batch job, not part of the worker (decided 2026-10-06): it reads every submission, runs the
four signals (src/codetutor/integrity/signals.py) and replaces all rows of `integrity_flags`
in one transaction, so running it again is safe. It migrates the database first (the sim
databases may be older than migration 0008). Flags are signals for a teacher, never a
punishment; no student-facing route reads them. See docs/integrity.md §2.

`tune` and `report` read the graded simulated classes and join the labels from the cohort
files (lab/sim/); they never write to a database. The thresholds are chosen on seed 0 only;
the report measures them once on held-out seed 1 (§2.4).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from codetutor.db.admin import database_name, migrate_to_head
from codetutor.db.engine import make_engine
from codetutor.evals.report import fixed
from codetutor.integrity.evaluate import FastFlags, labelled, search
from codetutor.integrity.known_ai import known_ai_answers
from codetutor.integrity.report import ClassData, ThresholdsNotFrozenError, render_report
from codetutor.integrity.signals import (
    INTEGRITY_VERSION,
    FlagKind,
    KnownAnswer,
    detect,
    needs_review,
)
from codetutor.integrity.store import load_submissions, replace_flags
from codetutor.problems.loader import load_all
from codetutor.settings import database_url, sim_database_url
from codetutor.sim.cohort import read_rows

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "lab" / "integrity" / "reports" / "integrity.md"
TUNING_SEED = 0
HELD_OUT_SEED = 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the checks and replace the stored flags")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--seed", type=int, help="a simulated class (0: codetutor_sim)")
    which.add_argument("--dev", action="store_true", help="the development database")
    tune = commands.add_parser("tune", help="the threshold search on one simulated class")
    tune.add_argument("--seed", type=int, default=TUNING_SEED)
    commands.add_parser("report", help=f"write {REPORT.relative_to(REPO)}")
    args = parser.parse_args()
    try:
        if args.command == "tune":
            return _tune(args.seed)
        if args.command == "report":
            return _report()
    except OperationalError as exc:
        print(
            f"can't reach a simulated class: run `make db-up` (and `make sim`, "
            f"`SIM_SEED=1 make sim`).\n{exc.orig}",
            file=sys.stderr,
        )
        return 1
    return _run(args.dev, args.seed)


def _run(dev: bool, seed: int | None) -> int:
    url = database_url() if dev else sim_database_url(seed)
    if not dev and "sim" not in database_name(url):
        print(f"refusing: {database_name(url)!r} is not a sim database", file=sys.stderr)
        return 1
    try:
        migrate_to_head(url)
    except OperationalError as exc:
        print(
            f"can't reach {database_name(url)!r}: run `make db-up` (and `make sim` for a "
            f"simulated class).\n{exc.orig}",
            file=sys.stderr,
        )
        return 1
    start = time.perf_counter()
    known = known_ai_answers(load_all())
    engine = make_engine(url)
    try:
        with Session(engine) as session:
            submissions = load_submissions(session)
            flags = detect(submissions, known)
            replace_flags(session, flags)
            session.commit()
    finally:
        engine.dispose()

    kinds = Counter(flag.kind for flag in flags)
    by_submission: dict[int, set[FlagKind]] = defaultdict(set)
    for flag in flags:
        by_submission[flag.submission_id].add(flag.kind)
    review = sum(needs_review(found) for found in by_submission.values())
    print(
        f"{database_name(url)}: {len(submissions)} submissions, {len(flags)} flags "
        f"(detector version {INTEGRITY_VERSION}) in {time.perf_counter() - start:.1f} s"
    )
    for kind in FlagKind:
        print(f"  {kind.value:<16} {kinds[kind]}")
    print(f"  needs review     {review} submissions (an entry and a content signal)")
    return 0


def _tune(seed: int) -> int:
    start = time.perf_counter()
    data = _class_data(seed, known_ai_answers(load_all()))
    points = search(data.fast, data.rows)
    print(f"seed {seed}: {len(points)} settings in {time.perf_counter() - start:.1f} s, best first")
    print("  paste  chars/s  similarity  flagged  precision  recall  F0.5")
    for point in points[:10]:
        c, s = point.config, point.scores
        print(
            f"  {c.paste_share:5.1f}  {c.chars_per_s:7.0f}  {c.similarity:10.1f}  {s.flagged:7d}  "
            f"{fixed(s.precision or 0.0, 3):>9}  {fixed(s.recall or 0.0, 3):>6}  {fixed(s.f, 3)}"
        )
    return 0


def _report() -> int:
    known = known_ai_answers(load_all())
    tuning = _class_data(TUNING_SEED, known)
    held_out = _class_data(HELD_OUT_SEED, known)
    try:
        text = render_report(tuning, held_out)
    except ThresholdsNotFrozenError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 1
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


def _class_data(seed: int, known: dict[str, list[KnownAnswer]]) -> ClassData:
    """A graded simulated class with its labels (the database's view + the cohort file)."""
    url = sim_database_url(seed)
    if "sim" not in database_name(url):
        raise SystemExit(f"refusing: {database_name(url)!r} is not a sim database")
    cohort = REPO / "lab" / "sim" / f"cohort-s{seed}.jsonl"
    engine = make_engine(url)
    try:
        with Session(engine) as session:
            submissions = load_submissions(session)
    finally:
        engine.dispose()
    return ClassData(
        seed=seed,
        database=database_name(url),
        cohort_file=str(cohort.relative_to(REPO)),
        cohort_sha256=hashlib.sha256(cohort.read_bytes()).hexdigest(),
        rows=labelled(submissions, read_rows(cohort)),
        fast=FastFlags(submissions, known),
    )


if __name__ == "__main__":
    sys.exit(main())
