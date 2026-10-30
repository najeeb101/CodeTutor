"""The HTTP API (docs/api.md): endpoints, dev login, no hidden-test leaks, rate limits."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, make_url, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from codetutor.api import create_app
from codetutor.api.schemas import FAILED_MESSAGE, MAX_REPR_CHARS, py_repr
from codetutor.api.submissions import RateLimitedError, RateLimits, create_submission
from codetutor.db.engine import make_engine
from codetutor.db.models import IntegrityFlagRow, SubmissionRow, UserRow
from codetutor.db.sync import sync_problems
from codetutor.grader import SubprocessSandbox
from codetutor.problems import StudentProblem
from codetutor.settings import database_url_for_tests
from codetutor.worker.jobs import MAX_CODE_CHARS, claim_next_job
from codetutor.worker.loop import Outcome, process_job
from conftest import BUGGY, SOLUTION, ProblemWriter, valid_meta, valid_tests

PROBLEM_ID = "cs1.loops.sum_of_evens"  # the conftest problem: t01-t04 visible, t05-t08 hidden
HIDDEN_IDS = ("t05", "t06", "t07", "t08")
SANDBOX = SubprocessSandbox()  # our own trusted test code (see test_worker.py)
API_DIR = Path(__file__).resolve().parents[1] / "src" / "codetutor" / "api"


@pytest.fixture
def bank_root(db_session: Session, write_problem: ProblemWriter) -> Path:
    """The conftest problem, synced into the test database with the real sync. Returns the
    bank's root folder, so a test can add problems and sync again."""
    root = write_problem().parents[2]
    sync_problems(db_session, root)
    db_session.commit()
    return root


@pytest.fixture
def client(db_engine: Engine, db_session: Session, bank_root: Path) -> Iterator[TestClient]:
    """The API on the test database (default limits). db_session empties the tables after."""
    with TestClient(create_app(engine=db_engine)) as client:
        yield client


def _limited_client(db_engine: Engine, limits: RateLimits) -> TestClient:
    """An API with other limits (use it in a `with` block)."""
    return TestClient(create_app(engine=db_engine, limits=limits))


def _login(client: TestClient, name: str = "sara") -> dict[str, str]:
    """Log in; return the headers that identify this user."""
    response = client.post("/api/login", json={"name": name})
    assert response.status_code == 200, response.text
    return {"X-User-Id": str(response.json()["id"])}


def _post_submission(
    client: TestClient,
    headers: dict[str, str],
    code: str = SOLUTION,
    version: int = 1,
    problem_id: str = PROBLEM_ID,
) -> httpx.Response:
    body = {"problem_id": problem_id, "problem_version": version, "code": code}
    return client.post("/api/submissions", json=body, headers=headers)


def _submit(client: TestClient, headers: dict[str, str], code: str = SOLUTION) -> int:
    """Submit (expecting 202); return the submission id."""
    response = _post_submission(client, headers, code)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def _display_text(test: dict[str, object]) -> tuple[object, object, object]:
    """A test result's Python display text: (args, expected, actual)."""
    return (test["args_repr"], test["expected_repr"], test["actual_repr"])


def _grade_next(engine: Engine) -> None:
    """Do one worker step: claim the oldest job, grade it, save it."""
    with Session(engine) as session, session.begin():
        job = claim_next_job(session)
    assert process_job(engine, SANDBOX, job, {}) is Outcome.DONE


# --- Health and login ---


def test_health_is_ok_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/api/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_an_unreachable_database_is_a_503() -> None:
    # A database that doesn't exist: the real server says so at once (no connect timeout).
    url = make_url(database_url_for_tests()).set(database="codetutor_missing_test")
    engine = make_engine(url.render_as_string(hide_password=False))
    try:
        with TestClient(create_app(engine=engine)) as client:
            response = client.get("/api/health")
    finally:
        engine.dispose()
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable, try again soon"}


def test_login_creates_each_user_once(client: TestClient, db_session: Session) -> None:
    first = client.post("/api/login", json={"name": "sara"}).json()
    again = client.post("/api/login", json={"name": "  sara "}).json()  # spaces are trimmed
    arabic = client.post("/api/login", json={"name": "نجيب"}).json()  # any language

    assert first == again == {"id": first["id"], "name": "sara"}
    assert arabic["name"] == "نجيب" and arabic["id"] != first["id"]
    assert db_session.scalar(select(func.count()).select_from(UserRow)) == 2


