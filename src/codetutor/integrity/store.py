"""The integrity checks' database side (Week 5 Step 2b): read submissions, write flags.

The functions take a Session and never commit: the caller commits once, so deleting the old
flags and inserting the new ones happen together or not at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from codetutor.db.models import IntegrityFlagRow, ProblemRow, SubmissionRow, UserRow
from codetutor.integrity.signals import INTEGRITY_VERSION, Flag, SubmissionInfo


def load_submissions(session: Session) -> list[SubmissionInfo]:
    """Every submission with what the checks may know about it, oldest first.

    The function name comes from the `problems` row (the student view): all versions of a
    problem keep the function's name.
    """
    function_names = {
        problem_id: view["function_name"]
        for problem_id, view in session.execute(select(ProblemRow.id, ProblemRow.student_view))
    }
    found = session.execute(
        select(
            SubmissionRow.id,
            UserRow.name,
            SubmissionRow.problem_id,
            SubmissionRow.created_at,
            SubmissionRow.code,
            SubmissionRow.editor_stats,
            SubmissionRow.result_status,
        )
        .join(UserRow, UserRow.id == SubmissionRow.user_id)
        .order_by(SubmissionRow.created_at, SubmissionRow.id)
    ).all()
    return [
        SubmissionInfo(
            id=sid,
            student=name,
            problem_id=problem_id,
            function_name=function_names[problem_id],
            created_at=created_at,
            code=code,
            editor_stats=editor_stats,
            result_status=result_status,
        )
        for sid, name, problem_id, created_at, code, editor_stats, result_status in found
    ]


def replace_flags(session: Session, flags: Sequence[Flag]) -> int:
    """Delete every stored flag, then store `flags`. Returns how many. Does not commit."""
    session.execute(delete(IntegrityFlagRow))
    if flags:
        session.execute(
            insert(IntegrityFlagRow),
            [
                {
                    "submission_id": flag.submission_id,
                    "kind": flag.kind.value,
                    "value": flag.value,
                    "reason": flag.reason,
                    "details": flag.details,
                    "detector_version": INTEGRITY_VERSION,
                }
                for flag in flags
            ],
        )
    return len(flags)
