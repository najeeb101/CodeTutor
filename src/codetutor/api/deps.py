"""FastAPI dependencies: a database session per request, the logged-in user, the limits."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from codetutor.api.schemas import MAX_ID
from codetutor.api.submissions import RateLimits
from codetutor.db.models import UserRow


def get_session(request: Request) -> Iterator[Session]:
    """One Session per request, closed afterwards (an uncommitted transaction rolls back)."""
    with Session(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def current_user(
    session: SessionDep,
    user_id: Annotated[int | None, Header(alias="X-User-Id", ge=1, le=MAX_ID)] = None,
) -> UserRow:
    """The logged-in user. Week 3 dev login: the client sends its user id in X-User-Id.

    NOT SECURE: anyone can send any id. Real authentication (before hosting) replaces only
    this function; the endpoints just ask for a UserRow.
    """
    if user_id is None:
        raise HTTPException(401, "log in first (POST /api/login), then send the X-User-Id header")
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(401, "unknown user id; log in again")
    return user


UserDep = Annotated[UserRow, Depends(current_user)]


def get_limits(request: Request) -> RateLimits:
    """The rate limits this app was built with (create_app)."""
    return request.app.state.limits


LimitsDep = Annotated[RateLimits, Depends(get_limits)]