@pytest.mark.parametrize(
    "body",
    [{"name": ""}, {"name": "   "}, {"name": "x" * 41}, {"name": "a\nb"}, {"name": "a\x00b"},
     {"name": "sara", "admin": True}, {}],
    ids=["empty", "spaces", "too_long", "newline", "nul", "unknown_field", "missing"],
)  # fmt: skip
def test_login_refuses_bad_names(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/api/login", json=body).status_code == 422


@pytest.mark.parametrize(
    ("path", "body"),
    [("/api/login", rb'{"name": "a\ud800"}'),
     ("/api/login", rb'{"name": "sara", "\ud800": 1}'),
     ("/api/submissions", rb'{"problem_id": "a.b.c\ud800", "problem_version": 1, "code": ""}')],
    ids=["in_a_value", "in_an_unknown_key", "in_a_problem_id"],
)  # fmt: skip
def test_a_lone_surrogate_is_a_422_not_a_crash(client: TestClient, path: str, body: bytes) -> None:
    # "\ud800" is valid JSON but not storable text. FastAPI's default 422 echoed it back and
    # the server crashed encoding it (500). Sent as raw bytes: httpx can't encode it itself.
    headers = {"content-type": "application/json", **_login(client)}
    response = client.post(path, content=body, headers=headers)

    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]  # the bad value is not echoed back


# --- Problems ---


def test_the_problem_list_has_active_problems_in_order(
    client: TestClient, db_session: Session, write_problem: ProblemWriter, bank_root: Path
) -> None:
    # "count_up" sorts first by name but has order 2; "retired" is made inactive.
    for name, order in (("count_up", 2), ("retired", 3)):
        meta = valid_meta() | {"id": f"cs1.loops.{name}", "order": order, "title": name}
        write_problem(meta=meta, folder=f"cs1/03_loops/{name}")
    sync_problems(db_session, bank_root)
    db_session.execute(text("UPDATE problems SET active = false WHERE id = 'cs1.loops.retired'"))
    db_session.commit()

    problems = client.get("/api/problems").json()

    assert [p["id"] for p in problems] == [PROBLEM_ID, "cs1.loops.count_up"]
    assert problems[0] == {
        "id": PROBLEM_ID,
        "title": "Sum of Even Numbers",
        "module": 3,
        "module_name": "Loops",
        "order": 1,
        "difficulty": "easy",
    }


