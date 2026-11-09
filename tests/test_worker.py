"""The grading worker: the Postgres job queue, leases, fencing and retries (docs/worker.md)."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from codetutor.db.models import (
    JobStatus,
    ProblemRow,
    ProblemVersionRow,
    SubmissionRow,
    TestResultRow,
    UserRow,
)
from codetutor.db.sync import sync_problems
from codetutor.grader import DockerSandbox, GradeStatus, Limits, SubprocessSandbox, grade
from codetutor.grader.sandbox import DOCKER_START_MARGIN_S
from codetutor.problems import Problem, load_all
from codetutor.worker.jobs import (
    LEASE_S,
    MAX_ATTEMPTS,
    MAX_CODE_CHARS,
    InvalidSubmissionError,
    Job,
    UnknownProblemError,
    claim_next_job,
    enqueue_submission,
    load_grade_result,
    release_job,
    save_result,
)
from codetutor.worker.loop import Outcome, WorkerStoppedError, process_job, run_worker
from conftest import BUGGY, SOLUTION, ProblemWriter, docker_runtime

PROBLEM_ID = "cs1.loops.sum_of_evens"  # the conftest problem: 8 tests, 4 visible, 4 hidden
# Our own trusted test code, so the fast subprocess sandbox is fine here. The worker script
# always uses Docker; test_worker_grades_in_docker covers that path.
SANDBOX = SubprocessSandbox()
EXPIRED = -1.0  # a lease that has already run out, for "the worker died" scenarios

# Prints a NUL, raises an error containing NUL on t01 (n = 10), returns a string with NUL.
NUL_CODE = """def sum_of_evens(n):
    print("a\\x00b")
    if n == 10:
        raise ValueError("bad\\x00value")
    return "x\\x00y"
"""


@pytest.fixture
def problem(db_session: Session, write_problem: ProblemWriter) -> Problem:
    """The conftest problem, synced into the test database with the real sync."""
    folder = write_problem()
    sync_problems(db_session, folder.parents[2])
    db_session.commit()
    return Problem.model_validate(db_session.get(ProblemVersionRow, (PROBLEM_ID, 1)).problem)


@pytest.fixture
def user_id(db_session: Session) -> int:
    user = UserRow(name="sara")
    db_session.add(user)
    db_session.commit()
    return user.id


def _enqueue(session: Session, user_id: int, *codes: str) -> list[int]:
    """Queue one submission per code (committed); return their ids."""
    ids = [enqueue_submission(session, user_id, PROBLEM_ID, code) for code in codes]
    session.commit()
    return ids


def _claim(engine: Engine, lease_s: float = LEASE_S) -> Job | None:
    with Session(engine) as session, session.begin():
        return claim_next_job(session, lease_s=lease_s)


def _submission(engine: Engine, submission_id: int) -> SubmissionRow:
    with Session(engine) as session:
        return session.get(SubmissionRow, submission_id)


def _test_rows(engine: Engine, submission_id: int) -> list[TestResultRow]:
    with Session(engine) as session:
        rows = session.scalars(
            select(TestResultRow)
            .where(TestResultRow.submission_id == submission_id)
            .order_by(TestResultRow.position)
        )
        return list(rows)


def _corrupt_problem(session: Session) -> str:
    """A problem whose stored copy can't be loaded (a real broken row, not a mock)."""
    problem_id = "cs1.loops.broken"
    session.add(ProblemVersionRow(problem_id=problem_id, version=1, content_hash="x", problem={}))
    session.flush()
    session.add(
        ProblemRow(
            id=problem_id,
            version=1,
            module=3,
            position=9,
            title="Broken",
            difficulty="easy",
            student_view={},
        )
    )
    session.commit()
    return problem_id


# --- Enqueue ---


def test_enqueue_saves_a_queued_job_on_the_current_version(
    db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)
    row = db_session.get(SubmissionRow, submission_id)
    assert (row.job_status, row.attempts, row.problem_version) == (JobStatus.QUEUED, 0, 1)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("x" * (MAX_CODE_CHARS + 1), "too long"),
        ("a\x00b", "NUL"),
        ("x = '\ud800'", "not valid text"),
    ],
)
def test_enqueue_refuses_code_that_cannot_be_stored(
    db_session: Session, problem: Problem, user_id: int, code: str, message: str
) -> None:
    with pytest.raises(InvalidSubmissionError, match=message):
        enqueue_submission(db_session, user_id, PROBLEM_ID, code)


