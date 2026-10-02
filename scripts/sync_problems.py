"""Copy the problem folders into Postgres (problem_versions + problems). Safe to run again.

Usage:
    python scripts/sync_problems.py                  # the bank, into $DATABASE_URL or the dev DB
    python scripts/sync_problems.py --root path/to/problems

Run `make db-migrate` first (`make db-sync` does both).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.db.sync import SyncError, sync_problems
from codetutor.problems import ProblemError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="problems folder")
    args = parser.parse_args()

    engine = make_engine()
    # hide_password: a real DATABASE_URL contains one.
    where = engine.url.render_as_string(hide_password=True)
    try:
        with Session(engine) as session, session.begin():  # commits only if no error
            report = sync_problems(session, args.root)
    except (SyncError, ProblemError) as exc:
        print(f"❌ {exc}")
        return 1
    except OperationalError as exc:
        print(f"❌ cannot reach Postgres at {where}. Run `make db-up`.\n   {exc.orig}")
        return 1
    except ProgrammingError as exc:
        print(f"❌ database error (is it migrated? run `make db-migrate`):\n   {exc.orig}")
        return 1
    finally:
        engine.dispose()

    total = len(report.added) + len(report.updated) + len(report.restored) + len(report.unchanged)
    print(f"✅ {total} problems in sync with {where}")
    print(
        f"   added {len(report.added)}, updated {len(report.updated)}, "
        f"restored {len(report.restored)}, unchanged {len(report.unchanged)}, "
        f"retired {len(report.retired)}"
    )
    for line in report.updated:
        print(f"   updated  {line}")
    for problem_id in report.restored:
        print(f"   restored {problem_id}")
    for problem_id in report.retired:
        print(f"   retired  {problem_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
