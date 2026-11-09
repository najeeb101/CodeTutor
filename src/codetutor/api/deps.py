"""FastAPI dependencies: a database session per request, the logged-in user, the limits."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from codetutor.api.auth import SESSION_COOKIE, user_for_token
from codetutor.api.schemas import MAX_ID
from codetutor.api.submissions import RateLimits
from codetutor.db.models import UserRow


def get_session(request: Request) -> Iterator[Session]:
    """One Session per request, closed afterwards (an uncommitted transaction rolls back)."""
    with Session(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def current_user(
    request: Request,
    session: SessionDep,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE, max_length=200)] = None,
    user_id: Annotated[int | None, Header(alias="X-User-Id", ge=1, le=MAX_ID)] = None,
) -> UserRow:
    """The logged-in user: the session cookie's user (api/auth.py).

    Only when the app runs with dev login (settings.dev_login(), `make api`) does the X-User-Id
    header also count. NOT secure: anyone can send any id. The production containers never
    switch it on, so there only a session works.
    """
    if token is not None:
        user = user_for_token(session, token)
        if user is None:
            raise HTTPException(401, "your session has ended; start again")
        return user
    if user_id is not None and request.app.state.dev_login:
        user = session.get(UserRow, user_id)
        if user is None:
            raise HTTPException(401, "unknown user id; log in again")
        return user
    raise HTTPException(401, "start a session first (POST /api/guest)")


UserDep = Annotated[UserRow, Depends(current_user)]


def get_limits(request: Request) -> RateLimits:
    """The rate limits this app was built with (create_app)."""
    return request.app.state.limits


LimitsDep = Annotated[RateLimits, Depends(get_limits)]
