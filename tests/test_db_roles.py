"""The API's database role (Deploy Step 2a, db/roles.py): least privilege, enforced by Postgres.

Roles belong to the whole Postgres server, not to one database, so the tests use their own role
name. The grants themselves live in the test database and go when it is dropped.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from codetutor.api import create_app
from codetutor.db.engine import make_engine
from codetutor.db.roles import API_ROLE, DEMO_ROLE, apply_api_role, apply_demo_role
from codetutor.db.sync import sync_problems
from codetutor.grader import SubprocessSandbox
from codetutor.settings import database_url_for_tests
from codetutor.tutor.jobs import claim_next_hint
from codetutor.tutor.loop import Tutor, process_hint_job
from codetutor.tutor.service import TutorConfig
from codetutor.worker.jobs import claim_next_job
from codetutor.worker.loop import Outcome, process_job
from conftest import BUGGY, ProblemWriter, ScriptedModel

ROLE = "codetutor_api_test"
PROBLEM_ID = "cs1.loops.sum_of_evens"
HINT = "Look at where your range stops: is n itself included?"
GRANTS_SQL = """
    SELECT 'table', table_name, privilege_type, '' FROM information_schema.role_table_grants
    WHERE grantee = :role
    UNION ALL
    SELECT 'column', table_name, privilege_type, column_name
    FROM information_schema.column_privileges WHERE grantee = :role
    ORDER BY 1, 2, 3, 4
