"""Smoke test: the local Postgres from compose.yaml is up and is the version we expect."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from codetutor.settings import database_url


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    url = database_url()
    try:
        conn = psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError as exc:
        # Name the host and port only: a real DATABASE_URL contains a password.
        info = conninfo_to_dict(url)
        where = f"{info.get('host')}:{info.get('port', 5432)}"
        pytest.fail(f"cannot reach Postgres at {where} ({exc}). Run `make db-up`.")
    with conn:
        yield conn


def test_server_is_postgres_17(connection: psycopg.Connection) -> None:
    [version] = connection.execute("SHOW server_version_num").fetchone()
    assert int(version) // 10000 == 17


def test_pgvector_is_available(connection: psycopg.Connection) -> None:
    # Available means installable; Week 4 runs CREATE EXTENSION vector in a migration.
    row = connection.execute(
        "SELECT default_version FROM pg_available_extensions WHERE name = 'vector'"
    ).fetchone()
    assert row is not None, "the image has no pgvector extension"
