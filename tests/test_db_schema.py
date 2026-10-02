"""The database schema: migrations, drift between models and migrations, and the CHECK rules."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, make_url, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.db.models import (
    Base,
    JobStatus,
    ProblemRow,
    ProblemVersionRow,
    SubmissionRow,
    TestResultRow,
    UserRow,
)
from codetutor.grader.models import GradeStatus, TestStatus
from codetutor.settings import database_url_for_tests
from conftest import alembic_config, recreate_database

TABLES = {"users", "problem_versions", "problems", "submissions", "test_results"}

# A complete result, so a submission may be `done` (see ck_submissions_result_complete).
DONE: dict[str, Any] = {
    "job_status": "done",
    "result_status": "accepted",
    "passed": 8,
    "total": 8,
    "reward": 1.0,
    "stdout": "",
    "duration_ms": 12.5,
    "grader_version": "0.2.1",
}


def _submission(session: Session, **columns: Any) -> SubmissionRow:
    """Add a problem version, a user and a submission (with `columns` set); return it, flushed."""
    session.add(
        ProblemVersionRow(problem_id="cs1.loops.x", version=1, content_hash="0" * 64, problem={})
    )
    user = UserRow(name="sara")
    session.add(user)
    session.flush()
    submission = SubmissionRow(
        user_id=user.id, problem_id="cs1.loops.x", problem_version=1, code="pass", **columns
    )
    session.add(submission)
    session.flush()
    return submission


def _test_result(submission_id: int, **columns: Any) -> TestResultRow:
    """A test_results row; `columns` replaces the defaults (a passed visible test)."""
    values: dict[str, Any] = {
        "submission_id": submission_id,
        "test_id": "t01",
        "position": 0,
        "hidden": False,
        "revealed": True,
        "status": "passed",
        "duration_ms": 1.0,
    }
    return TestResultRow(**(values | columns))


def _violated_constraint(session: Session, row: Any) -> str:
    """Add `row`, expect the database to reject it, and return the name of the broken rule."""
    session.add(row)
    with pytest.raises(IntegrityError) as caught:
        session.flush()
    assert isinstance(caught.value.orig, psycopg.errors.IntegrityError)
    return caught.value.orig.diag.constraint_name


# --- Migrations ---


def test_migrations_go_down_and_up_again() -> None:
    # Its own database, so a failure halfway can't leave the shared test database half-built.
    test_url = make_url(database_url_for_tests())
    url = test_url.set(database=f"{test_url.database}_migrations").render_as_string(
        hide_password=False
    )
    recreate_database(url)
    config = alembic_config(url)
    engine = make_engine(url)
    try:
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == TABLES | {"alembic_version"}

        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}

        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == TABLES | {"alembic_version"}
    finally:
        engine.dispose()


def test_models_and_migrations_agree(db_engine: Engine) -> None:
    # "Changed a model, forgot the migration" shows up here as a list of differences.
    # Note: Alembic does not compare CHECK constraints; the status tests below cover those.
    with db_engine.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert differences == []


# --- CHECK rules and foreign keys ---


def test_a_hidden_test_is_never_stored_revealed(db_session: Session) -> None:
    submission = _submission(db_session, **DONE)
    row = _test_result(submission.id, hidden=True, revealed=True, input=[5], expected=30)
    assert _violated_constraint(db_session, row) == "ck_test_results_hidden_never_revealed"


@pytest.mark.parametrize("column", ["input", "expected", "actual"])
def test_an_unrevealed_test_stores_no_details(db_session: Session, column: str) -> None:
    submission = _submission(db_session, **DONE)
    row = _test_result(submission.id, hidden=True, revealed=False, **{column: [5]})
    assert _violated_constraint(db_session, row) == "ck_test_results_unrevealed_has_no_details"


def test_json_null_is_not_sql_null(db_session: Session) -> None:
    # Setting a json column to None stores JSON null, which counts as a stored detail. The
    # worker (Step 2) must leave input/expected/actual unset on unrevealed tests instead.
    submission = _submission(db_session, **DONE)
    row = _test_result(submission.id, hidden=True, revealed=False, expected=None)
    assert _violated_constraint(db_session, row) == "ck_test_results_unrevealed_has_no_details"


def test_unset_details_are_sql_null_and_none_is_json_null(db_session: Session) -> None:
    submission = _submission(db_session, **DONE)
    db_session.add(_test_result(submission.id, test_id="t01", input=[0], expected=None))
    db_session.add(
        _test_result(submission.id, test_id="t05", position=1, hidden=True, revealed=False)
    )
    db_session.flush()
    rows = db_session.execute(
        text("SELECT test_id, expected IS NULL, expected::text FROM test_results ORDER BY position")
    ).all()
    assert [tuple(row) for row in rows] == [("t01", False, "null"), ("t05", True, None)]


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"job_status": "done"}, "ck_submissions_result_iff_done"),
        (DONE | {"job_status": "queued"}, "ck_submissions_result_iff_done"),
        (DONE | {"passed": None}, "ck_submissions_result_complete"),
        (DONE | {"reward": 1.5}, "ck_submissions_reward_in_range"),
        (DONE | {"reward": -0.1}, "ck_submissions_reward_in_range"),
        ({"job_status": "paused"}, "ck_submissions_job_status_known"),
        (DONE | {"result_status": "great"}, "ck_submissions_result_status_known"),
    ],
)
def test_submission_rules(db_session: Session, columns: dict[str, Any], constraint: str) -> None:
    with pytest.raises(IntegrityError) as caught:
        _submission(db_session, **columns)
    assert caught.value.orig.diag.constraint_name == constraint


def test_problems_must_point_at_a_stored_version(db_session: Session) -> None:
    row = ProblemRow(
        id="cs1.loops.x",
        version=1,
        module=3,
        position=1,
        title="X",
        difficulty="easy",
        student_view={},
    )
    assert _violated_constraint(db_session, row) == "fk_problems_id_problem_versions"


def test_a_new_submission_is_queued(db_session: Session) -> None:
    submission = _submission(db_session)
    db_session.refresh(submission)
    assert (submission.job_status, submission.attempts) == (JobStatus.QUEUED, 0)
    assert submission.result_status is None


# --- Every status the code can produce is allowed by the database (migration 0001's lists) ---


@pytest.mark.parametrize("status", list(GradeStatus))
def test_every_grade_status_is_allowed(db_session: Session, status: GradeStatus) -> None:
    _submission(db_session, **(DONE | {"result_status": status.value}))


@pytest.mark.parametrize("status", list(JobStatus))
def test_every_job_status_is_allowed(db_session: Session, status: JobStatus) -> None:
    _submission(db_session, **(DONE if status is JobStatus.DONE else {"job_status": status.value}))


@pytest.mark.parametrize("status", list(TestStatus))
def test_every_test_status_is_allowed(db_session: Session, status: TestStatus) -> None:
    submission = _submission(db_session, **DONE)
    db_session.add(_test_result(submission.id, status=status.value))
    db_session.flush()


# --- json, not jsonb (docs/database.md) ---


@pytest.mark.parametrize("value", [1e16, 30.0, -0.0, 1e300])
def test_json_columns_keep_a_float_a_float(db_session: Session, value: float) -> None:
    submission = _submission(db_session, **DONE)
    db_session.add(_test_result(submission.id, input=[value], expected=value, actual=value))
    db_session.commit()
    db_session.expire_all()  # read back from the database, not from the session's memory
    stored = db_session.scalars(select(TestResultRow)).one()
    for got in (stored.input[0], stored.expected, stored.actual):
        assert type(got) is float
        assert repr(got) == repr(value)


def test_jsonb_would_turn_the_float_into_an_int(db_session: Session) -> None:
    # The reason for the choice above: jsonb rewrites numbers. If this ever fails, the
    # reason for using json is gone (the choice itself is still safe).
    [as_jsonb] = db_session.execute(text("SELECT CAST('1e16' AS jsonb)::text")).one()
    assert as_jsonb == "10000000000000000"