def test_a_problem_shows_only_the_student_view(client: TestClient) -> None:
    response = client.get(f"/api/problems/{PROBLEM_ID}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(StudentProblem.model_fields)
    assert [example["id"] for example in body["examples"]] == ["t01", "t02", "t03", "t04"]
    # Nothing from the internal view: hidden test ids or values (t07: 100 -> 2550), hints,
    # the solution or the buggy code. The student view has no other numbers like these.
    for secret in (*HIDDEN_IDS, "2550", "Hint one.", "range(2, n + 1, 2)", "range(2, n, 2)"):
        assert secret not in response.text


def test_unknown_and_retired_problems_are_404(client: TestClient, db_session: Session) -> None:
    assert client.get("/api/problems/cs1.loops.nope").status_code == 404
    db_session.execute(text("UPDATE problems SET active = false"))
    db_session.commit()
    assert client.get(f"/api/problems/{PROBLEM_ID}").status_code == 404


def test_examples_carry_python_display_text(
    client: TestClient, db_session: Session, write_problem: ProblemWriter, bank_root: Path
) -> None:
    # JavaScript would show the float 32.0 as 32, and None as null: Python formats them.
    tests = valid_tests()
    tests[0] |= {"input": [0], "expected": 32.0, "compare": "float"}
    tests[1] |= {"input": ["it's"], "expected": "Fizz"}
    tests[2] |= {"input": [[1, 2], 3], "expected": None}
    tests[3] |= {"input": [{"a": 1}], "expected": [1, True]}
    meta = valid_meta() | {"id": "cs1.loops.shapes", "order": 2}
    write_problem(meta=meta, tests=tests, folder="cs1/03_loops/shapes")
    sync_problems(db_session, bank_root)
    db_session.commit()

    body = client.get("/api/problems/cs1.loops.shapes").json()

    text = [(e["args_repr"], e["expected_repr"]) for e in body["examples"]]
    assert text == [
        ("0", "32.0"),
        ('"it\'s"', "'Fizz'"),
        ("[1, 2], 3", "None"),
        ("{'a': 1}", "[1, True]"),
    ]
    assert body["examples"][0]["expected"] == 32.0  # the raw JSON value is still there


def test_long_display_text_is_cut() -> None:
    text = py_repr(list(range(1000)))
    assert len(text) == MAX_REPR_CHARS and text.endswith("…")
    assert py_repr("x") == "'x'"


# --- Submitting ---


@pytest.mark.parametrize(
    ("headers", "status"),
    [({}, 401), ({"X-User-Id": "999"}, 401), ({"X-User-Id": "abc"}, 422),
     ({"X-User-Id": "0"}, 422), ({"X-User-Id": str(2**63)}, 422)],
    ids=["no_header", "unknown_user", "not_a_number", "zero", "beyond_bigint"],
)  # fmt: skip
def test_submitting_needs_a_known_user(
    client: TestClient, headers: dict[str, str], status: int
) -> None:
    assert _post_submission(client, headers).status_code == status


def test_a_submission_is_queued_on_the_version_the_student_saw(
    client: TestClient, db_session: Session
) -> None:
    response = _post_submission(client, _login(client))

    assert response.status_code == 202
    submission_id = response.json()["id"]
    assert response.json() == {"id": submission_id, "job_status": "queued"}
    assert response.headers["location"] == f"/api/submissions/{submission_id}"
    row = db_session.get(SubmissionRow, submission_id)
    assert (row.problem_id, row.problem_version, row.job_status) == (PROBLEM_ID, 1, "queued")


def test_a_submission_for_an_old_version_is_refused(
    client: TestClient, db_session: Session, bank_root: Path
) -> None:
    # The student loaded version 1; then a sync stored version 2.
    folder = bank_root / "cs1" / "03_loops" / "sum_of_evens"
    meta = valid_meta() | {"version": 2}
    (folder / "problem.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    sync_problems(db_session, bank_root)
    db_session.commit()

    response = _post_submission(client, _login(client), version=1)

    assert response.status_code == 409
    assert "now version 2" in response.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(SubmissionRow)) == 0


@pytest.mark.parametrize(
    ("problem_id", "code", "status"),
    [("cs1.loops.nope", SOLUTION, 404), (PROBLEM_ID, "x = 1\x00", 422),
     (PROBLEM_ID, "x" * (MAX_CODE_CHARS + 1), 422)],
    ids=["unknown_problem", "nul", "too_long"],
)  # fmt: skip
def test_bad_submissions_are_refused(
    client: TestClient, problem_id: str, code: str, status: int
) -> None:
    response = _post_submission(client, _login(client), code=code, problem_id=problem_id)
    assert response.status_code == status


# --- The editor summary (Week 5 Step 0) ---

STATS = {
    "since_open_ms": 95_000,
    "active_ms": 80_000,
    "typed_chars": 140,
    "pasted_chars": 60,
    "paste_count": 2,
    "largest_paste_chars": 45,
    "edit_count": 120,
    "restored_draft": False,
}


def _post_with_stats(client: TestClient, headers: dict[str, str], stats: object) -> httpx.Response:
    body = {"problem_id": PROBLEM_ID, "problem_version": 1, "code": SOLUTION, "editor_stats": stats}
    return client.post("/api/submissions", json=body, headers=headers)


def test_the_editor_summary_is_stored_as_sent(client: TestClient, db_session: Session) -> None:
    response = _post_with_stats(client, _login(client), STATS)
    assert response.status_code == 202, response.text

    row = db_session.get(SubmissionRow, response.json()["id"])
    assert row is not None and row.editor_stats == STATS


def test_no_editor_summary_is_sql_null_not_json_null(
    client: TestClient, db_session: Session
) -> None:
    submission_id = _submit(client, _login(client))  # like scripts/submit.py: no summary

    is_null = db_session.scalar(
        select(SubmissionRow.editor_stats.is_(None)).where(SubmissionRow.id == submission_id)
    )
    assert is_null is True


@pytest.mark.parametrize(
    "change",
    [
        {"typed_chars": -1},
        {"typed_chars": "140"},  # strict: no strings
        {"typed_chars": 140.0},  # strict: no floats
        {"restored_draft": "false"},
        {"since_open_ms": 31 * 24 * 3600 * 1000},  # above the 30-day bound
        {"keystrokes": [1, 2, 3]},  # unknown key
        {"largest_paste_chars": 61},  # more than pasted_chars
        {"paste_count": 0},  # but 60 characters pasted
        {"active_ms": 96_000},  # more than since_open_ms
    ],
    ids=["negative", "string", "float", "bool_string", "too_long", "unknown_key",
         "largest_paste", "paste_count", "active_ms"],
)  # fmt: skip
def test_a_bad_editor_summary_is_refused_and_nothing_is_saved(
    client: TestClient, db_session: Session, change: dict[str, object]
) -> None:
    response = _post_with_stats(client, _login(client), STATS | change)

    assert response.status_code == 422, response.text
    assert db_session.scalar(select(func.count()).select_from(SubmissionRow)) == 0


def test_a_missing_editor_summary_field_is_refused(client: TestClient) -> None:
    stats = {key: value for key, value in STATS.items() if key != "edit_count"}
    assert _post_with_stats(client, _login(client), stats).status_code == 422


def test_the_editor_summary_never_comes_back(client: TestClient) -> None:
    headers = _login(client)
    submission_id = _post_with_stats(client, headers, STATS).json()["id"]

    one = client.get(f"/api/submissions/{submission_id}", headers=headers).json()
    listed = client.get("/api/submissions", headers=headers).json()

    assert "editor_stats" not in one and all("editor_stats" not in item for item in listed)


@pytest.mark.parametrize("value", ["[1, 2]", "null", "5"])
def test_the_database_refuses_an_editor_summary_that_is_not_an_object(
    client: TestClient, db_session: Session, value: str
) -> None:
    submission_id = _submit(client, _login(client))
    db_session.commit()

    with pytest.raises(IntegrityError, match="ck_submissions_editor_stats_is_object"):
        db_session.execute(
            text("UPDATE submissions SET editor_stats = CAST(:value AS json) WHERE id = :id"),
            {"value": value, "id": submission_id},
        )
    db_session.rollback()


# --- Results ---


def test_a_queued_submission_has_no_result_yet(client: TestClient) -> None:
    headers = _login(client)
    submission_id = _submit(client, headers)

    body = client.get(f"/api/submissions/{submission_id}", headers=headers).json()

    assert (body["job_status"], body["result"], body["message"]) == ("queued", None, None)
    assert body["code"] == SOLUTION


def test_a_graded_result_never_shows_hidden_test_details(
    client: TestClient, db_engine: Engine
) -> None:
    headers = _login(client)
    submission_id = _submit(client, headers, code=BUGGY)
    _grade_next(db_engine)

    body = client.get(f"/api/submissions/{submission_id}", headers=headers).json()

    assert (body["job_status"], body["result_status"]) == ("done", "wrong_answer")
    tests = {test["test_id"]: test for test in body["result"]["tests"]}
    assert (tests["t01"]["input"], tests["t01"]["expected"], tests["t01"]["actual"]) == (
        [10],
        30,
        20,
    )
    assert _display_text(tests["t01"]) == ("10", "30", "20")
    for test_id in HIDDEN_IDS:
        hidden = tests[test_id]
        assert hidden["hidden"] and not hidden["revealed"]
        assert (hidden["input"], hidden["expected"], hidden["actual"]) == (None, None, None)
        assert _display_text(hidden) == (None, None, None)
    assert tests["t07"]["status"] == "wrong_answer"  # the student learns *that* it failed


def test_a_test_with_an_error_has_no_actual_text(client: TestClient, db_engine: Engine) -> None:
    headers = _login(client)
    code = 'def sum_of_evens(n):\n    raise ValueError("no")\n'
    submission_id = _submit(client, headers, code=code)
    _grade_next(db_engine)

    t01 = client.get(f"/api/submissions/{submission_id}", headers=headers).json()["result"][
        "tests"
    ][0]

    assert (t01["status"], t01["error"]) == ("runtime_error", "ValueError: no")
    assert _display_text(t01) == ("10", "30", None)


def test_a_failed_job_shows_a_fixed_message_never_last_error(
    client: TestClient, db_session: Session
) -> None:
    headers = _login(client)
    submission_id = _submit(client, headers)
    db_session.execute(
        text(
            "UPDATE submissions SET job_status = 'failed', finished_at = now(), "
            "last_error = 'OSError: secret detail at /srv/internal' WHERE id = :id"
        ),
        {"id": submission_id},
    )
    db_session.commit()

    response = client.get(f"/api/submissions/{submission_id}", headers=headers)

    assert response.json()["message"] == FAILED_MESSAGE
    assert "secret detail" not in response.text and "last_error" not in response.text


def test_another_users_submission_looks_like_a_missing_one(client: TestClient) -> None:
    submission_id = _submit(client, _login(client, "sara"))
    omar = _login(client, "omar")

    other = client.get(f"/api/submissions/{submission_id}", headers=omar)
    missing = client.get(f"/api/submissions/{submission_id + 1000}", headers=omar)

    assert other.status_code == missing.status_code == 404


def test_my_submissions_are_mine_newest_first(client: TestClient) -> None:
    sara, omar = _login(client, "sara"), _login(client, "omar")
    first, second = _submit(client, sara), _submit(client, sara, code=BUGGY)
    _submit(client, omar)

    mine = client.get("/api/submissions", headers=sara).json()
    other_problem = client.get(
        "/api/submissions", params={"problem_id": "cs1.loops.nope"}, headers=sara
    ).json()
    one = client.get("/api/submissions", params={"limit": 1}, headers=sara).json()

    assert [row["id"] for row in mine] == [second, first]
    assert mine[0]["job_status"] == "queued" and mine[0]["result_status"] is None
    assert "code" not in mine[0]  # the list is a summary
    assert other_problem == []
    assert [row["id"] for row in one] == [second]


@pytest.mark.parametrize("limit", [0, 101, 1000])
def test_the_list_limit_is_checked(client: TestClient, limit: int) -> None:
    response = client.get("/api/submissions", params={"limit": limit}, headers=_login(client))
    assert response.status_code == 422


# --- Rate limits ---


def test_too_many_submissions_in_the_window_are_a_429(
    db_engine: Engine, db_session: Session, bank_root: Path
) -> None:
    with _limited_client(db_engine, RateLimits(per_window=3, max_waiting=100)) as client:
        sara, omar = _login(client, "sara"), _login(client, "omar")
        for _ in range(3):
            _submit(client, sara)

        limited = _post_submission(client, sara)

        assert limited.status_code == 429
        assert "at most 3 per 60 s" in limited.json()["detail"]
        assert 1 <= int(limited.headers["retry-after"]) <= 60
        assert _post_submission(client, omar).status_code == 202  # other users don't wait


def test_too_many_waiting_submissions_are_a_429(
    db_engine: Engine, db_session: Session, bank_root: Path
) -> None:
    with _limited_client(db_engine, RateLimits(max_waiting=2)) as client:
        sara = _login(client)
        _submit(client, sara)
        _submit(client, sara)

        limited = _post_submission(client, sara)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "2"

        _grade_next(db_engine)  # one is graded: one place is free again
        assert _post_submission(client, sara).status_code == 202


def test_submits_at_the_same_moment_never_pass_the_limit(
    db_engine: Engine, db_session: Session, bank_root: Path
) -> None:
    user = UserRow(name="sara")
    db_session.add(user)
    db_session.commit()
    user_id = user.id  # read once here: the threads must not touch db_session's objects
    limits = RateLimits(per_window=5, max_waiting=100)
    threads = 12  # fewer than the engine's 15 pooled connections
    barrier = threading.Barrier(threads)
    outcomes: list[str] = []

    def submit() -> None:
        with Session(db_engine) as session:
            barrier.wait()  # all threads start counting at the same moment
            try:
                create_submission(session, user_id, PROBLEM_ID, 1, SOLUTION, limits)
                session.commit()
                outcomes.append("ok")
            except RateLimitedError:
                outcomes.append("limited")

    workers = [threading.Thread(target=submit) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert (len(outcomes), outcomes.count("ok")) == (threads, 5)
    assert db_session.scalar(select(func.count()).select_from(SubmissionRow)) == 5


# --- Guards ---


EXPECTED_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/login"),
    ("GET", "/api/problems"),
    ("GET", "/api/problems/{problem_id}"),
    ("POST", "/api/submissions"),
    ("GET", "/api/submissions"),
    ("GET", "/api/submissions/{submission_id}"),
    ("POST", "/api/hints"),
    ("GET", "/api/hints"),
    ("GET", "/api/hints/{hint_id}"),
    ("PUT", "/api/hints/{hint_id}/rating"),
    # The instructor dashboard (Week 8): behind X-Instructor-Token
    ("GET", "/api/instructor/overview"),
    ("GET", "/api/instructor/students"),
    ("GET", "/api/instructor/students/{student_id}"),
    ("GET", "/api/instructor/problems"),
}
# Internal fields that must never be part of any request or response.
FORBIDDEN_FIELDS = {
    "last_error",
    "attempts",
    "lease_expires_at",
    "hints",
    "solution_code",
    "buggy",
    "content_hash",
    # The hint trace (Week 4): blocked attempts can contain solution code.
    "settings",
    "retrieved",
    "search_query",
    "student_code",
    "claims",
}


def _field_names(value: object) -> set[str]:
    """Every property name anywhere in an OpenAPI document."""
    names: set[str] = set()
    if isinstance(value, dict):
        names |= set(value.get("properties", {}))
        for item in value.values():
            names |= _field_names(item)
    elif isinstance(value, list):
        for item in value:
            names |= _field_names(item)
    return names


def test_the_api_has_exactly_the_planned_endpoints() -> None:
    spec = create_app().openapi()
    routes = {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}
    assert routes == EXPECTED_ROUTES


def test_no_internal_field_is_part_of_the_api() -> None:
    names = _field_names(create_app().openapi())
    assert "examples" in names and "result" in names  # the walk really finds fields
    assert names.isdisjoint(FORBIDDEN_FIELDS)


def test_the_api_code_never_names_the_table_with_hidden_tests() -> None:
    # A cheap guard until the API has its own database role (docs/ideas.md).
    files = sorted(API_DIR.glob("*.py"))
    assert len(files) >= 5
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "problem_versions" not in source and "ProblemVersionRow" not in source, path


# --- The instructor dashboard (Week 8 Step 1) ---

TEACHER = {"X-Instructor-Token": "t" * 20}
INSTRUCTOR_PATHS = (
    "/api/instructor/overview",
    "/api/instructor/students",
    "/api/instructor/students/1",
    "/api/instructor/problems",
)


@pytest.fixture
def teacher_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the dashboard on with the token in TEACHER."""
    monkeypatch.setenv("INSTRUCTOR_TOKEN", "t" * 20)


def _flag(db_session: Session, submission_id: int, kind: str, reason: str) -> None:
    db_session.add(
        IntegrityFlagRow(
            submission_id=submission_id,
            kind=kind,
            value=1.0,
            reason=reason,
            details={},
            detector_version="test",
        )
    )


def _small_class(client: TestClient, db_engine: Engine, db_session: Session) -> dict[str, int]:
    """sara solves on her first try; bob fails first, then solves. Bob's first submission has
    two flags (one entry signal + one content signal = needs review), sara's one (does not)."""
    sara, bob = _login(client, "sara"), _login(client, "bob")
    ids = {
        "sara": _submit(client, sara, SOLUTION),
        "bob_wrong": _submit(client, bob, BUGGY),
    }
    _grade_next(db_engine)
    _grade_next(db_engine)
    ids["bob_right"] = _submit(client, bob, SOLUTION)
    _grade_next(db_engine)
    _flag(db_session, ids["bob_wrong"], "paste", "One paste of 40 characters.")
    _flag(db_session, ids["bob_wrong"], "same_as_ai", "Same structure as a known AI answer.")
    _flag(db_session, ids["sara"], "paste", "One paste of 20 characters.")
    db_session.commit()
    ids["bob_user"] = int(bob["X-User-Id"])
    return ids


def test_the_dashboard_is_off_without_a_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INSTRUCTOR_TOKEN", raising=False)
    for path in INSTRUCTOR_PATHS:
        assert client.get(path, headers=TEACHER).status_code == 503, path


def test_a_short_token_counts_as_no_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTRUCTOR_TOKEN", "short")
    assert (
        client.get(INSTRUCTOR_PATHS[0], headers={"X-Instructor-Token": "short"}).status_code == 503
    )


def test_a_missing_or_wrong_token_is_refused_and_a_student_login_is_not_enough(
    client: TestClient, teacher_token: None
) -> None:
    student = _login(client)
    for path in INSTRUCTOR_PATHS:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=student).status_code == 401, path
        assert client.get(path, headers={"X-Instructor-Token": "w" * 20}).status_code == 403, path
        assert client.get(path, headers={"X-Instructor-Token": b"\xe9" * 20}).status_code == 403, (
            path
        )


