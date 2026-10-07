"""Problem difficulty and student skill from first attempts (Week 5 Step 3).

Usage:
    python scripts/skill.py report        # lab/skill/reports/skill.md (both simulated classes)
    python scripts/skill.py show --dev    # hardest problems and skill list of the dev database

`report` reads the two graded simulated classes (`make sim`, `SIM_SEED=1 make sim`), the
frozen integrity checks (detector version 1, computed on the fly: it does not read or write the
`integrity_flags` table) and the cohort files for the true values. It never writes to a
database. `show` is the plain use: estimates only, no truth. See docs/integrity.md §3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from codetutor.db.admin import database_name
from codetutor.db.engine import make_engine
from codetutor.evals.report import fixed
from codetutor.integrity.evaluate import review_ids
from codetutor.integrity.known_ai import known_ai_answers
from codetutor.integrity.signals import detect
from codetutor.integrity.store import load_submissions
from codetutor.problems.loader import load_all
from codetutor.settings import database_url, sim_database_url
from codetutor.skill.evaluate import estimate
from codetutor.skill.load import first_attempts
from codetutor.skill.report import ClassData, render_report

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "lab" / "skill" / "reports" / "skill.md"
SEEDS = (0, 1)
SHOWN = 10


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("report", help=f"write {REPORT.relative_to(REPO)}")
    show = commands.add_parser("show", help="estimates for one database")
    show.add_argument("--dev", action="store_true", required=True)
    args = parser.parse_args()
    try:
        return _report() if args.command == "report" else _show()
    except OperationalError as exc:
        print(
            f"can't reach the database: run `make db-up` (and `make sim`, "
            f"`SIM_SEED=1 make sim`).\n{exc.orig}",
            file=sys.stderr,
        )
        return 1


def _report() -> int:
    problems = load_all()
    known = known_ai_answers(problems)
    declared = {p.id: p.difficulty.value for p in problems}
    classes = [_class_data(seed, known, declared) for seed in SEEDS]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(classes), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


def _class_data(seed: int, known, declared: dict[str, str]) -> ClassData:
    url = sim_database_url(seed)
    if "sim" not in database_name(url):
        raise SystemExit(f"refusing: {database_name(url)!r} is not a sim database")
    cohort = REPO / "lab" / "sim" / f"cohort-s{seed}.jsonl"
    meta = json.loads(cohort.with_suffix(".meta.json").read_text(encoding="utf-8"))
    engine = make_engine(url)
    try:
        with Session(engine) as session:
            submissions = load_submissions(session)
    finally:
        engine.dispose()
    flagged = review_ids(detect(submissions, known))
    everything = first_attempts(submissions)
    clean = first_attempts(submissions, exclude=flagged)
    return ClassData(
        seed=seed,
        database=database_name(url),
        cohort_file=str(cohort.relative_to(REPO)),
        cohort_sha256=hashlib.sha256(cohort.read_bytes()).hexdigest(),
        submissions=len(submissions),
        responses=everything.responses,
        clean=clean.responses,
        ungraded=everything.ungraded,
        excluded=clean.excluded,
        true_skill={s["name"]: s["skill"] for s in meta["students"]},
        true_difficulty=meta["difficulty"],
        declared=declared,
    )


def _show() -> int:
    engine = make_engine(database_url())
    try:
        with Session(engine) as session:
            submissions = load_submissions(session)
    finally:
        engine.dispose()
    data = first_attempts(submissions)
    if not data.responses:
        print("no graded submissions yet")
        return 0
    e = estimate(data.responses)
    print(
        f"{database_name(database_url())}: {len(data.responses)} first tries "
        f"({data.ungraded} ungraded); Rasch {'converged' if e.converged else 'DID NOT converge'} "
        f"in {e.iterations} iterations"
    )
    print("hardest problems (difficulty in logits, 0 = average):")
    for problem, value in sorted(e.rasch_difficulty.items(), key=lambda kv: (-kv[1], kv[0]))[
        :SHOWN
    ]:
        print(f"  {fixed(value, 2):>6}  {problem}")
    print("lowest skill (a signal for a teacher, never a grade):")
    for student, value in sorted(e.rasch_skill.items(), key=lambda kv: (kv[1], kv[0]))[:SHOWN]:
        print(f"  {fixed(value, 2):>6}  {student}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
