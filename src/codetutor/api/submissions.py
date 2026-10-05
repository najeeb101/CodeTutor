"""Submitting and reading submissions: the rate limits, then the queue (docs/api.md).

Plain functions on a Session, without FastAPI, so tests can call them directly (also from many
threads at once). They never commit: the route decides where the transaction ends.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from codetutor.db.models import HintRow, JobStatus, SubmissionRow, UserRow
from codetutor.worker.jobs import enqueue_submission

WAITING = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
# Retry-After when the user has too many waiting submissions: one grading takes ~1 s in Docker.
# (A warm hint takes 1-5 s, so the same 2 s fits hints.)
WAITING_RETRY_AFTER_S = 2
# What "my submissions" returns per row. Not `code` or `stdout` (up to 64 KB each): a list of
# 100 rows stays small. The full row is only read for one submission.
SUMMARY_COLUMNS = (
    SubmissionRow.id,
    SubmissionRow.problem_id,
    SubmissionRow.problem_version,
    SubmissionRow.created_at,
    SubmissionRow.job_status,
    SubmissionRow.result_status,
    SubmissionRow.passed,
    SubmissionRow.total,
    SubmissionRow.reward,
)


@dataclass(frozen=True)
class RateLimits:
    """How much one user may submit and ask. All API limits live here; tests pass smaller ones."""

    per_window: int = 10  # at most this many submissions ...
    window_s: float = 60.0  # ... in any this-many-seconds window (a sliding window)
    # Queued or running at the same time. Fairness: one user can't fill the queue, so other
    # students never wait behind 100 jobs of one person.
    max_waiting: int = 3
    # Hints (Week 4): each one uses the GPU for 1-5 s, so one at a time per user.
    hint_max_waiting: int = 1
    hints_per_window: int = 10
    hint_window_s: float = 600.0


class RateLimitedError(Exception):
    """The user must wait `retry_after_s` seconds before submitting again."""

    def __init__(self, message: str, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class LimitHit:
    """Which limit a request hit, and when the user may try again."""

    kind: Literal["waiting", "window"]
    count: int  # waiting jobs, or requests in the window
    retry_after_s: int


def find_limit_hit(
    session: Session,
    table: type[SubmissionRow] | type[HintRow],
    user_id: int,
    *,
    max_waiting: int,
    per_window: int,
    window_s: float,
    waiting_retry_after_s: int,
) -> LimitHit | None:
    """The first limit this user's next request would break, or None (submissions and hints).

    Counts the user's rows in `table`: queued or running ones, and all from the last
    `window_s` seconds (a sliding window). Call it with the user's row locked (see
    create_submission).
    """
    waiting = session.scalar(
        select(func.count())
        .select_from(table)
        .where(table.user_id == user_id, table.job_status.in_(WAITING))
    )
    if waiting >= max_waiting:
        return LimitHit("waiting", waiting, waiting_retry_after_s)

    window = timedelta(seconds=window_s)
    recent, oldest, now = session.execute(
        select(func.count(), func.min(table.created_at), func.now()).where(
            table.user_id == user_id, table.created_at > func.now() - window
        )
    ).one()
    if recent >= per_window:
        # The user may ask again when the oldest request in the window leaves it.
        wait_s = (oldest + window - now).total_seconds()
        return LimitHit("window", recent, max(1, math.ceil(wait_s)))
    return None


def _check_limits(session: Session, user_id: int, limits: RateLimits) -> None:
    """Raise RateLimitedError if the user may not submit now."""
    hit = find_limit_hit(
        session,
        SubmissionRow,
        user_id,
        max_waiting=limits.max_waiting,
        per_window=limits.per_window,
        window_s=limits.window_s,
        waiting_retry_after_s=WAITING_RETRY_AFTER_S,
    )
    if hit is None:
        return
    if hit.kind == "waiting":
        message = (
            f"you already have {hit.count} submissions waiting to be graded; "
            "wait for their results first"
        )
    else:
        message = f"too many submissions: at most {limits.per_window} per {limits.window_s:g} s"
    raise RateLimitedError(message, hit.retry_after_s)


def lock_user(session: Session, user_id: int) -> None:
    """Lock the user's row until the transaction ends (SELECT ... FOR UPDATE).

    Requests of the same user that count their limits then run one after the other; other
    users never wait.
    """
    session.execute(select(UserRow.id).where(UserRow.id == user_id).with_for_update())


def create_submission(
    session: Session,
    user_id: int,
    problem_id: str,
    problem_version: int,
    code: str,
    limits: RateLimits,
) -> int:
    """Check the user's limits, then queue the submission. Returns its id. Does not commit.

    The user's row is locked first (SELECT ... FOR UPDATE, held until the caller commits or
    rolls back), so two submits of one user at the same moment are counted one after the
    other. Without the lock, both could count 9 of 10 and both insert: a check-then-act race.
    Other users' submits never wait for this lock.

    Raises RateLimitedError, and enqueue_submission's errors (UnknownProblemError,
    ProblemChangedError, InvalidSubmissionError).
    """
    lock_user(session, user_id)
    _check_limits(session, user_id, limits)
    return enqueue_submission(session, user_id, problem_id, code, expected_version=problem_version)


def get_own_submission(session: Session, user_id: int, submission_id: int) -> SubmissionRow | None:
    """The submission, or None if it doesn't exist OR belongs to someone else.

    Both cases look the same on purpose: the API answers 404 for both, so nobody can find out
    which submission ids exist.
    """
    submission = session.get(SubmissionRow, submission_id)
    if submission is None or submission.user_id != user_id:
        return None
    return submission


def list_submissions(
    session: Session, user_id: int, *, problem_id: str | None = None, limit: int = 20
) -> list[Row]:
    """The user's newest submissions (SUMMARY_COLUMNS only), optionally for one problem."""
    query = select(*SUMMARY_COLUMNS).where(SubmissionRow.user_id == user_id)
    if problem_id is not None:
        query = query.where(SubmissionRow.problem_id == problem_id)
    query = query.order_by(SubmissionRow.created_at.desc(), SubmissionRow.id.desc()).limit(limit)
    return list(session.execute(query))