def test_the_class_numbers(
    client: TestClient, db_engine: Engine, db_session: Session, teacher_token: None
) -> None:
    ids = _small_class(client, db_engine, db_session)
    overview = client.get("/api/instructor/overview", headers=TEACHER).json()
    assert (overview["students"], overview["problems"], overview["submissions"]) == (2, 1, 3)
    assert overview["graded"] == 3 and overview["accepted_share"] == 0.67
    assert overview["first_try_solve_share"] == 0.5
    assert (overview["students_to_review"], overview["submissions_to_review"]) == (1, 1)
    assert overview["flags_computed_at"] is not None

    students = client.get("/api/instructor/students", headers=TEACHER).json()
    assert [s["name"] for s in students] == ["bob", "sara"]  # the one to review comes first
    bob, sara = students
    assert (bob["submissions"], bob["problems_solved"], bob["first_try_solve_share"]) == (2, 1, 0.0)
    assert (bob["submissions_to_review"], sara["submissions_to_review"]) == (1, 0)
    assert sara["first_try_solve_share"] == 1.0 and sara["skill"] > bob["skill"]

    problems = client.get("/api/instructor/problems", headers=TEACHER).json()
    assert [(p["id"], p["students"], p["first_try_solve_share"]) for p in problems] == [
        (PROBLEM_ID, 2, 0.5)
    ]
    assert problems[0]["estimated_difficulty"] is not None
    assert ids["bob_user"] == bob["id"]


