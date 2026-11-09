"""The public demo API (Deploy Step 2c): the teacher view of a *simulated* class, for anyone.

A separate app in its own container, so the real API has no open teacher routes:
- only the four instructor GET routes exist (no guest, login, submissions or hints);
- no token, because the data is 60 invented students, not people;
- it connects as the read-only role `codetutor_demo` (db/roles.py) to a simulation database,
  and refuses to start on a database whose name does not contain "sim";
- the class is read once per `CACHE_TTL_S` and shared by every visitor (the data never changes
  while it runs, and the Rasch fit costs ~0.3 s).
The numbers come from the same functions as the real dashboard (api/instructor.py).
"""

from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, TypeVar

from fastapi import APIRouter, FastAPI, HTTPException, Path, Response
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from codetutor import __version__
from codetutor.api.app import _AsciiJSONResponse, _database_unavailable
from codetutor.api.deps import SessionDep
from codetutor.api.guards import BodySizeLimit
from codetutor.api.instructor import (
    ClassData,
    OverviewOut,
    ProblemStat,
    StudentDetail,
    StudentRow,
    load_class,
    overview,
    problem_stats,
    student_detail,
    student_rows,
)
from codetutor.api.schemas import MAX_ID
from codetutor.db.admin import database_name
from codetutor.db.engine import make_engine
from codetutor.settings import database_url

CACHE_TTL_S = 300.0  # a model home is built once: recompute at most every 5 minutes
BROWSER_CACHE = "public, max-age=60"
MAX_BODY_BYTES = 1024  # a GET has no body; anything bigger is refused at once
SIM_MARK = "sim"

T = TypeVar("T")


class DemoDatabaseError(RuntimeError):
    """The demo API was pointed at a database that is not a simulation."""


def check_demo_database(url: str) -> None:
    """Refuse a database whose name does not contain "sim" (same rule as `make sim-db`)."""
    name = database_name(url)
    if SIM_MARK not in name:
        raise DemoDatabaseError(
            f"refusing to serve the demo from {name!r}: a demo database name must contain "
            f"{SIM_MARK!r}, so real students can never appear on a public page"
        )


class ClassCache:
    """Keeps one value for `ttl_s` seconds, shared by all requests (thread-safe)."""

    def __init__(self, ttl_s: float = CACHE_TTL_S, clock: Callable[[], float] = time.monotonic):
        self.ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._value: object | None = None
        self._loaded_at: float | None = None

    def get(self, session: Session, load: Callable[[Session], T]) -> T:
        """The cached value, or `load(session)` if there is none or it is older than the TTL."""
        with self._lock:  # one visitor computes, the others wait for that one result
            now = self._clock()
            if self._loaded_at is None or now - self._loaded_at >= self.ttl_s:
                self._value = load(session)
                self._loaded_at = now
            return self._value  # type: ignore[return-value]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if app.state.engine is not None:  # given by a test: the caller disposes it
        yield
        return
    app.state.engine = make_engine()
    try:
        yield
    finally:
        app.state.engine.dispose()
        app.state.engine = None


def create_demo_app(engine: Engine | None = None) -> FastAPI:
    """Build the demo API. Without `engine` it uses DATABASE_URL, which must be a simulation."""
    if engine is None:
        check_demo_database(database_url())
    app = FastAPI(
        title="CodeTutor demo API (simulated class)",
        version=__version__,
        lifespan=_lifespan,
        telemetry={"auto_configure": False},
        default_response_class=_AsciiJSONResponse,
    )
    app.state.engine = engine
    app.state.cache = ClassCache()
    app.add_middleware(BodySizeLimit, max_bytes=MAX_BODY_BYTES)
    app.add_exception_handler(OperationalError, _database_unavailable)

    def cached(response: Response, session: Session) -> ClassData:
        response.headers["Cache-Control"] = BROWSER_CACHE
        return app.state.cache.get(session, load_class)

    # A router per app: its handlers close over this app's cache, so it must not be shared.
    router = APIRouter(prefix="/api/instructor")

    @app.get("/health")
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @router.get("/overview")
    def get_overview(session: SessionDep, response: Response) -> OverviewOut:
        return overview(cached(response, session))

    @router.get("/students")
    def get_students(session: SessionDep, response: Response) -> list[StudentRow]:
        return student_rows(cached(response, session))

    @router.get("/students/{student_id}")
    def get_student(
        session: SessionDep,
        response: Response,
        student_id: Annotated[int, Path(ge=1, le=MAX_ID)],
    ) -> StudentDetail:
        found = student_detail(cached(response, session), student_id)
        if found is None:
            raise HTTPException(404, "no such student (or they have not submitted anything)")
        return found

    @router.get("/problems")
    def get_problems(session: SessionDep, response: Response) -> list[ProblemStat]:
        return problem_stats(cached(response, session))

    app.include_router(router)
    return app
