"""Put the simulated class into a database, and compare its grades with the labels (Step 1b).

Loading uses the same door as a real submit (`enqueue_submission`: problem and version checks,
code checks), plus the simulated time. Only what a real submission has goes in: user, problem,
code, time, editor summary. The labels stay in the cohort file, so the detectors of Step 2 can
never read them; `graded_rows` joins them back by (student, problem, time), which the
generator makes unique.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from codetutor.db.models import SubmissionRow, UserRow
from codetutor.db.users import get_or_create_user
from codetutor.sim.cohort import CohortRow
from codetutor.worker.jobs import enqueue_submission


class SimDatabaseNotEmptyError(RuntimeError):
    """The database already has submissions (loading twice would double the class)."""


def load_rows(session: Session, rows: Sequence[CohortRow]) -> int:
    """Queue every row as a submission at its simulated time. Returns how many. Does not commit.

    Users get the time of their first submission as `created_at`, so a later report never
    sees students who "signed up" a month after they started.
    """
    existing = session.scalar(select(func.count()).select_from(SubmissionRow))
    if existing:
        raise SimDatabaseNotEmptyError(
            f"the database already has {existing} submissions: run `make sim-db` first"
        )
    users: dict[str, int] = {}
    for row in sorted(rows, key=lambda r: (r.created_at, r.key)):
        if row.student not in users:
            users[row.student] = get_or_create_user(session, row.student)
        enqueue_submission(
            session,
            users[row.student],
            row.problem_id,
            row.code,
            expected_version=row.problem_version,
            editor_stats=row.editor_stats,
            created_at=row.created_at,
        )
    session.execute(
        text(
            "UPDATE users SET created_at = first.at FROM "
            "(SELECT user_id, min(created_at) AS at FROM submissions GROUP BY user_id) AS first "
            "WHERE users.id = first.user_id"
        )
    )
    return len(rows)


@dataclass(frozen=True)
class GradedRow:
    """A cohort row with what the database says about it."""

    row: CohortRow
    submission_id: int
    job_status: str
    result_status: str | None  # None until graded


def graded_rows(session: Session, rows: Sequence[CohortRow]) -> list[GradedRow]:
    """Every cohort row with its submission's job and result status (joined by label key)."""
    found = session.execute(
        select(
            UserRow.name,
            SubmissionRow.problem_id,
            SubmissionRow.created_at,
            SubmissionRow.id,
            SubmissionRow.job_status,
            SubmissionRow.result_status,
        ).join(UserRow, UserRow.id == SubmissionRow.user_id)
    ).all()
    by_key: dict[tuple[str, str, datetime], tuple[int, str, str | None]] = {
        (name, problem_id, at): (sid, job, result)
        for name, problem_id, at, sid, job, result in found
    }
    graded = []
    for row in rows:
        sid, job, result = by_key[(row.student, row.problem_id, row.created_at)]
        graded.append(GradedRow(row, sid, job, result))
    return graded


def summary(graded: Sequence[GradedRow]) -> str:
    """Accepted share per persona, and whether the grades agree with the labels."""
    statuses = Counter(g.result_status or g.job_status for g in graded)
    lines = [
        f"{len(graded)} submissions: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items()))
    ]
    by_persona: dict[str, list[GradedRow]] = defaultdict(list)
    for g in graded:
        by_persona[g.row.label.persona.value].append(g)
    for persona, items in sorted(by_persona.items()):
        accepted = sum(g.result_status == "accepted" for g in items)
        lines.append(f"  {persona:<11} {accepted / len(items):6.1%} accepted of {len(items)}")
    done = [g for g in graded if g.result_status is not None]
    disagree = [g for g in done if (g.result_status == "accepted") != g.row.label.intended_pass]
    lines.append(f"  grade = label (intended pass) for {len(done) - len(disagree)} of {len(done)}")
    for g in disagree[:10]:
        lines.append(
            f"    #{g.submission_id} {g.row.key}: label pass={g.row.label.intended_pass}, "
            f"graded {g.result_status} ({g.row.label.source_kind.value} "
            f"{g.row.label.source_ref}, {g.row.label.transform.value})"
        )
    return "\n".join(lines)