"""


@pytest.fixture
def role_engine(
    db_engine: Engine, db_session: Session, write_problem: ProblemWriter
) -> Iterator[Engine]:
    """An engine logged in as the API role (grants applied to the test database)."""
    sync_problems(db_session, write_problem().parents[2])
    db_session.commit()
    password = secrets.token_hex(16)
    with db_engine.begin() as connection:
        apply_api_role(connection, ROLE, password)
    url = make_url(database_url_for_tests()).set(username=ROLE, password=password)
    engine = make_engine(url.render_as_string(hide_password=False))
    yield engine
    engine.dispose()


def _denied(engine: Engine, sql: str) -> bool:
    with engine.connect() as connection:
        try:
            connection.execute(text(sql))
        except ProgrammingError as exc:
            return "permission denied" in str(exc)
    return False


def test_the_api_role_cannot_read_the_hidden_tests(role_engine: Engine) -> None:
    assert _denied(role_engine, "SELECT 1 FROM problem_versions")


@pytest.mark.parametrize("column", ["student_code", "attempts", "last_error", "claims"])
def test_the_api_role_cannot_read_the_hint_trace(role_engine: Engine, column: str) -> None:
    assert _denied(role_engine, f"SELECT {column} FROM hints")


@pytest.mark.parametrize("table", ["note_chunks", "alembic_version"])
def test_the_api_role_cannot_read_tables_it_never_needs(role_engine: Engine, table: str) -> None:
    assert _denied(role_engine, f"SELECT 1 FROM {table}")


def test_the_whole_api_works_as_that_role(
    role_engine: Engine, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTRUCTOR_TOKEN", "t" * 32)
    app = create_app(engine=role_engine, dev_login=False)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/guest").status_code == 200
        assert client.get("/api/me").status_code == 200
        body = {"problem_id": PROBLEM_ID, "problem_version": 1, "code": BUGGY}
        submission_id = client.post("/api/submissions", json=body).json()["id"]
        with Session(db_engine) as session, session.begin():  # the worker: owner role
            job = claim_next_job(session)
        assert process_job(db_engine, SubprocessSandbox(), job, {}) is Outcome.DONE

        assert client.get(f"/api/submissions/{submission_id}").json()["job_status"] == "done"
        assert client.get("/api/submissions").status_code == 200
        hint_body = {
            "problem_id": PROBLEM_ID,
            "problem_version": 1,
            "level": 1,
            "submission_id": submission_id,
        }
        hint_id = client.post("/api/hints", json=hint_body).json()["id"]
        with Session(db_engine) as session, session.begin():  # the tutor worker: owner role
            hint_job = claim_next_hint(session)
        tutor = Tutor(ScriptedModel(HINT), config=TutorConfig(search_method="keyword"))
        assert process_hint_job(db_engine, tutor, hint_job, {}) is Outcome.DONE

        assert client.get(f"/api/hints/{hint_id}").json()["text"] == HINT
        assert client.get("/api/hints").status_code == 200
        rated = client.put(f"/api/hints/{hint_id}/rating", json={"rating": 1})
        assert rated.status_code == 200, rated.text
        teacher = {"X-Instructor-Token": "t" * 32}
        for path in ("overview", "students", "problems"):
            assert client.get(f"/api/instructor/{path}", headers=teacher).status_code == 200
        assert client.post("/api/logout").status_code == 200


def test_applying_the_grants_twice_changes_nothing(db_engine: Engine, role_engine: Engine) -> None:
    with db_engine.connect() as connection:
        before = connection.execute(text(GRANTS_SQL), {"role": ROLE}).all()
    with db_engine.begin() as connection:
        apply_api_role(connection, ROLE, secrets.token_hex(16))
    with db_engine.connect() as connection:
        after = connection.execute(text(GRANTS_SQL), {"role": ROLE}).all()
    assert before and after == before


@pytest.mark.parametrize("password", ["short", "has'quote" * 3, "x" * 15])
def test_a_password_that_is_not_long_hex_like_is_refused(db_engine: Engine, password: str) -> None:
    with db_engine.begin() as connection, pytest.raises(ValueError, match="password"):
        apply_api_role(connection, ROLE, password)


def test_the_role_name_is_checked(db_engine: Engine) -> None:
    with db_engine.begin() as connection, pytest.raises(ValueError, match="role"):
        apply_api_role(connection, "api; DROP TABLE users", secrets.token_hex(16))


def test_the_tests_never_touch_the_production_role() -> None:
    assert ROLE != API_ROLE


# --- the demo role (Deploy Step 2c): read-only, for the public demo of a simulated class ---

DEMO_TEST_ROLE = "codetutor_demo_test"


@pytest.fixture
def demo_engine(db_engine: Engine, db_session: Session) -> Iterator[Engine]:
    password = secrets.token_hex(16)
    with db_engine.begin() as connection:
        apply_demo_role(connection, DEMO_TEST_ROLE, password)
    url = make_url(database_url_for_tests()).set(username=DEMO_TEST_ROLE, password=password)
    engine = make_engine(url.render_as_string(hide_password=False))
    yield engine
    engine.dispose()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, name FROM users",
        "SELECT id, user_id, problem_id, created_at, result_status FROM submissions",
        "SELECT id FROM problems",
        "SELECT submission_id, kind, reason FROM integrity_flags",
    ],
)
def test_the_demo_role_reads_what_the_teacher_routes_read(demo_engine: Engine, sql: str) -> None:
    with demo_engine.connect() as connection:
        connection.execute(text(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT code FROM submissions",  # no student code, enforced by the database
        "SELECT stdout FROM submissions",
        "SELECT editor_stats FROM submissions",
        "SELECT 1 FROM problem_versions",
        "SELECT 1 FROM sessions",
        "SELECT 1 FROM hints",
        "SELECT 1 FROM test_results",
        "SELECT 1 FROM note_chunks",
    ],
)
def test_the_demo_role_cannot_read_anything_else(demo_engine: Engine, sql: str) -> None:
    assert _denied(demo_engine, sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (name) VALUES ('x')",
        "UPDATE users SET name = 'x'",
        "DELETE FROM users",
        "DELETE FROM integrity_flags",
        "TRUNCATE submissions",
    ],
)
def test_the_demo_role_cannot_change_anything(demo_engine: Engine, sql: str) -> None:
    assert _denied(demo_engine, sql)


def test_the_demo_api_works_as_that_role(
    demo_engine: Engine, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codetutor.api.demo import create_demo_app

    with TestClient(create_demo_app(engine=demo_engine)) as client:
        for path in ("overview", "students", "problems"):
            assert client.get(f"/api/instructor/{path}").status_code == 200, path


def test_the_roles_have_different_names() -> None:
    assert DEMO_ROLE != API_ROLE
