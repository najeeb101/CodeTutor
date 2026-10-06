"""Generate the simulated class, load it into its own database, compare grades with labels.

Usage:
    python scripts/sim_cohort.py generate             # → lab/sim/cohort-s0.jsonl (+ .meta.json)
    python scripts/sim_cohort.py generate --seed 1    # another class, its own file
    python scripts/sim_cohort.py reset-db             # (re)create codetutor_sim: migrate + sync
    python scripts/sim_cohort.py load                 # queue the class's submissions in it
    python scripts/sim_cohort.py summary              # after grading: grades vs labels

The rows file depends only on the problem bank, the two Week 2 result files and the config,
so it is byte-identical every time; the meta file adds the git commit and the input hashes.
`make sim` runs reset-db, load, four grading workers (Docker) and summary. The database is
$SIM_DATABASE_URL or the local `codetutor_sim`; every command that writes refuses a database
whose name lacks "sim", so fake students never reach the development database.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from codetutor.db.admin import (
    DatabaseNameError,
    DatabaseUnreachableError,
    database_name,
    migrate_to_head,
    recreate_database,
)
from codetutor.db.engine import make_engine
from codetutor.db.sync import sync_problems
from codetutor.evals.records import read_records
from codetutor.evals.run import git_state
from codetutor.problems.loader import load_all
from codetutor.settings import sim_database_url
from codetutor.sim.cohort import Cohort, generate, read_rows, write_cohort
from codetutor.sim.load import SimDatabaseNotEmptyError, graded_rows, load_rows
from codetutor.sim.load import summary as load_summary
from codetutor.sim.personas import CohortConfig
from codetutor.sim.pools import build_pools

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "lab" / "evals" / "results"
HONEST_ANSWERS = RESULTS / "qwen2.5-coder-1.5b-fp16-t0.8-n10.jsonl"  # the "students' own" code
AI_ANSWERS = RESULTS / "qwen2.5-coder-7b-q4-t0.8-n10.jsonl"  # what AI users paste
OUT_DIR = REPO / "lab" / "sim"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(cohort: Cohort) -> str:
    """A few lines to read after generating: is the class shaped as intended?"""
    rows = cohort.rows
    by_persona = Counter(row.label.persona.value for row in rows)
    passing = Counter(row.label.persona.value for row in rows if row.label.intended_pass)
    lines = [f"{len(rows)} submissions by {len(cohort.students)} students"]
    for persona, count in sorted(by_persona.items()):
        lines.append(f"  {persona:<11} {count:5} submissions, {passing[persona] / count:.0%} pass")
    sources = Counter(row.label.source_kind.value for row in rows)
    lines.append("  sources: " + ", ".join(f"{k} {v}" for k, v in sorted(sources.items())))
    copies = Counter(row.label.transform.value for row in rows if row.label.source_kind == "copy")
    lines.append("  copies: " + ", ".join(f"{k} {v}" for k, v in sorted(copies.items())))
    cheating = sum(row.label.cheating for row in rows)
    lines.append(f"  cheating rows: {cheating} ({cheating / len(rows):.1%})")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="write the cohort file")
    gen.add_argument("--seed", type=int, default=0)
    for name, text in (
        ("reset-db", "drop and re-create the sim database (migrations + problems)"),
        ("load", "queue the cohort's submissions in the sim database"),
        ("summary", "grades vs labels, after grading"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.command != "generate":
        return _database_command(args.command, OUT_DIR / f"cohort-s{args.seed}.jsonl")

    config = CohortConfig(seed=args.seed)
    problems = load_all()
    pools = build_pools(
        problems, read_records(HONEST_ANSWERS), read_records(AI_ANSWERS), config=config
    )
    cohort = generate(problems, pools, config)
    commit, dirty = git_state()
    meta = {
        "git_commit": commit,
        "git_dirty": dirty,
        "inputs": {
            path.relative_to(REPO).as_posix(): _sha256(path)
            for path in (HONEST_ANSWERS, AI_ANSWERS)
        },
        "problem_versions": {problem.id: problem.version for problem in problems},
    }
    out = OUT_DIR / f"cohort-s{args.seed}.jsonl"
    write_cohort(cohort, out, meta)
    print(summary(cohort))
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


def _database_command(command: str, cohort_path: Path) -> int:
    url = sim_database_url()
    if "sim" not in database_name(url):
        print(f"refusing: {database_name(url)!r} is not a sim database", file=sys.stderr)
        return 1
    try:
        if command == "reset-db":
            recreate_database(url, must_contain="sim")
            migrate_to_head(url)
    except (DatabaseNameError, DatabaseUnreachableError) as exc:
        print(exc, file=sys.stderr)
        return 1
    engine = make_engine(url)
    try:
        with Session(engine) as session:
            if command == "reset-db":
                report = sync_problems(session, REPO / "problems")
                session.commit()
                print(f"{database_name(url)}: migrated, {len(report.added)} problems synced")
            elif command == "load":
                rows = read_rows(cohort_path)
                count = load_rows(session, rows)
                session.commit()
                print(f"queued {count} submissions in {database_name(url)}")
            else:
                print(load_summary(graded_rows(session, read_rows(cohort_path))))
    except SimDatabaseNotEmptyError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
