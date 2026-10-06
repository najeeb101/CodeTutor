"""Create, drop and migrate whole databases: the test database and the simulated class's.

Moved here from tests/conftest.py in Week 5 Step 1b, because `make sim-db` needs the same thing
for `codetutor_sim`. A database is only dropped if its name contains a given word ("test",
"sim"), so a wrong URL can never wipe the real development database.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

# src/codetutor/db/admin.py -> parents[3] is the repository root (where alembic.ini lives).
ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


class DatabaseNameError(ValueError):
    """Refused to drop a database whose name lacks the required word."""


class DatabaseUnreachableError(RuntimeError):
    """The Postgres server didn't answer (is `make db-up` running?)."""


def database_name(url: str) -> str:
    """The database name in a Postgres URL (also SQLAlchemy-style `postgresql+psycopg://`)."""
    return conninfo_to_dict(url.replace("postgresql+psycopg://", "postgresql://", 1))["dbname"]


def recreate_database(url: str, *, must_contain: str) -> None:
    """Drop the database named in `url` (if it exists) and create it again, empty.

    Refuses a name without `must_contain` (DatabaseNameError) before connecting at all.
    """
    name = database_name(url)
    if must_contain not in name:
        raise DatabaseNameError(
            f"refusing to drop database {name!r}: its name must contain {must_contain!r}"
        )
    # DROP/CREATE DATABASE can't run inside a transaction or while connected to that database,
    # so connect to the server's default "postgres" database with autocommit.
    plain = url.replace("postgresql+psycopg://", "postgresql://", 1)
    admin = make_conninfo(plain, dbname="postgres", connect_timeout=3)
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            # WITH (FORCE) also closes connections left open by an earlier, crashed run.
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.OperationalError as exc:
        info = conninfo_to_dict(plain)  # host and port only: the URL may contain a password
        where = f"{info.get('host')}:{info.get('port', 5432)}"
        raise DatabaseUnreachableError(
            f"cannot reach Postgres at {where} ({exc}). Run `make db-up`."
        ) from exc


def alembic_config(url: str) -> Config:
    """The project's alembic.ini, pointed at `url` (env.py reads the "url" attribute)."""
    config = Config(str(ALEMBIC_INI))
    config.attributes["url"] = url
    return config


def migrate_to_head(url: str) -> None:
    """Run every migration on the database at `url` (the same ones as `make db-migrate`)."""
    command.upgrade(alembic_config(url), "head")
