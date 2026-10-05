"""The tutor worker loop: claim a hint job, make the hint, save it (docs/tutor.md §4).

The same three steps as the grading worker (worker/loop.py), and no transaction stays open
while the model works:
  1. claim (one short transaction, committed at once),
  2. make the hint with `give_hint` (the note search reads in autocommit mode; 1 s to 2 min),
  3. save the hint and its trace (one short transaction).

A model that fails or writes code is NOT an error here: `give_hint` already falls back to the
teacher's hint, so the student always gets one. Errors here are ours (database, a corrupt
problem copy).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from codetutor.db.models import JobStatus
from codetutor.evals.clients import ChatModel, Embedder
from codetutor.tutor.context import HintRequest
from codetutor.tutor.jobs import (
    LEASE_S,
    HintJob,
    claim_next_hint,
    earlier_hints,
    release_hint,
    save_hint_result,
)
from codetutor.tutor.service import TutorConfig, give_hint
from codetutor.worker.jobs import load_grade_result
from codetutor.worker.loop import (
    ERROR_PAUSE_S,
    MAX_ERRORS_IN_A_ROW,
    POLL_INTERVAL_S,
    Outcome,
    ProblemCache,
    WorkerStats,
    WorkerStoppedError,
    load_problem_copy,
)

# Ollama keeps a model 10 minutes after keep_loaded() (clients.OLLAMA_KEEP_ALIVE); refresh
# well before that, so a student never waits for the model to load again (13 s, measured).
KEEP_LOADED_EVERY_S = 240.0

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tutor:
    """What the worker makes hints with. `model` None: always the teacher's hint."""

    model: ChatModel | None
    embedder: Embedder | None = None
    config: TutorConfig = field(default_factory=TutorConfig)


def _release(engine: Engine, job: HintJob, error: str) -> Outcome:
    with Session(engine) as session, session.begin():
        status = release_hint(session, job, error)
    if status is None:
        return Outcome.LOST
    return Outcome.FAILED if status is JobStatus.FAILED else Outcome.RETRY


def process_hint_job(engine: Engine, tutor: Tutor, job: HintJob, cache: ProblemCache) -> Outcome:
    """Make the hint for one claimed job and save it; release the job if anything of ours fails."""
    try:
        with Session(engine) as session:
            problem = load_problem_copy(session, job.problem_id, job.problem_version, cache)
            # Stored with reveal_hidden=False; HintRequest refuses anything else.
            result = load_grade_result(session, job.submission_id) if job.submission_id else None
            earlier = earlier_hints(session, job)
        request = HintRequest(
            problem,
            job.code,
            job.level,
            question=job.question,
            result=result,
            earlier_hints=earlier,
        )
        # Autocommit: the search's reads don't keep a transaction open during the model call.
        reader = engine.execution_options(isolation_level="AUTOCOMMIT")
        with Session(reader) as session:
            hint = give_hint(
                request,
                model=tutor.model,
                session=session,
                embedder=tutor.embedder,
                config=tutor.config,
            )
        with Session(engine) as session, session.begin():
            saved = save_hint_result(session, job, hint)
    except Exception as exc:  # a worker must survive any single job; the error is kept
        log.exception("hint %d (claim %d) failed", job.id, job.claims)
        outcome = _release(engine, job, f"{type(exc).__name__}: {exc}")
        log.warning("hint %d: %s", job.id, outcome.value)
        return outcome

    if not saved:
        log.warning("hint %d: lease lost (another worker took it); not saved", job.id)
        return Outcome.LOST
    blocked = sum(1 for attempt in hint.attempts if not attempt.ok)
    log.info(
        "hint %d %s level %d: %s (%d attempt(s), %d not shown, %.1f s)",
        job.id,
        job.problem_id,
        job.level,
        hint.source.value,
        len(hint.attempts),
        blocked,
        hint.latency_ms / 1000,
    )
    return Outcome.DONE


def run_tutor_worker(
    engine: Engine,
    tutor: Tutor,
    stop: threading.Event,
    *,
    drain: bool = False,
    poll_interval_s: float = POLL_INTERVAL_S,
    error_pause_s: float = ERROR_PAUSE_S,
    lease_s: float = LEASE_S,
    keep_loaded: Callable[[], None] | None = None,
    keep_loaded_every_s: float = KEEP_LOADED_EVERY_S,
) -> WorkerStats:
    """Claim and answer hint jobs until `stop` is set (or, with drain=True, none is left).

    The same loop as the grading worker's `run_worker`. `keep_loaded` is called every
    `keep_loaded_every_s` (between jobs); if it fails, hints still work (the model just
    loads again on the next call). Raises WorkerStoppedError after MAX_ERRORS_IN_A_ROW failed
    jobs in a row.
    """
    cache: ProblemCache = {}
    stats = WorkerStats()
    errors_in_a_row = 0
    next_keep_loaded = time.monotonic() + keep_loaded_every_s
    while not stop.is_set():
        if keep_loaded is not None and time.monotonic() >= next_keep_loaded:
            _refresh(keep_loaded)
            next_keep_loaded = time.monotonic() + keep_loaded_every_s
        with Session(engine) as session, session.begin():  # commits the claim at once
            job = claim_next_hint(session, lease_s=lease_s)
        if job is None:
            if drain:
                break
            stop.wait(poll_interval_s)  # returns early when stop is set
            continue

        outcome = process_hint_job(engine, tutor, job, cache)
        stats.add(outcome)
        if outcome is Outcome.DONE:
            errors_in_a_row = 0
        elif outcome in (Outcome.RETRY, Outcome.FAILED):
            errors_in_a_row += 1
            if errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
                raise WorkerStoppedError(
                    f"{errors_in_a_row} hint jobs in a row failed; stopping (see the log above)"
                )
            stop.wait(error_pause_s)
    return stats


def _refresh(keep_loaded: Callable[[], None]) -> None:
    try:
        keep_loaded()
    except Exception as exc:  # only a speed-up: a failure must not stop the worker
        log.warning("could not keep the models loaded: %s", exc)
