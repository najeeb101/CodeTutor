"""The grading queue in Postgres: the submission row is the job (docs/worker.md).

A job moves queued -> running -> done (or back to queued after an error, or failed after
MAX_ATTEMPTS). A worker claims the oldest job with SELECT ... FOR UPDATE SKIP LOCKED and gets
a lease. `attempts` is the fencing token: a save only counts while the row still has the
attempts number of our claim.

Every function takes a Session and never commits: the caller decides where each transaction
ends (worker/loop.py: claim, grade, save are three separate steps).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from codetutor.db.models import JobStatus, ProblemRow, SubmissionRow, TestResultRow
from codetutor.grader.models import GradeResult, GradeStatus, TestResult

# How long a claimed job belongs to its worker. The slowest bank problem needs ~38 s in
# Docker; a test keeps every problem's worst case under half of this. If a worker dies, its job
# waits this long before another worker takes it.
LEASE_S = 300.0
MAX_ATTEMPTS = 3  # claims per job; after that it is `failed`
MAX_CODE_CHARS = 50_000  # a CS1 solution is a few hundred characters
MAX_ERROR_CHARS = 2_000  # `last_error` is cut to this length
# Postgres text can't hold NUL (\x00). It becomes U+FFFD, the character Python already uses
# for bytes it can't decode.
NUL_REPLACEMENT = "�"

# The oldest claimable job: queued, or running with an expired lease (its worker died).
# SKIP LOCKED: a row that another worker is claiming right now is skipped, not waited for, so
# two workers never get the same job and never block each other.
CLAIM_SQL = text("""
UPDATE submissions
SET job_status = 'running',
    attempts = attempts + 1,
    started_at = now(),
    lease_expires_at = now() + make_interval(secs => :lease_s)
