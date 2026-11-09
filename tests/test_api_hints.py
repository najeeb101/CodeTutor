"""The hint endpoints (Week 4 Step 3, docs/api.md): queue, levels, limits, rating, no leaks.

The tutor worker runs as plain function calls with a fake model (tests/test_tutor_jobs.py
tests it on its own).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from codetutor.api import create_app
from codetutor.api.hints import create_hint
from codetutor.api.schemas import HINT_FAILED_MESSAGE
from codetutor.api.submissions import RateLimitedError, RateLimits
from codetutor.db.models import HintRow, UserRow
from codetutor.db.sync import sync_problems
from codetutor.grader import SubprocessSandbox
from codetutor.tutor.jobs import claim_next_hint
from codetutor.tutor.loop import Tutor, process_hint_job
from codetutor.tutor.service import TutorConfig
from codetutor.worker.jobs import claim_next_job
from codetutor.worker.loop import Outcome, process_job
from conftest import BUGGY, ProblemWriter, ScriptedModel

PROBLEM_ID = "cs1.loops.sum_of_evens"
GOOD = "Look at where your range stops: is n itself included?"
SOLUTION_LINE = "return sum(range(2, n + 1, 2))"  # from the conftest solution
LEAK = f"Just write `{SOLUTION_LINE}`."
HINT_FIELDS = {
    "id",
    "problem_id",
    "problem_version",
    "submission_id",
    "level",
    "question",
    "created_at",
    "job_status",
    "text",
    "source",
    "rating",
    "message",
}
NO_LIMITS = RateLimits(hint_max_waiting=100, hints_per_window=100)


@pytest.fixture
def bank_root(db_session: Session, write_problem: ProblemWriter) -> Path:
    root = write_problem().parents[2]
    sync_problems(db_session, root)
    db_session.commit()
    return root


def _client(engine: Engine, limits: RateLimits | None = None) -> TestClient:
    return TestClient(create_app(engine=engine, limits=limits, dev_login=True))


@pytest.fixture
def client(db_engine: Engine, db_session: Session, bank_root: Path) -> Iterator[TestClient]:
    """The API on the test database, without hint limits (the limit tests set their own)."""
    with _client(db_engine, NO_LIMITS) as client:
        yield client


def _login(client: TestClient, name: str = "sara") -> dict[str, str]:
    response = client.post("/api/login", json={"name": name})
    assert response.status_code == 200, response.text
    return {"X-User-Id": str(response.json()["id"])}


def _post_hint(client: TestClient, headers: dict[str, str], **changes: Any) -> httpx.Response:
    body: dict[str, Any] = {"problem_id": PROBLEM_ID, "problem_version": 1, "level": 1}
    body |= {"code": BUGGY} if "submission_id" not in changes else {}
    body |= changes
    return client.post("/api/hints", json=body, headers=headers)


def _ask(client: TestClient, headers: dict[str, str], **changes: Any) -> int:
    response = _post_hint(client, headers, **changes)
    assert response.status_code == 202, response.text
    assert response.headers["Location"] == f"/api/hints/{response.json()['id']}"
    return response.json()["id"]


def _answer_next(engine: Engine, *replies: str) -> ScriptedModel:
    """One tutor worker step with a fake model; returns the model (to read its prompts)."""
    model = ScriptedModel(*(replies or (GOOD,)))
    with Session(engine) as session, session.begin():
        job = claim_next_hint(session)
    tutor = Tutor(model, config=TutorConfig(search_method="keyword"))
    assert process_hint_job(engine, tutor, job, {}) is Outcome.DONE
    return model


def _answered(client: TestClient, engine: Engine, headers: dict[str, str], level: int) -> int:
    hint_id = _ask(client, headers, level=level)
    _answer_next(engine)
    return hint_id


def _submit_and_grade(client: TestClient, engine: Engine, headers: dict[str, str]) -> int:
    body = {"problem_id": PROBLEM_ID, "problem_version": 1, "code": BUGGY}
    submission_id = client.post("/api/submissions", json=body, headers=headers).json()["id"]
    with Session(engine) as session, session.begin():
        job = claim_next_job(session)
    assert process_job(engine, SubprocessSandbox(), job, {}) is Outcome.DONE
    return submission_id


# --- Asking and reading ---


def test_asking_needs_a_known_user(client: TestClient) -> None:
    assert _post_hint(client, {}).status_code == 401


def test_a_request_is_queued_then_answered(client: TestClient, db_engine: Engine) -> None:
    headers = _login(client)
    hint_id = _ask(client, headers, question="  why does it fail?  ")
    queued = client.get(f"/api/hints/{hint_id}", headers=headers).json()
    assert (queued["job_status"], queued["text"], queued["source"]) == ("queued", None, None)
    assert queued["question"] == "why does it fail?"
    model = _answer_next(db_engine)
    done = client.get(f"/api/hints/{hint_id}", headers=headers).json()
    assert set(done) == HINT_FIELDS
    assert (done["job_status"], done["text"], done["source"]) == ("done", GOOD, "model")
    assert (done["rating"], done["message"], done["level"]) == (None, None, 1)
    assert "why does it fail?" in model.calls[0][-1]["content"]


def test_the_trace_never_leaves_the_api(
    client: TestClient, db_engine: Engine, db_session: Session
) -> None:
    headers = _login(client)
    hint_id = _ask(client, headers)
    _answer_next(db_engine, LEAK, GOOD)  # the first reply is blocked, the retry is shown
    stored = db_session.get(HintRow, hint_id)
    assert stored.attempts[0]["text"] == LEAK  # the trace has the solution line ...
    answers = [
        client.get(f"/api/hints/{hint_id}", headers=headers),
        client.get("/api/hints", headers=headers),
        client.put(f"/api/hints/{hint_id}/rating", json={"rating": 1}, headers=headers),
    ]
    for answer in answers:
        assert answer.status_code == 200, answer.text
        assert "range(2, n + 1, 2)" not in answer.text  # ... the API never sends it
        assert GOOD in answer.text


def test_a_failed_job_shows_a_fixed_message_never_last_error(
    client: TestClient, db_session: Session
) -> None:
    headers = _login(client)
    hint_id = _ask(client, headers)
    db_session.execute(
        update(HintRow)
        .where(HintRow.id == hint_id)
        .values(job_status="failed", last_error="/home/secret/path.py line 3")
    )
    db_session.commit()
    answer = client.get(f"/api/hints/{hint_id}", headers=headers)
    assert answer.json()["message"] == HINT_FAILED_MESSAGE
    assert "secret" not in answer.text


def test_another_users_hint_looks_like_a_missing_one(client: TestClient) -> None:
    hint_id = _ask(client, _login(client, "sara"))
    omar = _login(client, "omar")
    assert client.get(f"/api/hints/{hint_id}", headers=omar).status_code == 404
    assert client.get(f"/api/hints/{hint_id + 1}", headers=omar).status_code == 404
    assert client.get("/api/hints", headers=omar).json() == []


def test_my_hints_are_mine_newest_first(client: TestClient, db_engine: Engine) -> None:
    headers = _login(client)
    first = _answered(client, db_engine, headers, level=1)
    second = _answered(client, db_engine, headers, level=2)
    _ask(client, _login(client, "omar"))
    mine = client.get(f"/api/hints?problem_id={PROBLEM_ID}", headers=headers).json()
    assert [hint["id"] for hint in mine] == [second, first]
    assert [hint["id"] for hint in client.get("/api/hints?limit=1", headers=headers).json()] == [
        second
    ]
    assert client.get("/api/hints?problem_id=cs1.x.y", headers=headers).json() == []


# --- What a hint is about ---


@pytest.mark.parametrize(
    "changes",
    [
        {"code": BUGGY, "submission_id": 1},  # both
        {"code": None},  # neither
        {"level": 0},
        {"level": 4},
        {"question": "x" * 501},
        {"question": "a\x00b"},
        {"problem_id": "not an id"},
        {"answer": "please"},  # unknown field
    ],
)
def test_bad_requests_are_a_422(client: TestClient, changes: dict[str, Any]) -> None:
    response = _post_hint(client, _login(client), **changes)
    assert response.status_code == 422, response.text


def test_a_lone_surrogate_in_a_question_is_a_422(client: TestClient) -> None:
    # Raw bytes: httpx can't encode "\ud800" itself, but JSON allows the escape.
    body = (
        f'{{"problem_id": "{PROBLEM_ID}", "problem_version": 1, "level": 1, '
        '"code": "x", "question": "\\ud800"}'
    ).encode()
    headers = _login(client) | {"Content-Type": "application/json"}
    response = client.post("/api/hints", content=body, headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "question"]


def test_a_question_may_have_line_breaks(client: TestClient) -> None:
    hint_id = _ask(client, _login(client), question="line one\nline two")
    assert hint_id >= 1


def test_unknown_problems_and_old_versions_are_refused(client: TestClient) -> None:
    headers = _login(client)
    assert _post_hint(client, headers, problem_id="cs1.loops.nope").status_code == 404
    old = _post_hint(client, headers, problem_version=2)
    assert old.status_code == 409 and "reload" in old.json()["detail"]


def test_a_hint_about_my_graded_submission_sees_its_results(
    client: TestClient, db_engine: Engine, db_session: Session
) -> None:
    headers = _login(client)
    submission_id = _submit_and_grade(client, db_engine, headers)
    hint_id = _ask(client, headers, submission_id=submission_id)
    model = _answer_next(db_engine)
    assert "Visible tests: 2 of 4 passed." in model.calls[0][-1]["content"]
    row = db_session.get(HintRow, hint_id)
    assert (row.submission_id, row.student_code) == (submission_id, BUGGY)
    assert client.get(f"/api/hints/{hint_id}", headers=headers).json()["submission_id"] == (
        submission_id
    )


def test_a_submission_must_be_mine_and_graded(client: TestClient) -> None:
    headers = _login(client)
    body = {"problem_id": PROBLEM_ID, "problem_version": 1, "code": BUGGY}
    submission_id = client.post("/api/submissions", json=body, headers=headers).json()["id"]
    waiting = _post_hint(client, headers, submission_id=submission_id)
    assert waiting.status_code == 409 and "not graded yet" in waiting.json()["detail"]
    omar = _post_hint(client, _login(client, "omar"), submission_id=submission_id)
    assert omar.status_code == 404
    assert _post_hint(client, headers, submission_id=submission_id + 1).status_code == 404


# --- Levels ---


def test_levels_go_in_order(client: TestClient, db_engine: Engine) -> None:
    headers = _login(client)
    for level, needed in ((2, 1), (3, 2)):
        refused = _post_hint(client, headers, level=level)
        assert refused.status_code == 409
        assert refused.json()["detail"] == f"ask for a level {needed} hint first"
    _answered(client, db_engine, headers, level=1)
    assert _post_hint(client, headers, level=3).status_code == 409
    _answered(client, db_engine, headers, level=2)
    last = _answered(client, db_engine, headers, level=3)
    hint = client.get(f"/api/hints/{last}", headers=headers).json()
    assert (hint["text"], hint["source"]) == ("Hint three.", "reference")
    assert _post_hint(client, headers, level=1).status_code == 202  # asking again is fine


def test_levels_are_counted_per_user(client: TestClient, db_engine: Engine) -> None:
    _answered(client, db_engine, _login(client, "sara"), level=1)
    assert _post_hint(client, _login(client, "omar"), level=2).status_code == 409


# --- Rating ---


def test_a_finished_hint_can_be_rated_and_rated_again(
    client: TestClient, db_engine: Engine, db_session: Session
) -> None:
    headers = _login(client)
    hint_id = _ask(client, headers)
    early = client.put(f"/api/hints/{hint_id}/rating", json={"rating": 1}, headers=headers)
    assert early.status_code == 409
    _answer_next(db_engine)
    for rating in (1, -1):
        answer = client.put(
            f"/api/hints/{hint_id}/rating", json={"rating": rating}, headers=headers
        )
        assert answer.status_code == 200 and answer.json()["rating"] == rating
    stored = db_session.get(HintRow, hint_id)
    assert stored.rating == -1 and stored.rated_at is not None


@pytest.mark.parametrize("body", [{"rating": 0}, {"rating": 2}, {"rating": "up"}, {}])
def test_only_up_or_down_is_a_rating(
    client: TestClient, db_engine: Engine, body: dict[str, Any]
) -> None:
    headers = _login(client)
    hint_id = _answered(client, db_engine, headers, level=1)
    assert client.put(f"/api/hints/{hint_id}/rating", json=body, headers=headers).status_code == 422


def test_nobody_rates_another_users_hint(client: TestClient, db_engine: Engine) -> None:
    hint_id = _answered(client, db_engine, _login(client, "sara"), level=1)
    omar = _login(client, "omar")
    answer = client.put(f"/api/hints/{hint_id}/rating", json={"rating": -1}, headers=omar)
    assert answer.status_code == 404


# --- Limits ---


def test_one_waiting_hint_at_a_time(
    db_engine: Engine, db_session: Session, bank_root: Path
) -> None:
    with _client(db_engine) as client:  # the default limits
        headers = _login(client)
        _ask(client, headers)
        second = _post_hint(client, headers)
        assert second.status_code == 429 and second.headers["Retry-After"] == "2"
        assert "still answering" in second.json()["detail"]
        _answer_next(db_engine)
        assert _post_hint(client, headers).status_code == 202


def test_too_many_hints_in_the_window_are_a_429(
    db_engine: Engine, db_session: Session, bank_root: Path
) -> None:
    limits = RateLimits(hint_max_waiting=100, hints_per_window=2, hint_window_s=600)
    with _client(db_engine, limits) as client:
        headers = _login(client)
        _ask(client, headers)
        _ask(client, headers)
        third = _post_hint(client, headers)
        assert third.status_code == 429
        assert 590 <= int(third.headers["Retry-After"]) <= 600
        assert third.json()["detail"] == "too many hints: at most 2 per 10 minutes"


def test_requests_at_the_same_moment_never_pass_the_limit(
    db_engine: Engine, db_session: Session, bank_root: Path
) -> None:
    user = UserRow(name="sara")
    db_session.add(user)
    db_session.commit()
    user_id = user.id  # read once here: the threads must not touch db_session's objects
    limits = RateLimits(hint_max_waiting=100, hints_per_window=5)
    threads = 12  # fewer than the engine's 15 pooled connections
    barrier = threading.Barrier(threads)
    outcomes: list[str] = []

    def ask() -> None:
        with Session(db_engine) as session:
            barrier.wait()  # all threads start counting at the same moment
            try:
                create_hint(
                    session,
                    user_id,
                    problem_id=PROBLEM_ID,
                    problem_version=1,
                    level=1,
                    limits=limits,
                    code=BUGGY,
                )
                session.commit()
                outcomes.append("ok")
            except RateLimitedError:
                outcomes.append("limited")

    workers = [threading.Thread(target=ask) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert (len(outcomes), outcomes.count("ok")) == (threads, 5)
    assert db_session.scalar(select(func.count()).select_from(HintRow)) == 5