def test_risk_is_null_early_in_the_course_and_a_number_once_week_three_is_reached(
    client: TestClient, db_engine: Engine, db_session: Session, teacher_token: None
) -> None:
    ids = _small_class(client, db_engine, db_session)  # everything happened in week 1
    overview = client.get("/api/instructor/overview", headers=TEACHER).json()
    students = client.get("/api/instructor/students", headers=TEACHER).json()
    assert overview["risk_available"] is False
    assert all(s["risk"] is None for s in students)

    # Move bob's second try to day 15 after his first: the class now has a week-3 submission.
    first = db_session.get(SubmissionRow, ids["bob_wrong"])
    db_session.get(SubmissionRow, ids["bob_right"]).created_at = first.created_at + timedelta(
        days=15
    )
    db_session.commit()
    overview = client.get("/api/instructor/overview", headers=TEACHER).json()
    students = client.get("/api/instructor/students", headers=TEACHER).json()
    assert overview["risk_available"] is True
    assert all(0.0 <= s["risk"] <= 1.0 for s in students)
    detail = client.get(f"/api/instructor/students/{ids['bob_user']}", headers=TEACHER).json()
    assert detail["risk"] is not None


def test_a_student_page_shows_the_reasons_and_never_the_code(
    client: TestClient, db_engine: Engine, db_session: Session, teacher_token: None
) -> None:
    ids = _small_class(client, db_engine, db_session)
    response = client.get(f"/api/instructor/students/{ids['bob_user']}", headers=TEACHER)
    detail = response.json()
    assert [(p["tries"], p["solved"], p["solved_on_first_try"]) for p in detail["problems"]] == [
        (2, True, False)
    ]
    assert [(f["kind"], f["needs_review"], f["submission_id"]) for f in detail["flags"]] == [
        ("paste", True, ids["bob_wrong"]),
        ("same_as_ai", True, ids["bob_wrong"]),
    ]
    assert detail["flags"][0]["reason"] == "One paste of 40 characters."
    everything = "".join(
        client.get(path, headers=TEACHER).text
        for path in (*INSTRUCTOR_PATHS[:2], INSTRUCTOR_PATHS[3], response.request.url.path)
    )
    assert "def sum_of_evens" not in everything and "return" not in everything


def test_an_unknown_or_silent_student_is_404_and_a_bad_id_is_422(
    client: TestClient, teacher_token: None
) -> None:
    _login(client, "quiet")  # exists, never submitted
    assert client.get("/api/instructor/students/99999", headers=TEACHER).status_code == 404
    assert client.get("/api/instructor/students/1", headers=TEACHER).status_code == 404
    assert client.get("/api/instructor/students/0", headers=TEACHER).status_code == 422


def test_an_empty_class_still_answers(client: TestClient, teacher_token: None) -> None:
    overview = client.get("/api/instructor/overview", headers=TEACHER).json()
    assert overview["students"] == 0 and overview["accepted_share"] is None
    assert overview["skill_fit_settled"] is None
    assert client.get("/api/instructor/students", headers=TEACHER).json() == []
    assert client.get("/api/instructor/problems", headers=TEACHER).json()[0]["students"] == 0
