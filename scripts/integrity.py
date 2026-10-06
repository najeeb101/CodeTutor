"""Run the integrity checks over a database and store the flags (Week 5 Step 2b).

Usage:
    python scripts/integrity.py run --seed 0     # the simulated class codetutor_sim
    python scripts/integrity.py run --seed 1     # the held-out class codetutor_sim_s1
    python scripts/integrity.py run --dev        # the development database

A batch job, not part of the worker (decided 2026-10-06): it reads every submission, runs the
four signals (src/codetutor/integrity/signals.py) and replaces all rows of `integrity_flags`
in one transaction, so running it again is safe. It migrates the database first (the sim
databases may be older than migration 0008). Flags are signals for a teacher, never a
punishment; no student-facing route reads them. See docs/integrity.md §2.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from codetutor.db.admin import database_name, migrate_to_head
from codetutor.db.engine import make_engine
from codetutor.integrity.known_ai import known_ai_answers
from codetutor.integrity.signals import INTEGRITY_VERSION, FlagKind, detect, needs_review
from codetutor.integrity.store import load_submissions, replace_flags
from codetutor.problems.loader import load_all
from codetutor.settings import database_url, sim_database_url


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the checks and replace the stored flags")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--seed", type=int, help="a simulated class (0: codetutor_sim)")
    which.add_argument("--dev", action="store_true", help="the development database")
    args = parser.parse_args()

    url = database_url() if args.dev else sim_database_url(args.seed)
    if not args.dev and "sim" not in database_name(url):
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


if __name__ == "__main__":
    sys.exit(main())
