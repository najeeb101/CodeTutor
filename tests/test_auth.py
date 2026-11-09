"""Sessions, the dev-login switch and the abuse limits (Deploy Step 2a, docs/api.md §2).

The client talks to https://testserver: the session cookie is `Secure`, and a browser (or
httpx) sends a Secure cookie back only over HTTPS.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from starlette.types import Message

from codetutor.api import create_app
from codetutor.api.auth import SESSION_COOKIE
from codetutor.api.guards import BodySizeLimit, IpWindow, client_ip
from codetutor.api.submissions import RateLimits
from codetutor.db.sync import sync_problems
from conftest import BUGGY, ProblemWriter

HTTPS = "https://testserver"
PROBLEM_ID = "cs1.loops.sum_of_evens"


@pytest.fixture
def bank(db_session: Session, write_problem: ProblemWriter) -> Path:
    root = write_problem().parents[2]
    sync_problems(db_session, root)
    db_session.commit()
    return root


def _client(engine: Engine, limits: RateLimits | None = None, **options: Any) -> TestClient:
    """The API in production mode unless `options` say otherwise (use it in a `with` block)."""
    options.setdefault("dev_login", False)
    return TestClient(create_app(engine=engine, limits=limits, **options), base_url=HTTPS)


@pytest.fixture
def client(db_engine: Engine, bank: Path) -> Iterator[TestClient]:
    with _client(db_engine) as client:
        yield client


def _guest(client: TestClient, ip: str | None = None) -> dict[str, Any]:
    headers = {"X-Forwarded-For": ip} if ip else {}
    response = client.post("/api/guest", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _submit(client: TestClient) -> Any:
    body = {"problem_id": PROBLEM_ID, "problem_version": 1, "code": BUGGY}
    return client.post("/api/submissions", json=body)


# --- sessions -----------------------------------------------------------------------------


def test_a_guest_gets_a_locked_down_session_cookie(client: TestClient) -> None:
    response = client.post("/api/guest")

    assert response.status_code == 200
    assert response.json()["name"].startswith("guest-")
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for part in ("httponly", "secure", "samesite=lax", "path=/api", "max-age="):
        assert part in cookie
    assert client.get("/api/me").json() == response.json()


def test_only_the_hash_of_the_token_is_stored(client: TestClient, db_session: Session) -> None:
    _guest(client)
    token = client.cookies[SESSION_COOKIE]

    stored = db_session.scalars(text("SELECT token_hash FROM sessions")).all()
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in stored


def test_without_a_session_there_is_no_user(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert _submit(client).status_code == 401


def test_a_made_up_token_is_refused(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE, "not-a-real-token", domain="testserver")
    assert client.get("/api/me").status_code == 401


def test_logout_ends_the_session_for_good(client: TestClient, db_session: Session) -> None:
    _guest(client)
    token = client.cookies[SESSION_COOKIE]

    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, token, domain="testserver")  # an old copy of the cookie
    assert client.get("/api/me").status_code == 401
    assert db_session.scalar(text("SELECT count(*) FROM sessions")) == 0


def test_another_guests_submission_looks_missing(db_engine: Engine, bank: Path) -> None:
    with _client(db_engine) as alice, _client(db_engine) as bob:
        _guest(alice)
        _guest(bob)
        submission_id = _submit(alice).json()["id"]

        assert alice.get(f"/api/submissions/{submission_id}").status_code == 200
        assert bob.get(f"/api/submissions/{submission_id}").status_code == 404


# TODO(najeeb): write `test_an_expired_session_is_refused`. Start a guest, then move the
# session's expiry into the past with SQL (db_session.execute(text("UPDATE sessions SET
# expires_at = now() - interval '1 minute'")); db_session.commit()). /api/me must now be 401.


# --- the dev-login switch -----------------------------------------------------------------


def test_dev_login_is_off_unless_switched_on(
    db_engine: Engine, bank: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODETUTOR_DEV_LOGIN", raising=False)
    with TestClient(create_app(engine=db_engine), base_url=HTTPS) as client:
        user_id = _guest(client)["id"]
        client.cookies.clear()

        assert client.post("/api/login", json={"name": "sara"}).status_code == 404
        assert client.get("/api/me", headers={"X-User-Id": str(user_id)}).status_code == 401


def test_dev_login_still_works_when_switched_on(db_engine: Engine, bank: Path) -> None:
    with _client(db_engine, dev_login=True) as client:
        user_id = client.post("/api/login", json={"name": "sara"}).json()["id"]
        assert client.get("/api/me", headers={"X-User-Id": str(user_id)}).json()["name"] == "sara"


# --- limits --------------------------------------------------------------------------------


def test_guests_per_ip_are_limited_and_other_ips_are_not(db_engine: Engine, bank: Path) -> None:
    limits = RateLimits(guests_per_ip=2)
    with _client(db_engine, limits, trusted_proxy_hops=1) as client:
        _guest(client, "1.2.3.4")
        _guest(client, "1.2.3.4")
        third = client.post("/api/guest", headers={"X-Forwarded-For": "1.2.3.4"})
        assert third.status_code == 429
        assert int(third.headers["Retry-After"]) >= 1
        _guest(client, "5.6.7.8")


def test_a_forwarded_for_header_is_ignored_without_a_trusted_proxy(
    db_engine: Engine, bank: Path
) -> None:
    with _client(db_engine, RateLimits(guests_per_ip=2), trusted_proxy_hops=0) as client:
        _guest(client, "1.1.1.1")
        _guest(client, "2.2.2.2")  # a made-up address changes nothing: same socket
        assert client.post("/api/guest", headers={"X-Forwarded-For": "3.3.3.3"}).status_code == 429


def test_guests_in_total_are_limited(db_engine: Engine, bank: Path) -> None:
    limits = RateLimits(guests_per_hour=2)
    with _client(db_engine, limits, trusted_proxy_hops=1) as client:
        _guest(client, "1.0.0.1")
        _guest(client, "1.0.0.2")
        busy = client.post("/api/guest", headers={"X-Forwarded-For": "1.0.0.3"})
        assert busy.status_code == 503
        assert "Retry-After" in busy.headers


def test_a_full_grading_queue_answers_503(db_engine: Engine, bank: Path) -> None:
    limits = RateLimits(max_queue=1)
    with _client(db_engine, limits) as alice, _client(db_engine, limits) as bob:
        _guest(alice)
        _guest(bob)
        assert _submit(alice).status_code == 202
        busy = _submit(bob)
        assert busy.status_code == 503
        assert "Retry-After" in busy.headers


def test_a_full_hint_queue_answers_503(db_engine: Engine, bank: Path) -> None:
    limits = RateLimits(max_hint_queue=1)
    body = {"problem_id": PROBLEM_ID, "problem_version": 1, "level": 1, "code": BUGGY}
    with _client(db_engine, limits) as alice, _client(db_engine, limits) as bob:
        _guest(alice)
        _guest(bob)
        assert alice.post("/api/hints", json=body).status_code == 202
        assert bob.post("/api/hints", json=body).status_code == 503


def test_a_too_big_body_is_refused(db_engine: Engine, bank: Path) -> None:
    with _client(db_engine, RateLimits(max_body_bytes=1_000)) as client:
        _guest(client)
        body = {"problem_id": PROBLEM_ID, "problem_version": 1, "code": "x" * 2_000}
        assert client.post("/api/submissions", json=body).status_code == 413


def _drive(middleware: BodySizeLimit, chunks: list[bytes], headers: list[tuple[bytes, bytes]]):
    """Send `chunks` through the middleware as one streamed request; return what it sent."""
    sent: list[Message] = []
    pending = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]

    async def receive() -> Message:
        return pending.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers}
    asyncio.run(middleware(scope, receive, send))
    return sent


async def _read_everything(scope: Any, receive: Any, send: Any) -> None:
    """A tiny app that reads the whole body, then answers 200."""
    while (await receive()).get("more_body"):
        pass
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_a_streamed_body_without_a_length_is_cut_off_at_the_limit() -> None:
    middleware = BodySizeLimit(_read_everything, max_bytes=10)
    sent = _drive(middleware, [b"12345", b"67890", b"x"], headers=[])
    assert sent[0]["status"] == 413


def test_a_declared_length_over_the_limit_is_refused_before_reading() -> None:
    middleware = BodySizeLimit(_read_everything, max_bytes=10)
    sent = _drive(middleware, [b"1"], headers=[(b"content-length", b"11")])
    assert sent[0]["status"] == 413


def test_a_body_at_the_limit_passes() -> None:
    middleware = BodySizeLimit(_read_everything, max_bytes=10)
    assert _drive(middleware, [b"12345", b"67890"], headers=[])[0]["status"] == 200


@pytest.mark.parametrize(
    ("forwarded", "hops", "expected"),
    [
        (None, 0, "10.0.0.9"),
        ("1.2.3.4", 0, "10.0.0.9"),  # no trusted proxy: the header is ignored
        ("1.2.3.4", 1, "1.2.3.4"),
        ("6.6.6.6, 1.2.3.4", 1, "1.2.3.4"),  # the client wrote 6.6.6.6 itself: ignored
        ("6.6.6.6, 1.2.3.4, 172.18.0.5", 2, "1.2.3.4"),
        (None, 1, "10.0.0.9"),  # did not come through the proxy at all
    ],
)
def test_client_ip_trusts_exactly_the_configured_proxies(
    forwarded: str | None, hops: int, expected: str
) -> None:
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    assert client_ip(headers, "10.0.0.9", hops) == expected


def test_the_ip_window_forgets_old_requests() -> None:
    window = IpWindow(limit=2, window_s=60)
    assert window.hit("a", now=0) is None
    assert window.hit("a", now=1) is None
    assert window.hit("a", now=2) == 58  # wait until the first one is 60 s old
    assert window.hit("a", now=61) is None
