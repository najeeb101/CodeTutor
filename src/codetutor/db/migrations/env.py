"""Alembic environment: how migrations connect to the database. See docs/database.md."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, pool

from codetutor.db.engine import make_engine, sqlalchemy_url
from codetutor.db.models import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the tests run migrations inside pytest; keep its loggers.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The models. `alembic revision --autogenerate` compares them with the database.
target_metadata = Base.metadata


def _url() -> URL:
    """The database to migrate: the caller's URL (the tests pass one), else settings."""
    return sqlalchemy_url(config.attributes.get("url"))


def run_migrations_offline() -> None:
    """Print the SQL instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run the migrations in one transaction (Postgres can roll back DDL too)."""
    # NullPool: a migration needs one connection once, not a pool.
    engine = make_engine(config.attributes.get("url"), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
