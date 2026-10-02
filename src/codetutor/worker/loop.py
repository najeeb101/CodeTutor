"""The worker loop: claim a job, grade it, save the result (docs/worker.md).

Each job uses three steps, and never keeps a transaction open while grading:
  1. claim (one short transaction, committed at once, so other workers see it),
  2. grade with the one grader (no transaction; 1-38 s),
  3. save the result and its test rows (one short transaction: all or nothing).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from codetutor.db.models import JobStatus, ProblemVersionRow
from codetutor.grader import grade
from codetutor.grader.sandbox import Sandbox
from codetutor.problems import Problem
from codetutor.worker.jobs import LEASE_S, Job, claim_next_job, release_job, save_result

POLL_INTERVAL_S = 1.0  # how often an idle worker looks for new jobs
ERROR_PAUSE_S = 2.0  # wait after a failed job, so a broken setup doesn't spin
MAX_ERRORS_IN_A_ROW = 5  # then the worker stops: something is wrong with the setup, not a job

log = logging.getLogger(__name__)

# Sealed problem copies by (id, version). Safe to keep forever: a stored copy never changes.
ProblemCache = dict[tuple[str, int], Problem]


class Outcome(StrEnum):
    """What happened to one claimed job."""

    DONE = "done"  # graded and saved
    RETRY = "retry"  # an error on our side; queued again
    FAILED = "failed"  # an error on the last attempt
    LOST = "lost"  # our lease expired and another worker took the job; nothing saved


class WorkerStoppedError(RuntimeError):
    """Too many jobs in a row failed: the setup is broken (e.g. Docker or the database)."""


@dataclass
class WorkerStats:
    """Counts of job outcomes in one run of the worker."""

    done: int = 0
    retry: int = 0
    failed: int = 0
    lost: int = 0

    def add(self, outcome: Outcome) -> None:
        setattr(self, outcome.value, getattr(self, outcome.value) + 1)


def _load_problem(session: Session, job: Job, cache: ProblemCache) -> Problem:
    """The sealed copy of the version the student saw (from the database, not the files)."""
    key = (job.problem_id, job.problem_version)
    if key not in cache:
        row = session.get(ProblemVersionRow, key)
        if row is None:  # impossible while the foreign key exists; checked to fail clearly
            raise LookupError(f"no stored copy of {job.problem_id} v{job.problem_version}")
        cache[key] = Problem.model_validate(row.problem)
    return cache[key]


def _release(engine: Engine, job: Job, error: str) -> Outcome:
    with Session(engine) as session, session.begin():
        status = release_job(session, job, error)
    if status is None:
        return Outcome.LOST
    return Outcome.FAILED if status is JobStatus.FAILED else Outcome.RETRY


def process_job(engine: Engine, sandbox: Sandbox, job: Job, cache: ProblemCache) -> Outcome:
    """Grade one claimed job and save the result; release the job if anything of ours fails.

    A student's broken code is not an error here: it is a normal GradeResult (compile_error,
    runtime_error, ...). Errors here are ours: a corrupt problem copy, the database, the sandbox.
    """
    try:
        with Session(engine) as session:
            problem = _load_problem(session, job, cache)
        # reveal_hidden=False: hidden test details never reach the database (docs/database.md).
        result = grade(problem, job.code, reveal_hidden=False, sandbox=sandbox)
        with Session(engine) as session, session.begin():
            saved = save_result(session, job, result)
    except Exception as exc:  # a worker must survive any single job; the error is kept
        log.exception("job %d (attempt %d) failed", job.id, job.attempts)
        outcome = _release(engine, job, f"{type(exc).__name__}: {exc}")
        log.warning("job %d: %s", job.id, outcome.value)
        return outcome

    if not saved:
        log.warning("job %d: lease lost (another worker took it); result not saved", job.id)
        return Outcome.LOST
    log.info(
        "job %d %s v%d: %s %d/%d (%.1f s)",
        job.id,
        job.problem_id,
        job.problem_version,
        result.status.value,
        result.passed,
        result.total,
        result.duration_ms / 1000,
    )
    return Outcome.DONE


def run_worker(
    engine: Engine,
    sandbox: Sandbox,
    stop: threading.Event,
    *,
    drain: bool = False,
    poll_interval_s: float = POLL_INTERVAL_S,
    error_pause_s: float = ERROR_PAUSE_S,
    lease_s: float = LEASE_S,
) -> WorkerStats:
    """Claim and grade jobs until `stop` is set (or, with drain=True, until none is left).

    The current job always finishes before stopping. Raises WorkerStoppedError after
    MAX_ERRORS_IN_A_ROW failed jobs in a row.
    """
    cache: ProblemCache = {}
    stats = WorkerStats()
    errors_in_a_row = 0
    while not stop.is_set():
        with Session(engine) as session, session.begin():  # commits the claim at once
            job = claim_next_job(session, lease_s=lease_s)
        if job is None:
            if drain:
                break
            stop.wait(poll_interval_s)  # returns early when stop is set
            continue

        outcome = process_job(engine, sandbox, job, cache)
        stats.add(outcome)
        if outcome is Outcome.DONE:
            errors_in_a_row = 0
        elif outcome in (Outcome.RETRY, Outcome.FAILED):
            errors_in_a_row += 1
            if errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
                raise WorkerStoppedError(
                    f"{errors_in_a_row} jobs in a row failed; stopping (see the log above)"
                )
            stop.wait(error_pause_s)
    return stats
