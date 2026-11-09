"""The public demo API (Deploy Step 2c, docs/deploy.md): the teacher view of a simulated class,
read-only and without a token. It runs in its own container on its own (simulated) database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from codetutor.api.demo import ClassCache, DemoDatabaseError, check_demo_database, create_demo_app
from codetutor.db.sync import sync_problems
from codetutor.db.users import get_or_create_user
from codetutor.grader import SubprocessSandbox
from codetutor.worker.jobs import claim_next_job, enqueue_submission
from codetutor.worker.loop import Outcome, process_job
from conftest import BUGGY, SOLUTION, ProblemWriter

PROBLEM_ID = "cs1.loops.sum_of_evens"
DEMO_PATHS = (
    "/api/instructor/overview",
    "/api/instructor/students",
    "/api/instructor/students/1",
    "/api/instructor/problems",
)


@pytest.fixture
def small_class(db_engine: Engine, db_session: Session, write_problem: ProblemWriter) -> None:
    """Two students: sara solves at once, bob fails first and then solves."""
    sync_problems(db_session, write_problem().parents[2])
    sara = get_or_create_user(db_session, "sim-001")
    bob = get_or_create_user(db_session, "sim-002")
    for user, code in ((sara, SOLUTION), (bob, BUGGY), (bob, SOLUTION)):
        enqueue_submission(db_session, user, PROBLEM_ID, code)
    db_session.commit()
    for _ in range(3):
        with Session(db_engine) as session, session.begin():
            job = claim_next_job(session)
        assert process_job(db_engine, SubprocessSandbox(), job, {}) is Outcome.DONE


@pytest.fixture
def demo(db_engine: Engine, small_class: None) -> Iterator[TestClient]:
    with TestClient(create_demo_app(engine=db_engine)) as client:
        yield client


def test_the_demo_serves_exactly_the_four_teacher_routes(db_engine: Engine) -> None:
    spec = create_demo_app(engine=db_engine).openapi()
    routes = {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}
    assert routes == {
        ("GET", "/api/instructor/overview"),
        ("GET", "/api/instructor/students"),
        ("GET", "/api/instructor/students/{student_id}"),
        ("GET", "/api/instructor/problems"),
        ("GET", "/health"),
    }


def test_the_routes_answer_without_a_token(demo: TestClient) -> None:
    overview = demo.get("/api/instructor/overview")
    assert overview.status_code == 200
    assert overview.json()["students"] == 2 and overview.json()["submissions"] == 3
    names = {student["name"] for student in demo.get("/api/instructor/students").json()}
    assert names == {"sim-001", "sim-002"}
    assert demo.get("/api/instructor/problems").status_code == 200
    student_id = demo.get("/api/instructor/students").json()[0]["id"]
    assert demo.get(f"/api/instructor/students/{student_id}").status_code == 200
    assert demo.get("/api/instructor/students/99999").status_code == 404


def test_nothing_can_be_changed_and_there_is_no_student_api(demo: TestClient) -> None:
    for path in DEMO_PATHS:
        assert demo.post(path).status_code == 405
        assert demo.delete(path).status_code == 405
    for path in ("/api/guest", "/api/login", "/api/submissions", "/api/hints", "/api/me"):
        assert demo.post(path).status_code == 404, path
        assert demo.get(path).status_code == 404, path


def test_no_answer_contains_code(demo: TestClient) -> None:
    for path in DEMO_PATHS[:2] + DEMO_PATHS[3:]:
        text = demo.get(path).text
        assert "def " not in text and "return " not in text, path


def test_answers_may_be_cached_by_a_browser_for_a_minute(demo: TestClient) -> None:
    assert demo.get("/api/instructor/overview").headers["cache-control"] == "public, max-age=60"


def test_the_class_is_read_once_per_window(db_engine: Engine, small_class: None) -> None:
    queries: list[str] = []

    @event.listens_for(db_engine, "before_cursor_execute")
    def count(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        queries.append(statement)

    try:
        with TestClient(create_demo_app(engine=db_engine)) as client:
            assert client.get("/api/instructor/overview").status_code == 200
            after_first = len(queries)
            client.get("/api/instructor/students")
            client.get("/api/instructor/problems")
            assert after_first > 0 and len(queries) == after_first
    finally:
        event.remove(db_engine, "before_cursor_execute", count)


def test_the_cache_reloads_after_its_time_is_up(db_engine: Engine, small_class: None) -> None:
    loads: list[int] = []
    clock = [0.0]
    cache = ClassCache(ttl_s=300, clock=lambda: clock[0])

    def load(session: Session) -> int:
        loads.append(1)
        return len(loads)

    with Session(db_engine) as session:
        assert cache.get(session, load) == 1
        clock[0] = 299
        assert cache.get(session, load) == 1
        clock[0] = 301
        assert cache.get(session, load) == 2


@pytest.mark.parametrize("name", ["codetutor", "codetutor_test", "prod"])
def test_a_database_without_sim_in_its_name_is_refused(name: str) -> None:
    with pytest.raises(DemoDatabaseError, match="sim"):
        check_demo_database(f"postgresql://u:p@db:5432/{name}")


@pytest.mark.parametrize("name", ["codetutor_sim", "codetutor_sim_s1"])
def test_a_simulation_database_is_accepted(name: str) -> None:
    check_demo_database(f"postgresql://u:p@db:5432/{name}")


def test_the_factory_checks_the_configured_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/codetutor")
    with pytest.raises(DemoDatabaseError):
        create_demo_app()


def test_the_demo_code_does_not_name_the_student_tables() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/codetutor/api/demo.py").read_text()
    for table in ("HintRow", "SessionRow", "ProblemVersionRow"):
        assert table not in source
