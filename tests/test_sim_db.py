"""The simulated class in a database (Week 5 Step 1b): loading, labels kept out, joining back.

Runs on the test database (never codetutor_sim), with the committed cohort file's first rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from codetutor.db.admin import DatabaseNameError, database_name, recreate_database
from codetutor.db.models import SubmissionRow, UserRow
from codetutor.db.sync import sync_problems
from codetutor.grader import SubprocessSandbox
from codetutor.sim.cohort import CohortRow, read_rows
from codetutor.sim.load import SimDatabaseNotEmptyError, graded_rows, load_rows, summary
from codetutor.sim.pools import SourceKind
from codetutor.worker.jobs import claim_next_job
from codetutor.worker.loop import Outcome, process_job

COHORT = Path(__file__).resolve().parents[1] / "lab" / "sim" / "cohort-s0.jsonl"
SANDBOX = SubprocessSandbox()  # only rows whose code is the bank's own files are graded here
FIRST_ROWS = 40  # all in module 1 (the first week)


@pytest.fixture(scope="module")
def rows() -> list[CohortRow]:
    return read_rows(COHORT)[:FIRST_ROWS]


@pytest.fixture
def loaded(db_session: Session, rows: list[CohortRow]) -> Session:
    sync_problems(db_session)  # the real bank: the rows are about real problems
    load_rows(db_session, rows)
    db_session.commit()
    return db_session


def test_a_sim_database_must_have_sim_in_its_name() -> None:
    with pytest.raises(DatabaseNameError, match="must contain 'sim'"):
        recreate_database("postgresql://u:p@127.0.0.1:5432/codetutor", must_contain="sim")
    assert database_name("postgresql+psycopg://u:p@127.0.0.1:5432/codetutor_sim") == "codetutor_sim"


def test_rows_are_queued_at_their_simulated_times(loaded: Session, rows: list[CohortRow]) -> None:
    stored = loaded.execute(
        select(UserRow.name, SubmissionRow).join(UserRow).order_by(SubmissionRow.id)
    ).all()
    assert len(stored) == len(rows)
    expected = sorted(rows, key=lambda r: (r.created_at, r.key))
    for (name, submission), row in zip(stored, expected, strict=True):
        assert (name, submission.problem_id) == (row.student, row.problem_id)
        assert submission.code == row.code
        assert submission.created_at == row.created_at
        assert submission.editor_stats == row.editor_stats
        assert submission.job_status == "queued"
    first = loaded.scalar(select(UserRow.created_at).where(UserRow.name == expected[0].student))
    assert first == expected[0].created_at  # signed up at their first submission


def test_no_label_ever_reaches_the_database(loaded: Session, rows: list[CohortRow]) -> None:
    dump = (
        loaded.execute(
            text("SELECT string_agg(t::text, ' ') FROM (SELECT * FROM submissions) AS t")
        ).scalar_one()
        + loaded.execute(
            text("SELECT string_agg(t::text, ' ') FROM (SELECT * FROM users) AS t")
        ).scalar_one()
    )
    # The label's field names, and its references, which only the simulator knows. (Persona
    # names can't be searched for: "average" is also in "average_of_three".)
    for field in ('"persona"', '"source_kind"', '"source_ref"', '"intended_pass"', '"cheating"'):
        assert field not in dump, field
    for row in rows:
        assert row.label.source_ref not in dump, row.label.source_ref


def test_loading_twice_is_refused(loaded: Session, rows: list[CohortRow]) -> None:
    with pytest.raises(SimDatabaseNotEmptyError, match="make sim-db"):
        load_rows(loaded, rows)
    assert loaded.scalar(select(func.count()).select_from(SubmissionRow)) == len(rows)


def test_graded_rows_join_back_to_their_labels(
    loaded: Session, db_engine: Engine, rows: list[CohortRow]
) -> None:
    bank_code = {SourceKind.SOLUTION, SourceKind.BUGGY}
    to_grade = {r.key for r in rows if r.label.source_kind in bank_code}
    assert to_grade, "module 1 should have bank-code rows"
    row_of = {item.submission_id: item.row for item in graded_rows(loaded, rows)}
    graded_now = 0
    while True:  # claim in queue order; grade bank-code rows, mark the rest failed
        with Session(db_engine) as session, session.begin():
            job = claim_next_job(session)
            if job is None:
                break
            if row_of[job.id].key not in to_grade:
                session.execute(
                    text("UPDATE submissions SET job_status = 'failed' WHERE id = :id"),
                    {"id": job.id},
                )
                continue
        assert process_job(db_engine, SANDBOX, job, {}) is Outcome.DONE
        graded_now += 1

    graded = graded_rows(loaded, rows)
    assert len(graded) == len(rows) and graded_now == len(to_grade)
    for item in graded:
        if item.row.key in to_grade:
            assert (item.result_status == "accepted") == item.row.label.intended_pass
    text_summary = summary(graded)
    assert f"{len(rows)} submissions:" in text_summary
    assert f"for {len(to_grade)} of {len(to_grade)}" in text_summary