def test_enqueue_refuses_unknown_and_retired_problems(
    db_session: Session, problem: Problem, user_id: int
) -> None:
    with pytest.raises(UnknownProblemError):
        enqueue_submission(db_session, user_id, "cs1.loops.nope", SOLUTION)
    db_session.get(ProblemRow, PROBLEM_ID).active = False
    with pytest.raises(UnknownProblemError):
        enqueue_submission(db_session, user_id, PROBLEM_ID, SOLUTION)


# --- Claim, lease, fencing ---


def test_claim_takes_the_oldest_job_and_leases_it(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    first, second = _enqueue(db_session, user_id, SOLUTION, SOLUTION)

    job = _claim(db_engine)
    assert (job.id, job.attempts, job.code) == (first, 1, SOLUTION)
    row = _submission(db_engine, first)
    assert row.job_status == JobStatus.RUNNING
    lease_left = db_session.scalar(
        select(func.extract("epoch", SubmissionRow.lease_expires_at - func.now())).where(
            SubmissionRow.id == first
        )
    )
    assert LEASE_S - 10 < float(lease_left) <= LEASE_S

    assert _claim(db_engine).id == second
    assert _claim(db_engine) is None


def test_two_workers_never_get_the_same_job(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    ids = _enqueue(db_session, user_id, *[SOLUTION] * 40)
    claimed: list[int] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def worker() -> None:
        start.wait()  # all 8 threads start claiming at the same moment
        while (job := _claim(db_engine)) is not None:
            with lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(claimed) == ids  # every job exactly once: no duplicates, none missed


def test_an_expired_lease_is_claimed_again(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)
    first = _claim(db_engine, lease_s=EXPIRED)  # this worker "dies"
    second = _claim(db_engine)
    assert (first.id, first.attempts) == (submission_id, 1)
    assert (second.id, second.attempts) == (submission_id, 2)


def test_a_job_whose_lease_expires_on_the_last_attempt_fails(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)
    for _ in range(MAX_ATTEMPTS):
        _claim(db_engine, lease_s=EXPIRED)

    assert _claim(db_engine) is None
    row = _submission(db_engine, submission_id)
    assert (row.job_status, row.attempts) == (JobStatus.FAILED, MAX_ATTEMPTS)
    assert row.last_error.startswith(f"lease expired on attempt {MAX_ATTEMPTS}")


def test_a_late_save_from_a_lost_lease_writes_nothing(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)
    slow = _claim(db_engine, lease_s=EXPIRED)  # worker A: too slow, its lease runs out
    fast = _claim(db_engine)  # worker B takes the job over
    result = grade(problem, SOLUTION, sandbox=SANDBOX)

    with Session(db_engine) as session, session.begin():
        assert save_result(session, slow, result) is False
        assert release_job(session, slow, "late") is None
    assert _test_rows(db_engine, submission_id) == []  # A wrote nothing

    with Session(db_engine) as session, session.begin():
        assert save_result(session, fast, result) is True
    assert len(_test_rows(db_engine, submission_id)) == 8


# --- Grading and saving ---


def test_a_correct_solution_is_saved_as_done(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)

    assert process_job(db_engine, SANDBOX, _claim(db_engine), {}) is Outcome.DONE

    row = _submission(db_engine, submission_id)
    assert (row.job_status, row.result_status, row.reward) == (JobStatus.DONE, "accepted", 1.0)
    assert (row.passed, row.total, row.lease_expires_at) == (8, 8, None)
    assert row.finished_at is not None
    tests = _test_rows(db_engine, submission_id)
    assert [t.test_id for t in tests] == [f"t0{i}" for i in range(1, 9)]
    hidden = [t for t in tests if t.hidden]
    assert len(hidden) == 4
    assert all(not t.revealed and t.input is None and t.expected is None for t in hidden)
    assert db_session.scalar(
        text("SELECT count(*) FROM test_results WHERE hidden AND input IS NULL")
    ) == len(hidden)


def test_a_buggy_solution_is_saved_as_wrong_answer(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, BUGGY)
    process_job(db_engine, SANDBOX, _claim(db_engine), {})

    result = load_grade_result(db_session, submission_id)
    assert result.status is GradeStatus.WRONG_ANSWER
    t01 = result.tests[0]  # visible: the student sees input, expected and actual
    assert (t01.input, t01.expected, t01.actual) == ([10], 30, 20)
    t07 = next(test for test in result.tests if test.test_id == "t07")  # hidden, failed
    assert (t07.status, t07.input, t07.expected, t07.actual) == ("wrong_answer", None, None, None)


def test_a_saved_result_loads_back_unchanged(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    code = 'print("loading")\n' + BUGGY
    [submission_id] = _enqueue(db_session, user_id, code)
    job = _claim(db_engine)
    result = grade(problem, code, reveal_hidden=False, sandbox=SANDBOX)
    with Session(db_engine) as session, session.begin():
        save_result(session, job, result)

    # repr, not ==: it also shows 30 vs 30.0 (the grader treats them differently).
    assert repr(load_grade_result(db_session, submission_id)) == repr(result)


def test_nul_is_cleaned_in_text_but_kept_in_json_values(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, NUL_CODE)

    assert process_job(db_engine, SANDBOX, _claim(db_engine), {}) is Outcome.DONE

    result = load_grade_result(db_session, submission_id)
    assert "a�b" in result.stdout and "\x00" not in result.stdout
    assert result.tests[0].error == "ValueError: bad�value"
    assert result.tests[1].actual == "x\x00y"  # a json value: stored as \u0000, comes back


def test_the_result_is_none_until_the_job_is_done(
    db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)
    assert load_grade_result(db_session, submission_id) is None


# --- Errors and the loop ---


def test_a_corrupt_problem_copy_is_retried_then_failed(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    broken = _corrupt_problem(db_session)
    submission_id = enqueue_submission(db_session, user_id, broken, SOLUTION)
    db_session.commit()

    stats = run_worker(db_engine, SANDBOX, threading.Event(), drain=True, error_pause_s=0)

    assert (stats.retry, stats.failed, stats.done) == (MAX_ATTEMPTS - 1, 1, 0)
    row = _submission(db_engine, submission_id)
    assert (row.job_status, row.attempts) == (JobStatus.FAILED, MAX_ATTEMPTS)
    assert row.last_error.startswith("ValidationError")
    assert row.result_status is None


def test_the_worker_stops_after_too_many_errors_in_a_row(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    broken = _corrupt_problem(db_session)
    for _ in range(2):  # 2 jobs × 3 attempts: the 5th error in a row stops the worker
        enqueue_submission(db_session, user_id, broken, SOLUTION)
    db_session.commit()

    with pytest.raises(WorkerStoppedError, match="5 jobs in a row failed"):
        run_worker(db_engine, SANDBOX, threading.Event(), drain=True, error_pause_s=0)


def test_drain_grades_everything_then_returns(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    ids = _enqueue(db_session, user_id, SOLUTION, BUGGY, SOLUTION)

    stats = run_worker(db_engine, SANDBOX, threading.Event(), drain=True)

    assert (stats.done, stats.retry, stats.failed, stats.lost) == (3, 0, 0, 0)
    statuses = [_submission(db_engine, i).result_status for i in ids]
    assert statuses == ["accepted", "wrong_answer", "accepted"]


def test_a_set_stop_event_stops_before_the_next_claim(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    [submission_id] = _enqueue(db_session, user_id, SOLUTION)
    stop = threading.Event()
    stop.set()

    stats = run_worker(db_engine, SANDBOX, stop)

    assert stats.done == 0
    assert _submission(db_engine, submission_id).job_status == JobStatus.QUEUED


def test_the_lease_covers_the_slowest_bank_problem() -> None:
    # If a problem could take longer than its lease, a second worker would grade it again.
    def worst_case_s(problem: Problem) -> float:
        limits = Limits(per_test_timeout_s=problem.time_limit_s)
        return limits.total_for(len(problem.tests)) + DOCKER_START_MARGIN_S

    slowest = max(load_all(), key=worst_case_s)
    assert worst_case_s(slowest) < LEASE_S / 2, slowest.id


@pytest.mark.docker
def test_worker_grades_in_docker(
    db_engine: Engine, db_session: Session, problem: Problem, user_id: int
) -> None:
    ids = _enqueue(db_session, user_id, SOLUTION, BUGGY)

    stats = run_worker(
        db_engine, DockerSandbox(runtime=docker_runtime()), threading.Event(), drain=True
    )

    assert stats.done == 2
    assert [_submission(db_engine, i).result_status for i in ids] == ["accepted", "wrong_answer"]
