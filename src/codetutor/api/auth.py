"""Sessions (Deploy Step 2a): a random token in an HttpOnly cookie, its sha256 in Postgres.

A visitor starts as a guest (`POST /api/guest`): a new user named `guest-<10 hex>` and a
session. The cookie can't be read by the page's scripts (HttpOnly), is sent only over HTTPS
(Secure; browsers treat localhost as secure too) and not with requests that other sites start
(SameSite=Lax). Logging out deletes the session row, so an old copy of the cookie stops working.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from codetutor.db.models import SessionRow, UserRow

SESSION_COOKIE = "codetutor_session"
SESSION_DAYS = 30
TOKEN_BYTES = 32  # 256 random bits: guessing one is hopeless
GUEST_PREFIX = "guest-"
GUEST_NAME_TRIES = 5  # a name clash (1 in 10^12 per try) only means: draw another name


def token_hash(token: str) -> str:
    """The value stored for a token: its sha256 in hex (64 characters)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(session: Session, user_id: int) -> str:
    """Store a new session for the user and return its token (for the cookie). Does not commit."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires = func.now() + timedelta(days=SESSION_DAYS)
    session.execute(
        insert(SessionRow).values(token_hash=token_hash(token), user_id=user_id, expires_at=expires)
    )
    return token


def user_for_token(session: Session, token: str) -> UserRow | None:
    """The user of a live session, or None for an unknown or expired token."""
    return session.scalar(
        select(UserRow)
        .join(SessionRow, SessionRow.user_id == UserRow.id)
        .where(SessionRow.token_hash == token_hash(token), SessionRow.expires_at > func.now())
    )


def end_session(session: Session, token: str) -> None:
    """Delete the session (logging out). Unknown tokens are fine. Does not commit."""
    session.execute(delete(SessionRow).where(SessionRow.token_hash == token_hash(token)))


def create_guest(session: Session) -> UserRow:
    """A new guest user with a fresh random name. Does not commit.

    Never `get_or_create`: an existing name must never log anyone into someone else's account.
    """
    for _ in range(GUEST_NAME_TRIES):
        name = f"{GUEST_PREFIX}{secrets.token_hex(5)}"
        user_id = session.scalar(
            insert(UserRow).values(name=name).on_conflict_do_nothing().returning(UserRow.id)
        )
        if user_id is not None:
            return session.get_one(UserRow, user_id)
    raise RuntimeError("could not find a free guest name")  # practically impossible


def guests_in_last_hour(session: Session) -> int:
    """How many guest users were created in the last hour (the global guest limit)."""
    return session.scalar(
        select(func.count())
        .select_from(UserRow)
        .where(
            UserRow.name.startswith(GUEST_PREFIX, autoescape=True),
            UserRow.created_at > func.now() - timedelta(hours=1),
        )
    )
