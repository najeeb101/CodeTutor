"""The tutor's queue and worker (Week 4 Step 3, docs/tutor.md §4), with a fake model."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from codetutor.db.models import HintRow, JobStatus, UserRow
from codetutor.db.sync import sync_problems
from codetutor.evals.clients import ModelUnavailableError
from codetutor.grader import SubprocessSandbox
from codetutor.tutor.context import HintRequest
from codetutor.tutor.jobs import (
    HintJob,
    claim_next_hint,
    enqueue_hint,
    release_hint,
    save_hint_result,
)
from codetutor.tutor.loop import Tutor, process_hint_job, run_tutor_worker
from codetutor.tutor.service import TutorConfig, give_hint, save_hint
from codetutor.worker.jobs import MAX_ATTEMPTS, claim_next_job, enqueue_submission
from codetutor.worker.loop import Outcome, load_problem_copy, process_job
from conftest import BUGGY, SOLUTION, ProblemWriter, ScriptedModel

PROBLEM_ID = "cs1.loops.sum_of_evens"  # the conftest problem: t01-t04 visible, t05-t08 hidden
GOOD = "Look at where your range stops: is n itself included?"
# No note search in these tests (the search has its own tests): keyword search on an empty
# notes table finds nothing, without an embedder.
CONFIG = TutorConfig(search_method="keyword")


@pytest.fixture
def user_id(db_session: Session, write_problem: ProblemWriter) -> int:
    """A user, and the conftest problem synced into the test database."""
    sync_problems(db_session, write_problem().parents[2])
    user = UserRow(name="sara")
    db_session.add(user)
    db_session.commit()
    return user.id


def _ask(session: Session, user_id: int, level: int = 1, code: str = BUGGY, **options: Any) -> int:
    hint_id = enqueue_hint(
        session, user_id=user_id, problem_id=PROBLEM_ID, level=level, code=code, **options
    )
    session.commit()
    return hint_id


def _claim(engine: Engine, lease_s: float = 300.0) -> HintJob:
    with Session(engine) as session, session.begin():
        job = claim_next_hint(session, lease_s=lease_s)
    assert job is not None
    return job


def _answer(engine: Engine, model: ScriptedModel) -> Outcome:
    """One worker step with this model: claim, answer, save."""
    return process_hint_job(engine, Tutor(model, config=CONFIG), _claim(engine), {})


def _row(session: Session, hint_id: int) -> HintRow:
    session.expire_all()
    return session.get(HintRow, hint_id)


def _user_prompt(model: ScriptedModel, call: int = 0) -> str:
    return model.calls[call][-1]["content"]


def _request(session: Session, code: str = BUGGY, level: int = 1) -> HintRequest:
    problem = load_problem_copy(session, PROBLEM_ID, 1, {})
    return HintRequest(problem, code, level)


def test_a_request_is_queued_on_the_current_version(db_session: Session, user_id: int) -> None:
    row = _row(db_session, _ask(db_session, user_id, question="why?"))
    assert (row.job_status, row.claims, row.problem_version, row.text) == ("queued", 0, 1, None)
    assert (row.student_code, row.question, row.level) == (BUGGY, "why?", 1)


@pytest.mark.parametrize(
    ("options", "error"),
    [
        ({"level": 4}, "level must be one of"),
        ({"question": "x" * 501}, "at most 500"),
        ({"code": "\x00"}, "NUL"),
    ],
)
def test_bad_requests_are_refused(
    db_session: Session, user_id: int, options: dict[str, Any], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        _ask(db_session, user_id, **options)


def test_a_hint_is_claimed_answered_and_saved(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    hint_id = _ask(db_session, user_id)
    model = ScriptedModel(GOOD)
    assert _answer(db_engine, model) is Outcome.DONE
    row = _row(db_session, hint_id)
    assert (row.job_status, row.claims, row.text, row.source) == ("done", 1, GOOD, "model")
    assert row.finished_at is not None and row.lease_expires_at is None
    assert [attempt["text"] for attempt in row.attempts] == [GOOD]
    assert row.settings["search_method"] == "keyword" and row.retrieved == []
    assert "Hint three." not in _user_prompt(model)  # never the bottom-out hint at level 1


def test_level_3_is_the_teachers_last_hint_without_a_model_call(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    hint_id = _ask(db_session, user_id, level=3)
    model = ScriptedModel()  # would fail if called: no replies
    assert _answer(db_engine, model) is Outcome.DONE
    row = _row(db_session, hint_id)
    assert (row.text, row.source, row.model, model.calls) == ("Hint three.", "reference", None, [])


def test_a_model_that_is_down_still_gives_the_teachers_hint(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    hint_id = _ask(db_session, user_id, level=2)
    assert _answer(db_engine, ScriptedModel(ModelUnavailableError("down"))) is Outcome.DONE
    row = _row(db_session, hint_id)
    assert (row.job_status, row.text, row.source) == ("done", "Hint two.", "fallback")
    assert "down" in row.attempts[0]["error"]


def test_an_error_of_ours_puts_the_job_back(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    hint_id = _ask(db_session, user_id)
    assert _answer(db_engine, ScriptedModel(RuntimeError("a bug"))) is Outcome.RETRY
    row = _row(db_session, hint_id)
    assert (row.job_status, row.text) == ("queued", None)
    assert "RuntimeError: a bug" in row.last_error


def test_a_job_fails_after_its_last_claim(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    hint_id = _ask(db_session, user_id)
    for claim in range(1, MAX_ATTEMPTS + 1):
        job = _claim(db_engine)
        with Session(db_engine) as session, session.begin():
            status = release_hint(session, job, "broken")
        assert job.claims == claim
        assert status is (JobStatus.FAILED if claim == MAX_ATTEMPTS else JobStatus.QUEUED)
    with Session(db_engine) as session:
        assert claim_next_hint(session) is None
    assert _row(db_session, hint_id).job_status == "failed"


def test_a_late_save_after_a_lost_lease_writes_nothing(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    hint_id = _ask(db_session, user_id)
    slow = _claim(db_engine, lease_s=0)  # the lease ends at once: as if this worker hung
    fast = _claim(db_engine)  # another worker takes the job over
    assert (slow.claims, fast.claims) == (1, 2)
    late = give_hint(_request(db_session), model=ScriptedModel(GOOD))
    with Session(db_engine) as session, session.begin():
        assert save_hint_result(session, slow, late) is False
    row = _row(db_session, hint_id)
    assert (row.job_status, row.claims, row.text) == ("running", 2, None)


def test_the_graded_result_reaches_the_prompt_without_hidden_details(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    submission_id = enqueue_submission(db_session, user_id, PROBLEM_ID, BUGGY)
    db_session.commit()
    with Session(db_engine) as session, session.begin():
        grading = claim_next_job(session)
    assert process_job(db_engine, SubprocessSandbox(), grading, {}) is Outcome.DONE
    _ask(db_session, user_id, submission_id=submission_id)
    model = ScriptedModel(GOOD)
    assert _answer(db_engine, model) is Outcome.DONE
    prompt = _user_prompt(model)
    # BUGGY stops before n: t01 (10) and t03 (2) fail; hidden t07 (100) fails.
    assert "Visible tests: 2 of 4 passed." in prompt
    assert "sum_of_evens(10) should return 30, but it returned 20" in prompt
    assert "Hidden tests: 3 of 4 passed" in prompt
    assert "100" not in prompt and "2550" not in prompt  # the hidden input and expected value


def test_earlier_hints_for_the_same_code_are_in_the_prompt(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    first = "First, check the last number your range gives."
    _ask(db_session, user_id)
    assert _answer(db_engine, ScriptedModel(first)) is Outcome.DONE
    _ask(db_session, user_id, level=2)
    same_code = ScriptedModel(GOOD)
    assert _answer(db_engine, same_code) is Outcome.DONE
    _ask(db_session, user_id, code=SOLUTION)
    other_code = ScriptedModel(GOOD)
    assert _answer(db_engine, other_code) is Outcome.DONE
    assert "Hints you already gave" in _user_prompt(same_code)
    assert first in _user_prompt(same_code)
    assert first not in _user_prompt(other_code)


def test_the_worker_drains_the_queue_and_keeps_the_models_loaded(
    db_engine: Engine, db_session: Session, user_id: int
) -> None:
    for level in (1, 3):
        _ask(db_session, user_id, level=level)
    calls: list[str] = []

    def keep_loaded() -> None:
        calls.append("load")
        raise ModelUnavailableError("Ollama is down")  # must not stop the worker

    stats = run_tutor_worker(
        db_engine,
        Tutor(ScriptedModel(GOOD), config=CONFIG),
        threading.Event(),
        drain=True,
        keep_loaded=keep_loaded,
        keep_loaded_every_s=0,
    )
    assert (stats.done, stats.retry, stats.failed) == (2, 0, 0)
    assert len(calls) >= 2  # before each claim, as it is always due here
    statuses = db_session.scalars(select(HintRow.job_status).order_by(HintRow.id)).all()
    assert statuses == ["done", "done"]


def test_offline_hints_are_saved_as_done(db_session: Session, user_id: int) -> None:
    """ask_tutor.py and the safety run insert finished rows (service.save_hint)."""
    request = _request(db_session)
    row = save_hint(db_session, request, give_hint(request, model=ScriptedModel(GOOD)))
    db_session.commit()
    saved = _row(db_session, row.id)
    assert (saved.job_status, saved.text, saved.user_id) == ("done", GOOD, None)
    assert saved.finished_at is not None
