"""End to end over real HTTP: a real uvicorn server, a real grading worker loop and a real tutor
worker loop with a fake model (all in threads) on the test database, checked by the same code as
`make e2e` (codetutor.e2e)."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from codetutor.api import create_app
from codetutor.db.sync import sync_problems
from codetutor.e2e import Check, forbidden_texts, run_checks
from codetutor.grader import SubprocessSandbox
from codetutor.problems import Problem, load_all
from codetutor.tutor.loop import Tutor, run_tutor_worker
from codetutor.tutor.service import TutorConfig
from codetutor.worker.loop import run_worker
from conftest import ProblemWriter, ScriptedModel

SANDBOX = SubprocessSandbox()  # our own trusted test code (see test_worker.py)
HINT = "Look at where your range stops: is n itself included?"
START_TIMEOUT_S = 10.0


@pytest.fixture
def problem(db_session: Session, write_problem: ProblemWriter) -> Problem:
    """The conftest problem: written, synced into the test database, and loaded from its files."""
    root = write_problem().parents[2]
    sync_problems(db_session, root)
    db_session.commit()
    [problem] = load_all(root)
    return problem


@pytest.fixture
def api_url(db_engine: Engine, problem: Problem) -> Iterator[str]:
    """A real uvicorn server on a free port (uvicorn skips signal handlers outside the main
    thread, so it can run in a thread)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))  # port 0: the system picks a free port
    server = uvicorn.Server(uvicorn.Config(create_app(engine=db_engine), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + START_TIMEOUT_S
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=START_TIMEOUT_S)
    sock.close()


@pytest.fixture
def worker(db_engine: Engine, api_url: str) -> Iterator[None]:
    """The real worker loop, polling every 50 ms, stopped (after its current job) at the end."""
    stop = threading.Event()
    thread = threading.Thread(
        target=run_worker,
        args=(db_engine, SANDBOX, stop),
        kwargs={"poll_interval_s": 0.05},
        daemon=True,
    )
    thread.start()
    yield
    stop.set()
    thread.join(timeout=START_TIMEOUT_S)


@pytest.fixture
def tutor(db_engine: Engine, api_url: str) -> Iterator[None]:
    """The real tutor worker loop with a fake model (one good hint), polling every 50 ms."""
    stop = threading.Event()
    tutor = Tutor(ScriptedModel(HINT), config=TutorConfig(search_method="keyword"))
    thread = threading.Thread(
        target=run_tutor_worker,
        args=(db_engine, tutor, stop),
        kwargs={"poll_interval_s": 0.05},
        daemon=True,
    )
    thread.start()
    yield
    stop.set()
    thread.join(timeout=START_TIMEOUT_S)


def _report(checks: list[Check]) -> str:
    return "\n".join(f"{'ok ' if c.ok else 'BAD'} {c.name}: {c.detail}" for c in checks)


def test_the_whole_chain_works_over_real_http(
    api_url: str, worker: None, tutor: None, problem: Problem
) -> None:
    checks = run_checks(api_url, problem)

    assert all(check.ok for check in checks), _report(checks)
    assert [check.name for check in checks][-5:] == [
        "reference solution is accepted",
        "buggy solution fails, hidden tests stay hidden",
        "my submissions",
        "a hint about the buggy submission",
        "rate the hint",
    ]
    assert checks[-2].detail.startswith("model hint")


def test_without_a_tutor_the_hint_check_fails_and_says_why(
    api_url: str, worker: None, problem: Problem
) -> None:
    checks = run_checks(api_url, problem, hint_timeout_s=1.0)

    assert [check.ok for check in checks][-2:] == [True, False], _report(checks)
    assert checks[-1].name == "a hint about the buggy submission", _report(checks)  # Q19
    assert "is `make tutor` running?" in checks[-1].detail


def test_without_a_worker_the_check_fails_and_says_why(api_url: str, problem: Problem) -> None:
    checks = run_checks(api_url, problem, result_timeout_s=1.0)

    assert [check.ok for check in checks] == [True, True, True, True, False], _report(checks)
    assert checks[-1].name == "reference solution is accepted"
    assert "is `make worker` running?" in checks[-1].detail


def test_forbidden_texts_are_hints_and_the_solutions_own_lines(problem: Problem) -> None:
    # The solution's def line and docstring are in the starter code too, so they are allowed.
    assert forbidden_texts(problem) == [*problem.hints, "return sum(range(2, n + 1, 2))"]
