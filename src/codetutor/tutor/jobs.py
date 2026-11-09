"""The tutor's queue in Postgres: the hints row is the job (Week 4 Step 3, docs/tutor.md §4).

The same design as grading (worker/jobs.py, docs/worker.md): a job moves queued -> running ->
done, or back to queued after an error of ours, or to failed after MAX_ATTEMPTS claims. The
tutor worker claims the oldest job with SELECT ... FOR UPDATE SKIP LOCKED and gets a lease;
`claims` is the fencing token (in `submissions` it is called `attempts`, but in `hints` that
name holds the model's replies).

Why a worker and not the API: a hint needs the sealed problem copy (the solution for the
guardrail, the teacher's hints), and the API never reads that table.

Every function takes a Session and never commits: the caller decides where transactions end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session

from codetutor.db.models import HintRow, JobStatus
from codetutor.tutor.context import LEVELS
from codetutor.tutor.service import HintResult, result_columns
from codetutor.worker.jobs import (
    MAX_ATTEMPTS,
    MAX_ERROR_CHARS,
    check_code,
    clean_text,
    current_problem_version,
)

# A claimed hint belongs to its worker this long. A hint makes at most 2 model calls; loading
# the model after a reboot took 109 s (2026-10-05), a warm hint 1-5 s.
LEASE_S = 300.0
MAX_QUESTION_CHARS = 500
MAX_EARLIER_HINTS = 3  # the newest hints already shown for the same code go into the prompt

# The oldest claimable hint job (same rules as worker/jobs.py CLAIM_SQL).
CLAIM_SQL = text("""
UPDATE hints
SET job_status = 'running',
    claims = claims + 1,
    started_at = now(),
    lease_expires_at = now() + make_interval(secs => :lease_s)
WHERE id = (
    SELECT id FROM hints
    WHERE (job_status = 'queued' OR (job_status = 'running' AND lease_expires_at < now()))
      AND claims < :max_attempts
    ORDER BY id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, claims, user_id, problem_id, problem_version, submission_id, level, question,
          student_code
""")

# Hint jobs whose worker died on the last allowed claim: nobody may claim them again.
FAIL_ABANDONED_SQL = text("""
UPDATE hints
SET job_status = 'failed',
    finished_at = now(),
    lease_expires_at = NULL,
    last_error = 'lease expired on claim ' || claims || ' (the tutor worker stopped or hung)'
WHERE job_status = 'running' AND lease_expires_at < now() AND claims >= :max_attempts
""")


@dataclass(frozen=True)
class HintJob:
    """A claimed hint request. `claims` is the fencing token of this claim."""

    id: int
    claims: int
    user_id: int | None
    problem_id: str
    problem_version: int
    submission_id: int | None
    level: int
    question: str | None
    code: str


def enqueue_hint(
    session: Session,
    *,
    user_id: int,
    problem_id: str,
    level: int,
    code: str,
    expected_version: int | None = None,
    question: str | None = None,
    submission_id: int | None = None,
) -> int:
    """Save a new hint request as a queued job, on the problem's current version.

    The caller has checked everything about the user (limits, level order, that the
    submission is theirs and graded on this version). Raises InvalidSubmissionError (bad code),
    UnknownProblemError, ProblemChangedError, or ValueError (bad level or question).
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, not {level}")
    check_code(code)
    if question is not None and (len(question) > MAX_QUESTION_CHARS or "\x00" in question):
        raise ValueError(f"a question has at most {MAX_QUESTION_CHARS} characters and no NUL")
    version = current_problem_version(session, problem_id, expected_version)
    # A plain INSERT that sends back only the id: an ORM insert would also ask for the server
    # defaults (`claims`, ...), columns the API's database role may not read (db/roles.py).
    return session.scalar(
        insert(HintRow)
        .values(
            user_id=user_id,
            problem_id=problem_id,
            problem_version=version,
            submission_id=submission_id,
            level=level,
            question=question,
            student_code=code,
        )
        .returning(HintRow.id)
    )


def claim_next_hint(session: Session, *, lease_s: float = LEASE_S) -> HintJob | None:
    """Claim the oldest claimable hint job. None if there is none. Commit right after this."""
    session.execute(FAIL_ABANDONED_SQL, {"max_attempts": MAX_ATTEMPTS})
    row = session.execute(
        CLAIM_SQL, {"lease_s": lease_s, "max_attempts": MAX_ATTEMPTS}
    ).one_or_none()
    if row is None:
        return None
    return HintJob(
        id=row.id,
        claims=row.claims,
        user_id=row.user_id,
        problem_id=row.problem_id,
        problem_version=row.problem_version,
        submission_id=row.submission_id,
        level=row.level,
        question=row.question,
        code=row.student_code,
    )


def earlier_hints(session: Session, job: HintJob) -> tuple[str, ...]:
    """The newest finished hints this user already got for the same code, oldest first.

    The prompt says "don't repeat them", so asking twice gives a new hint.
    """
    if job.user_id is None:
        return ()
    texts = session.scalars(
        select(HintRow.text)
        .where(
            HintRow.user_id == job.user_id,
            HintRow.problem_id == job.problem_id,
            HintRow.student_code == job.code,
            HintRow.job_status == JobStatus.DONE.value,
            HintRow.id < job.id,
        )
        .order_by(HintRow.id.desc())
        .limit(MAX_EARLIER_HINTS)
    )
    return tuple(reversed([text for text in texts if text is not None]))


def _still_ours(job: HintJob) -> tuple[Any, ...]:
    """WHERE conditions that are true only while our claim is the latest one (fencing)."""
    return (
        HintRow.id == job.id,
        HintRow.claims == job.claims,
        HintRow.job_status == JobStatus.RUNNING.value,
    )


def save_hint_result(session: Session, job: HintJob, result: HintResult) -> bool:
    """Store the hint and its trace. False (nothing written) if the job is no longer ours."""
    if result.level != job.level:
        raise ValueError(f"the hint is level {result.level}, job {job.id} asked for {job.level}")
    updated = session.execute(
        update(HintRow)
        .where(*_still_ours(job))
        .values(
            job_status=JobStatus.DONE.value,
            finished_at=func.now(),
            lease_expires_at=None,
            **result_columns(result),
        )
    ).rowcount
    return updated > 0


def release_hint(session: Session, job: HintJob, error: str) -> JobStatus | None:
    """Give a job back after an error: queued again, or failed on the last claim.

    Returns the new status, or None if the job is no longer ours (nothing written).
    """
    status = JobStatus.FAILED if job.claims >= MAX_ATTEMPTS else JobStatus.QUEUED
    updated = session.execute(
        update(HintRow)
        .where(*_still_ours(job))
        .values(
            job_status=status.value,
            last_error=clean_text(error)[:MAX_ERROR_CHARS],
            lease_expires_at=None,
            finished_at=func.now() if status is JobStatus.FAILED else None,
        )
    ).rowcount
    return status if updated else None