WHERE id = (
    SELECT id FROM submissions
    WHERE (job_status = 'queued' OR (job_status = 'running' AND lease_expires_at < now()))
      AND attempts < :max_attempts
    ORDER BY id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id, attempts, problem_id, problem_version, code
""")

# Jobs whose worker died on the last allowed attempt: nobody may claim them again.
FAIL_ABANDONED_SQL = text("""
UPDATE submissions
SET job_status = 'failed',
    finished_at = now(),
    lease_expires_at = NULL,
    last_error = 'lease expired on attempt ' || attempts || ' (the worker stopped or hung)'
WHERE job_status = 'running' AND lease_expires_at < now() AND attempts >= :max_attempts
""")


class InvalidSubmissionError(ValueError):
    """The submitted code can't be accepted (too long, or not storable text)."""


class UnknownProblemError(LookupError):
    """No active problem has this id."""


class ProblemChangedError(ValueError):
    """The problem has a newer version than the one the student saw (a sync ran meanwhile)."""

    def __init__(self, problem_id: str, expected: int, current: int) -> None:
        super().__init__(f"{problem_id} is now version {current}, not {expected}")
        self.current_version = current


@dataclass(frozen=True)
class Job:
    """A claimed submission. `attempts` is the fencing token of this claim."""

    id: int
    attempts: int
    problem_id: str
    problem_version: int
    code: str


def clean_text(value: str | None) -> str | None:
    """Make text storable in Postgres: replace NUL characters."""
    return None if value is None else value.replace("\x00", NUL_REPLACEMENT)


def _check_code(code: str) -> None:
    if len(code) > MAX_CODE_CHARS:
        raise InvalidSubmissionError(
            f"code is too long ({len(code)} > {MAX_CODE_CHARS} characters)"
        )
    if "\x00" in code:
        raise InvalidSubmissionError("code must not contain the NUL character")
    try:
        code.encode("utf-8")
    except UnicodeEncodeError as exc:  # e.g. a lone surrogate like "\ud800"
        raise InvalidSubmissionError("code contains characters that are not valid text") from exc


def enqueue_submission(
    session: Session,
    user_id: int,
    problem_id: str,
    code: str,
    *,
    expected_version: int | None = None,
) -> int:
    """Save a new submission as a queued job, graded on the problem's current version.

    `expected_version`: the version the student saw (the API sends it). If the current version
    is different, nothing is saved (ProblemChangedError), so code is never graded against a
    problem the student didn't see. Returns the submission id. Saving the row IS enqueueing:
    one insert, no second system.
    """
    _check_code(code)
    problem = session.get(ProblemRow, problem_id)
    if problem is None or not problem.active:
        raise UnknownProblemError(f"no active problem {problem_id!r}")
    if expected_version is not None and expected_version != problem.version:
        raise ProblemChangedError(problem_id, expected_version, problem.version)
    submission = SubmissionRow(
        user_id=user_id, problem_id=problem_id, problem_version=problem.version, code=code
    )
    session.add(submission)
    session.flush()  # assigns the id
    return submission.id


def claim_next_job(session: Session, *, lease_s: float = LEASE_S) -> Job | None:
    """Claim the oldest claimable job (running, attempts + 1, leased). None if there is none.

    Commit right after this, so the claim is visible to other workers before grading starts.
    """
    session.execute(FAIL_ABANDONED_SQL, {"max_attempts": MAX_ATTEMPTS})
    row = session.execute(
        CLAIM_SQL, {"lease_s": lease_s, "max_attempts": MAX_ATTEMPTS}
    ).one_or_none()
    if row is None:
        return None
    return Job(
        id=row.id,
        attempts=row.attempts,
        problem_id=row.problem_id,
        problem_version=row.problem_version,
        code=row.code,
    )


def _still_ours(job: Job) -> tuple[Any, ...]:
    """WHERE conditions that are true only while our claim is the latest one (fencing)."""
    return (
        SubmissionRow.id == job.id,
        SubmissionRow.attempts == job.attempts,
        SubmissionRow.job_status == JobStatus.RUNNING.value,
    )


def _test_row(submission_id: int, position: int, test: TestResult) -> TestResultRow:
    """One test_results row. Unrevealed tests leave input/expected/actual unset (SQL NULL);
    setting them to None would store JSON null, which the table's CHECK rejects."""
    values: dict[str, Any] = {
        "submission_id": submission_id,
        "test_id": test.test_id,
        "position": position,
        "hidden": test.hidden,
        "revealed": test.revealed,
        "status": test.status.value,
        "error": clean_text(test.error),
        "duration_ms": test.duration_ms,
    }
    if test.revealed:
        values |= {"input": test.input, "expected": test.expected, "actual": test.actual}
    return TestResultRow(**values)


def save_result(session: Session, job: Job, result: GradeResult) -> bool:
    """Store the result and its tests. False (nothing written) if the job is no longer ours."""
    if (result.problem_id, result.problem_version) != (job.problem_id, job.problem_version):
        raise ValueError(
            f"result is for {result.problem_id} v{result.problem_version}, not job {job.id}"
        )
    updated = session.execute(
        update(SubmissionRow)
        .where(*_still_ours(job))
        .values(
            job_status=JobStatus.DONE.value,
            finished_at=func.now(),
            lease_expires_at=None,
            result_status=result.status.value,
            passed=result.passed,
            total=result.total,
            reward=result.reward,
            compile_error=clean_text(result.compile_error),
            error=clean_text(result.error),
            stdout=clean_text(result.stdout),
            duration_ms=result.duration_ms,
            grader_version=result.grader_version,
        )
    ).rowcount
    if updated == 0:
        return False  # our lease expired and another worker claimed the job
    session.add_all(_test_row(job.id, position, test) for position, test in enumerate(result.tests))
    session.flush()
    return True


def release_job(session: Session, job: Job, error: str) -> JobStatus | None:
    """Give a job back after an error: queued again, or failed on the last attempt.

    Returns the new status, or None if the job is no longer ours (nothing written).
    """
    status = JobStatus.FAILED if job.attempts >= MAX_ATTEMPTS else JobStatus.QUEUED
    updated = session.execute(
        update(SubmissionRow)
        .where(*_still_ours(job))
        .values(
            job_status=status.value,
            last_error=clean_text(error)[:MAX_ERROR_CHARS],
            lease_expires_at=None,
            finished_at=func.now() if status is JobStatus.FAILED else None,
        )
    ).rowcount
    return status if updated else None


def load_grade_result(session: Session, submission_id: int) -> GradeResult | None:
    """Rebuild the saved GradeResult of a submission. None until it is done."""
    submission = session.get(SubmissionRow, submission_id)
    if submission is None or submission.result_status is None:
        return None
    rows = session.scalars(
        select(TestResultRow)
        .where(TestResultRow.submission_id == submission_id)
        .order_by(TestResultRow.position)
    )
    tests = [
        TestResult(
            test_id=row.test_id,
            hidden=row.hidden,
            status=row.status,
            error=row.error,
            revealed=row.revealed,
            input=row.input,
            expected=row.expected,
            actual=row.actual,
            duration_ms=row.duration_ms,
        )
        for row in rows
    ]
    return GradeResult(
        problem_id=submission.problem_id,
        problem_version=submission.problem_version,
        status=GradeStatus(submission.result_status),
        passed=submission.passed,
        total=submission.total,
        reward=submission.reward,
        tests=tests,
        compile_error=submission.compile_error,
        error=submission.error,
        stdout=submission.stdout,
        duration_ms=submission.duration_ms,
        grader_version=submission.grader_version,
    )
