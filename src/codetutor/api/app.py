"""The FastAPI app (Week 3 Step 3). See docs/api.md.

Run it with `make api` (uvicorn on 127.0.0.1:8000). The API never grades: it saves the
submission row (that row is the job), and the worker grades it (docs/worker.md).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from codetutor import __version__, settings
from codetutor.api.guards import BodySizeLimit, IpWindow
from codetutor.api.instructor import router as instructor_router
from codetutor.api.routes import router
from codetutor.api.submissions import RateLimits
from codetutor.db.engine import make_engine

DEV_LOGIN_WARNING = (
    "dev login is ON: X-User-Id and POST /api/login also identify users (NOT secure: anyone "
    "can send any id). Keep the API on 127.0.0.1; production never sets CODETUTOR_DEV_LOGIN."
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown: open the database pool, unless the caller gave an engine."""
    if app.state.dev_login:
        log.warning(DEV_LOGIN_WARNING)
    if app.state.engine is not None:  # given to create_app (tests): the caller disposes it
        yield
        return
    app.state.engine = make_engine()
    try:
        yield
    finally:
        app.state.engine.dispose()
        app.state.engine = None


class _AsciiJSONResponse(JSONResponse):
    """JSON with every non-ASCII character escaped (\\uXXXX): still valid JSON for any client.

    Starlette's JSONResponse encodes to UTF-8, which can't encode a lone surrogate ("\\ud800",
    valid in JSON). Echoing one from a bad request crashed the server (500, found by a test).
    """

    def render(self, content: object) -> bytes:
        return json.dumps(content, ensure_ascii=True, allow_nan=False).encode("ascii")


async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 for a request that doesn't match its model, without echoing the input back.

    FastAPI's default answer includes each bad value, which could be 50 000 characters of code
    or text that can't be encoded. The type, the place (`loc`) and the message are enough.
    """
    errors = [
        {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]
    return _AsciiJSONResponse({"detail": errors}, status_code=422)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """Postgres is down or unreachable: 503 with a short message (the details go to the log)."""
    log.error("database unavailable: %s", exc)
    return JSONResponse({"detail": "database unavailable, try again soon"}, status_code=503)


def create_app(
    engine: Engine | None = None,
    limits: RateLimits | None = None,
    *,
    dev_login: bool | None = None,
    trusted_proxy_hops: int | None = None,
) -> FastAPI:
    """Build the API. Without `engine`, it connects to settings.database_url() at startup.

    uvicorn calls this with no arguments (`--factory`), so dev login and the trusted proxies
    come from the environment (settings.py); tests pass the test database's engine, smaller
    limits and the switches.
    """
    app = FastAPI(
        title="CodeTutor API",
        version=__version__,
        lifespan=_lifespan,
        # FastAPI includes the OpenTelemetry API (it does nothing without an SDK). This also
        # stops OTEL_* environment variables from adding exporters: tracing is a Week 4
        # decision (Langfuse), and no data should leave the machine without one.
        telemetry={"auto_configure": False},
    )
    app.state.engine = engine
    app.state.limits = limits = limits or RateLimits()
    app.state.dev_login = settings.dev_login() if dev_login is None else dev_login
    app.state.trusted_proxy_hops = (
        settings.trusted_proxy_hops() if trusted_proxy_hops is None else trusted_proxy_hops
    )
    app.state.guest_ips = IpWindow(limits.guests_per_ip, limits.guest_ip_window_s)
    app.add_middleware(BodySizeLimit, max_bytes=limits.max_body_bytes)
    app.include_router(router)
    app.include_router(instructor_router)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(OperationalError, _database_unavailable)
    return app
