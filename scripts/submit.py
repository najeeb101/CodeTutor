"""Submit a Python file for grading through the queue (a dev tool until the API exists).

Usage:
    python scripts/submit.py cs1.loops.fizzbuzz my_fizzbuzz.py            # queue it
    python scripts/submit.py cs1.loops.fizzbuzz my_fizzbuzz.py --wait     # and show the result

A worker must be running to grade it (`make worker`). The user is created if needed
(name only, like the Week 3 dev login: not secure).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.db.models import JobStatus, SubmissionRow, UserRow
from codetutor.worker.jobs import (
    InvalidSubmissionError,
    UnknownProblemError,
    enqueue_submission,
    load_grade_result,
)
from grade_cli import format_result  # same folder: print results like the grade CLI

POLL_S = 0.5


def _user_id(session: Session, name: str) -> int:
    """The id of the user with this name, created if new."""
    session.execute(insert(UserRow).values(name=name).on_conflict_do_nothing())
    return session.scalars(select(UserRow.id).where(UserRow.name == name)).one()


def _wait(session: Session, submission_id: int, timeout_s: float) -> int:
    """Poll until the job is done or failed; print the result. Returns the exit code."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        submission = session.get(SubmissionRow, submission_id)
        if submission.job_status == JobStatus.DONE:
            print(format_result(load_grade_result(session, submission_id)))
            return 0
        if submission.job_status == JobStatus.FAILED:
            print(
                f"❌ grading failed after {submission.attempts} attempts: {submission.last_error}"
            )
            return 1
        # End the read transaction while we sleep (never hold one open), and forget the
        # loaded row, so the next poll reads it again from the database.
        session.rollback()
        time.sleep(POLL_S)
    print(f"⏳ still not graded after {timeout_s:g} s. Is a worker running? (make worker)")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("problem_id", help="e.g. cs1.loops.fizzbuzz")
    parser.add_argument("file", type=Path, help="the Python file to submit")
    parser.add_argument("--user", default="dev", help="user name (default: dev)")
    parser.add_argument("--wait", action="store_true", help="wait for the result and print it")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait (120)")
    args = parser.parse_args()

    engine = make_engine()
    try:
        with Session(engine) as session:
            with session.begin():
                user_id = _user_id(session, args.user)
                code = args.file.read_text(encoding="utf-8")
                submission_id = enqueue_submission(session, user_id, args.problem_id, code)
            print(f"submission {submission_id} queued ({args.problem_id}, user {args.user!r})")
            return _wait(session, submission_id, args.timeout) if args.wait else 0
    except (InvalidSubmissionError, UnknownProblemError, OSError) as exc:
        print(f"❌ {exc}")
        return 1
    except OperationalError as exc:
        print(f"❌ cannot reach Postgres. Run `make db-up`. ({exc.orig})")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
