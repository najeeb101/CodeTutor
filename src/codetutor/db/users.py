"""Users (Week 3: name-only dev login, NOT secure: anyone can use any name)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from codetutor.db.models import UserRow


def get_or_create_user(session: Session, name: str) -> int:
    """The id of the user with this name, created if new. Does not commit.

    ON CONFLICT DO NOTHING makes two logins with the same new name at the same moment safe:
    one insert wins, the other does nothing, and both read the same id.
    """
    session.execute(insert(UserRow).values(name=name).on_conflict_do_nothing())
    return session.scalars(select(UserRow.id).where(UserRow.name == name)).one()
