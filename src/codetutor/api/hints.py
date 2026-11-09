"""Asking for hints, reading and rating them (Week 4 Step 3, docs/api.md).

The API only queues a request. The tutor worker makes the hint (tutor/jobs.py, tutor/loop.py),
because it needs the sealed problem copy (the solution for the guardrail, the teacher's hints),
and the API never reads that table.

Plain functions on a Session, like api/submissions.py. They never commit.
"""

from __future__ import annotations

from sqlalchemy import Row, func, select, update
from sqlalchemy.orm import Session

from codetutor.api.submissions import (
    WAITING_RETRY_AFTER_S,
    RateLimitedError,
    RateLimits,
    check_queue_room,
    find_limit_hit,
    get_own_submission,
    lock_user,
)
from codetutor.db.models import HintRow, JobStatus
from codetutor.tutor.jobs import enqueue_hint

# What the API reads from a hint row: never `attempts`, `settings`, `retrieved`,
# `student_code` or `last_error` (blocked attempts can contain solution code).
HINT_COLUMNS = (
    HintRow.id,
    HintRow.problem_id,
    HintRow.problem_version,
    HintRow.submission_id,
    HintRow.level,
    HintRow.question,
    HintRow.created_at,
    HintRow.job_status,
    HintRow.text,
    HintRow.source,
    HintRow.rating,
)


class HintConflictError(Exception):
    """The request can't be answered now (HTTP 409); the message says why."""


class NotFoundError(LookupError):
    """No such hint or submission for this user (HTTP 404)."""


def create_hint(
    session: Session,
    user_id: int,
    *,
    problem_id: str,
    problem_version: int,
    level: int,
    limits: RateLimits,
    question: str | None = None,
    submission_id: int | None = None,
    code: str | None = None,
) -> int:
    """Check the user's limits and the level order, then queue the request. Returns its id.

    About a submission: it must be mine, for this problem, graded, and on the version the
    student sees; the hint is about its code and results. About `code`: not graded yet.
    The user's row is locked first, like create_submission (no check-then-act race).

    Raises RateLimitedError, ServerBusyError, NotFoundError, HintConflictError, and
    enqueue_hint's errors.
    """
    lock_user(session, user_id)
    _check_limits(session, user_id, limits)
    check_queue_room(session, HintRow, limits.max_hint_queue)
    if submission_id is not None:
        code = _graded_code(session, user_id, submission_id, problem_id, problem_version)
    if code is None:
        raise ValueError("a hint request needs a submission_id or code")
    _check_level_order(session, user_id, problem_id, level)
    return enqueue_hint(
        session,
        user_id=user_id,
        problem_id=problem_id,
        level=level,
        code=code,
        expected_version=problem_version,
        question=question,
        submission_id=submission_id,
    )


def get_own_hint(session: Session, user_id: int, hint_id: int) -> Row | None:
    """The hint (HINT_COLUMNS), or None if it doesn't exist OR belongs to someone else."""
    query = select(*HINT_COLUMNS).where(HintRow.id == hint_id, HintRow.user_id == user_id)
    return session.execute(query).one_or_none()


def list_hints(
    session: Session, user_id: int, *, problem_id: str | None = None, limit: int = 20
) -> list[Row]:
    """The user's newest hints (HINT_COLUMNS), optionally for one problem."""
    query = select(*HINT_COLUMNS).where(HintRow.user_id == user_id)
    if problem_id is not None:
        query = query.where(HintRow.problem_id == problem_id)
    query = query.order_by(HintRow.created_at.desc(), HintRow.id.desc()).limit(limit)
    return list(session.execute(query))


def rate_hint(session: Session, user_id: int, hint_id: int, rating: int) -> Row:
    """Save 👍 (1) or 👎 (-1); a new rating replaces the old one. Returns the hint.

    Raises NotFoundError (not mine), HintConflictError (not finished yet).
    """
    updated = session.execute(
        update(HintRow)
        .where(
            HintRow.id == hint_id,
            HintRow.user_id == user_id,
            HintRow.job_status == JobStatus.DONE.value,
        )
        .values(rating=rating, rated_at=func.now())
        .returning(*HINT_COLUMNS)
    ).one_or_none()
    if updated is not None:
        return updated
    if get_own_hint(session, user_id, hint_id) is None:
        raise NotFoundError(f"no hint {hint_id}")
    raise HintConflictError("this hint is not ready yet; rate it when you can read it")


def _check_limits(session: Session, user_id: int, limits: RateLimits) -> None:
    hit = find_limit_hit(
        session,
        HintRow,
        user_id,
        max_waiting=limits.hint_max_waiting,
        per_window=limits.hints_per_window,
        window_s=limits.hint_window_s,
        waiting_retry_after_s=WAITING_RETRY_AFTER_S,
    )
    if hit is None:
        return
    if hit.kind == "waiting":
        message = "the tutor is still answering your last request; wait for it first"
    else:
        minutes = limits.hint_window_s / 60
        message = f"too many hints: at most {limits.hints_per_window} per {minutes:g} minutes"
    raise RateLimitedError(message, hit.retry_after_s)


def _graded_code(
    session: Session, user_id: int, submission_id: int, problem_id: str, problem_version: int
) -> str:
    """The code of my graded submission for this problem version (see create_hint)."""
    submission = get_own_submission(session, user_id, submission_id)
    if submission is None or submission.problem_id != problem_id:
        raise NotFoundError(f"no submission {submission_id} for {problem_id}")
    if submission.job_status != JobStatus.DONE.value:
        raise HintConflictError("this submission is not graded yet; wait for its result, then ask")
    if submission.problem_version != problem_version:
        raise HintConflictError(
            f"submission {submission_id} was graded on an older version of this problem; "
            "submit again, then ask"
        )
    return submission.code


def _check_level_order(session: Session, user_id: int, problem_id: str, level: int) -> None:
    """Level L needs a finished hint of level L-1 or higher for this problem first."""
    if level == 1:
        return
    earlier = session.scalar(
        select(func.max(HintRow.level)).where(
            HintRow.user_id == user_id,
            HintRow.problem_id == problem_id,
            HintRow.job_status == JobStatus.DONE.value,
        )
    )
    if earlier is None or earlier < level - 1:
        raise HintConflictError(f"ask for a level {level - 1} hint first")
