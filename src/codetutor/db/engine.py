"""Connecting to Postgres with SQLAlchemy."""

from __future__ import annotations

from typing import Any

from sqlalchemy import URL, Engine, create_engine, make_url

from codetutor.settings import DB_CONNECT_TIMEOUT_S, database_url

# SQLAlchemy needs the driver in the URL. "postgresql+psycopg" is psycopg 3 (installed in
# Step 0); a plain "postgresql://" would make SQLAlchemy look for psycopg2.
DRIVER = "postgresql+psycopg"


def sqlalchemy_url(url: str | None = None) -> URL:
    """Turn a plain Postgres URL (default: settings.database_url()) into a SQLAlchemy URL."""
    return make_url(url or database_url()).set(drivername=DRIVER)


def make_engine(url: str | None = None, **options: Any) -> Engine:
    """Create an engine (a connection pool) for `url` (default: settings.database_url()).

    `options` go to sqlalchemy.create_engine (Alembic passes its own pool class).
    """
    return create_engine(
        sqlalchemy_url(url),
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_S},  # fail fast if the DB is down
        # Test a pooled connection before using it, so a database restart gives a fresh
        # connection instead of an error.
        pool_pre_ping=True,
        **options,
    )
